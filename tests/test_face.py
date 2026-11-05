"""Uses a fake bridge that follows the real protocol, so OpenFace isn't needed."""

import stat
import sys
import textwrap
import time
from pathlib import Path

import numpy as np
import pytest

from preop.cli import format_tick
from preop.features.body import Person
from preop.features.face import FaceExtractor, FaceFeatures, FaceUnavailable, parse_result
from preop.pipeline import Pipeline
from preop.types import VideoFrame


def fake_detect(t, image) -> list[Person]:
    points = np.zeros((33, 3), dtype=np.float32)
    points[:, :2] = 0.5
    points[:, 2] = 1.0
    return [Person(points)]


class Frames:
    def __init__(self, seconds: float = 0.6):
        self._seconds = seconds

    def stream(self):
        end = time.monotonic() + self._seconds
        while time.monotonic() < end:
            yield VideoFrame(time.monotonic(), np.zeros((480, 1280, 3), dtype=np.uint8))
            time.sleep(0.02)

    def stop(self):
        pass


def make_bridge(tmp_path: Path, body: str) -> list[str]:
    script = tmp_path / "bridge.py"
    script.write_text(textwrap.dedent(body))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return [sys.executable, str(script)]


GOOD_BRIDGE = """\
import json, struct, sys
print(json.dumps({"ready": True}), flush=True)
while True:
    header = sys.stdin.buffer.read(16)
    if len(header) < 16:
        break
    w, h, t = struct.unpack("<IId", header)
    assert len(sys.stdin.buffer.read(w * h * 3)) == w * h * 3
    assert w <= 640
    print(json.dumps({"detected": True, "confidence": 0.9, "aus": {"AU04": 2.0, "AU12": 0.1},
                      "present": {"AU04": 1.0, "AU12": 0.0}}), flush=True)
"""


def test_parse_result_keeps_values():
    line = b'{"detected":true,"confidence":0.5,"aus":{"AU01":1.5},"present":{"AU01":1}}'
    assert parse_result(line, 3.0) == FaceFeatures(3.0, True, 0.5, {"AU01": 1.5}, {"AU01": 1.0})


def test_active_lists_only_present_units_strongest_first():
    face = FaceFeatures(
        0.0,
        True,
        1.0,
        {"AU01": 1.0, "AU04": 3.0, "AU12": 5.0},
        {"AU01": 1.0, "AU04": 1.0, "AU12": 0.0},
    )
    assert face.active() == [("AU04", 3.0), ("AU01", 1.0)]


def test_no_face_means_no_active_units():
    face = FaceFeatures(0.0, False, 0.0, {"AU01": 1.0}, {"AU01": 1.0})
    assert face.active() == []


def test_extractor_talks_to_bridge_and_downscales_large_frames(tmp_path: Path):
    extractor = FaceExtractor(make_bridge(tmp_path, GOOD_BRIDGE))
    try:
        result = extractor.analyze(1.0, np.zeros((720, 1280, 3), dtype=np.uint8))
    finally:
        extractor.close()
    assert result.detected
    assert result.aus["AU04"] == 2.0


def test_bridge_that_never_gets_ready_is_reported(tmp_path: Path):
    with pytest.raises(FaceUnavailable):
        FaceExtractor(make_bridge(tmp_path, "print('failed', flush=True)\n"))


def test_missing_bridge_is_reported(tmp_path: Path):
    with pytest.raises(FaceUnavailable, match="build_openface_bridge"):
        FaceExtractor.from_paths(tmp_path / "missing", tmp_path)


def test_pipeline_publishes_face_features(tmp_path: Path):
    extractor = FaceExtractor(make_bridge(tmp_path, GOOD_BRIDGE))
    pipeline = Pipeline(Frames(), detect=fake_detect, analyze_face=extractor.analyze)
    ticks = []
    pipeline.run(ticks.append, duration_s=3, tick_s=0.2)
    extractor.close()
    with_face = [tick for tick in ticks if tick.face is not None]
    assert with_face
    assert "AU04=2.0" in format_tick(with_face[-1])
    assert pipeline.state.face_latencies


def test_bridge_crash_keeps_other_signals_running(tmp_path: Path):
    crash = """\
    import json, sys
    print(json.dumps({"ready": True}), flush=True)
    sys.stdin.buffer.read(16)
    sys.exit(1)
    """
    extractor = FaceExtractor(make_bridge(tmp_path, crash))
    pipeline = Pipeline(Frames(), detect=fake_detect, analyze_face=extractor.analyze)
    ticks = []
    pipeline.run(ticks.append, duration_s=3, tick_s=0.2)
    extractor.close()
    assert pipeline.state.face_error
    assert ticks[-1].body is not None


@pytest.mark.model
def test_real_bridge_finds_no_face_in_a_blank_frame():
    try:
        extractor = FaceExtractor.from_paths()
    except FaceUnavailable:
        pytest.skip("OpenFace bridge not built")
    try:
        assert not extractor.analyze(1.0, np.zeros((480, 640, 3), dtype=np.uint8)).detected
    finally:
        extractor.close()

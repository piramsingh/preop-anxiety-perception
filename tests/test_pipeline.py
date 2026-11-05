"""End-to-end tests on a generated clip. No real audio or video is used."""

import shutil
import subprocess
import threading
import time
import wave
from pathlib import Path

import cv2
import numpy as np
import pytest

from preop.cli import format_tick
from preop.config import Config, load_config
from preop.features.audio import F0_COLUMN, HNR_COLUMN, LOUDNESS_COLUMN, VocalWindow
from preop.features.body import Person
from preop.pipeline import Pipeline
from preop.sources.pulse import SimulatedPulseSource
from preop.sources.video_file import AudioFileSource, VideoFileSource


def fake_analyzer(samples, rate):
    return {F0_COLUMN: 30.0, LOUDNESS_COLUMN: 1.0, HNR_COLUMN: 5.0}


def fake_detect(t, image) -> list[Person]:
    points = np.zeros((33, 3), dtype=np.float32)
    points[:, 0] = 0.5 + 0.1 * np.sin(t * 10)
    points[:, 1] = 0.5
    points[:, 2] = 1.0
    return [Person(points)]


@pytest.fixture
def clip(tmp_path: Path) -> Path:
    """Three seconds of generated video with a tone, muxed with ffmpeg."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    silent = tmp_path / "silent.mp4"
    writer = cv2.VideoWriter(str(silent), cv2.VideoWriter_fourcc(*"mp4v"), 15, (64, 48))
    for _ in range(45):
        writer.write(np.zeros((48, 64, 3), dtype=np.uint8))
    writer.release()
    audio = tmp_path / "tone.wav"
    samples = (0.1 * np.sin(2 * np.pi * 220 * np.arange(48000) / 16000) * 32767).astype(np.int16)
    with wave.open(str(audio), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(samples.tobytes())
    output = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-loglevel", "quiet", "-i", str(silent), "-i", str(audio),
         "-c:v", "copy", "-c:a", "aac", str(output)],
        check=True,
    )  # fmt: skip
    return output


def test_replay_reaches_a_score_with_both_signals(clip: Path):
    start = time.monotonic()
    pipeline = Pipeline(
        VideoFileSource(clip, start),
        AudioFileSource(clip, start),
        SimulatedPulseSource(period_s=0.2),
        fake_detect,
        VocalWindow(fake_analyzer, window_s=1.0, hop_s=0.5),
    )
    ticks = []
    pipeline.run(ticks.append, duration_s=10, tick_s=0.5)

    assert time.monotonic() - start < 8  # It stopped when the file ended, not at the duration.
    full = [tick for tick in ticks if tick.body and tick.vocal]
    assert full, "expected a tick with both video and audio features"
    assert full[-1].score.value is not None
    assert full[-1].score.confidence > 0.9
    assert full[-1].pulse is not None and full[-1].pulse.simulated
    assert "PLACEHOLDER" in format_tick(full[-1])
    assert pipeline.state.frames > 0


def test_score_keeps_working_with_video_only(clip: Path):
    pipeline = Pipeline(VideoFileSource(clip), detect=fake_detect)
    ticks = []
    pipeline.run(ticks.append, duration_s=5, tick_s=0.5)
    scored = [tick for tick in ticks if tick.score.value is not None]
    assert scored
    assert scored[-1].vocal is None
    assert scored[-1].score.confidence < 0.7


def test_stale_features_stop_counting():
    class OneFrame:
        def stream(self):
            from preop.types import VideoFrame

            yield VideoFrame(time.monotonic(), np.zeros((4, 4, 3), dtype=np.uint8))

        def stop(self):
            pass

    pipeline = Pipeline(OneFrame(), detect=fake_detect)
    pipeline.run(lambda tick: None, duration_s=0.1, tick_s=0.1)
    assert pipeline.snapshot(time.monotonic() + 10).body is None


def test_source_errors_reach_the_caller():
    class Broken:
        def stream(self):
            raise RuntimeError("device gone")
            yield

        def stop(self):
            pass

    with pytest.raises(RuntimeError, match="device gone"):
        Pipeline(Broken(), detect=fake_detect).run(lambda tick: None, duration_s=2, tick_s=0.1)


def test_simulated_pulse_stops_promptly():
    source = SimulatedPulseSource(period_s=5.0)
    thread = threading.Thread(target=lambda: list(source.stream()))
    thread.start()
    source.stop()
    thread.join(timeout=1.0)
    assert not thread.is_alive()


def test_default_yaml_matches_defaults():
    assert load_config(Path("config/default.yaml")) == Config()


@pytest.mark.model
def test_pose_runs_on_blank_image_without_finding_people():
    model = Path("models/pose_landmarker_full.task")
    if not model.exists():
        pytest.skip("pose model not downloaded")
    from preop.features.pose import PoseExtractor

    extractor = PoseExtractor(model_path=model)
    try:
        assert extractor.detect(1.0, np.zeros((240, 320, 3), dtype=np.uint8)) == []
    finally:
        extractor.close()

"""Dashboard server tests with generated frames. No real audio or video is used."""

import json
import re
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from preop.config import Config
from preop.dashboard.server import STATIC, create_app
from preop.dashboard.session import SessionManager, encode_frame, tick_to_dict
from preop.features.body import BodyFeatures, Person
from preop.pipeline import Pipeline, Tick
from preop.score.scorer import DistressScore, MypasScorer
from preop.sources.pulse import SimulatedPulseSource
from preop.types import PulseSample, VideoFrame

LOCAL = {"Host": "127.0.0.1:8765"}


class Frames:
    def __init__(self, count: int = 1000) -> None:
        self._count, self._stopped = count, False

    def stream(self):
        for _ in range(self._count):
            if self._stopped:
                return
            yield VideoFrame(time.monotonic(), np.zeros((48, 64, 3), dtype=np.uint8))
            time.sleep(0.01)

    def stop(self):
        self._stopped = True


def fake_detect(t, image):
    points = np.zeros((33, 3), dtype=np.float32)
    points[:, :2], points[:, 2] = 0.5, 1.0
    return [Person(points)]


def make_manager(count: int = 1000, closed: list | None = None) -> SessionManager:
    def build(config, camera):
        pipeline = Pipeline(
            Frames(count),
            pulse=SimulatedPulseSource(period_s=0.05),
            detect=fake_detect,
            scorer=MypasScorer(config.score.baseline_s),
        )
        if closed is not None:
            pipeline.closers = [lambda: closed.append(True)]
        return pipeline

    return SessionManager(Config(), build, tick_s=0.05)


def client_for(manager: SessionManager) -> TestClient:
    return TestClient(create_app(manager), base_url="http://127.0.0.1:8765")


@pytest.fixture
def video_file(tmp_path: Path) -> str:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"generated")
    return str(path)


def start_body(path: str) -> dict:
    return {"source": "file", "path": path, "baseline_s": 10}


def wait_for(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def test_other_websites_cannot_start_a_session(video_file):
    client = client_for(make_manager())
    response = client.post(
        "/api/session", json=start_body(video_file), headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403


def test_other_local_ports_cannot_start_a_session(video_file):
    client = client_for(make_manager())
    response = client.post(
        "/api/session", json=start_body(video_file), headers={"Origin": "http://127.0.0.1:3000"}
    )
    assert response.status_code == 403


def test_dns_rebinding_host_is_refused():
    client = client_for(make_manager())
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 403


def test_other_websites_cannot_open_the_updates_socket():
    client = client_for(make_manager())
    with pytest.raises(Exception):  # noqa: B017 - the close surfaces as a transport error
        with client.websocket_connect("/ws", headers={**LOCAL, "Origin": "https://evil.example"}):
            pass


def test_page_loads_nothing_from_the_internet():
    for path in STATIC.iterdir():
        urls = re.findall(r"https?://[^\s\"')]+", path.read_text())
        assert [url for url in urls if not url.startswith("http://www.w3.org/")] == [], path


def test_page_is_served():
    response = client_for(make_manager()).get("/")
    assert response.status_code == 200
    assert "Lullaby" in response.text


def test_missing_video_is_a_friendly_error(tmp_path):
    response = client_for(make_manager()).post(
        "/api/session", json=start_body(str(tmp_path / "missing.mp4"))
    )
    assert response.status_code == 400
    assert "wasn't found" in response.json()["detail"]


def test_baseline_shorter_than_the_minimum_is_refused(video_file):
    body = {**start_body(video_file), "baseline_s": 1}
    assert client_for(make_manager()).post("/api/session", json=body).status_code == 422


def test_session_streams_ticks_and_finishes_when_the_source_ends(video_file):
    manager = make_manager(count=40)
    client = client_for(manager)
    with client.websocket_connect("/ws", headers=LOCAL) as socket:
        assert socket.receive_json()["status"] == "idle"
        assert client.post("/api/session", json=start_body(video_file)).status_code == 200
        ticks, last = 0, None
        while last is None or last.get("status") != "finished":
            last = socket.receive_json()
            ticks += last["type"] == "tick"
    assert ticks > 0
    assert len(last["history"]) == ticks
    assert last["settings"]["name"] == "clip.mp4"


def test_only_one_session_at_a_time_and_stop_releases_models(video_file):
    closed: list = []
    manager = make_manager(closed=closed)
    client = client_for(manager)
    assert client.post("/api/session", json=start_body(video_file)).status_code == 200
    assert client.post("/api/session", json=start_body(video_file)).status_code == 409
    wait_for(lambda: manager.status == "running")
    client.post("/api/session/stop")
    manager.join()
    assert manager.status == "stopped"
    assert closed == [True]
    assert client.post("/api/session", json=start_body(video_file)).status_code == 200
    manager.stop()
    manager.join()


def test_source_errors_reach_the_page(video_file):
    def build(config, camera):
        raise RuntimeError("device gone")

    manager = SessionManager(Config(), build)
    client = client_for(manager)
    client.post("/api/session", json=start_body(video_file))
    manager.join()
    assert (manager.status, manager.message) == ("error", "device gone")


def test_reconnecting_page_gets_the_session_so_far(video_file):
    manager = make_manager(count=30)
    client = client_for(manager)
    client.post("/api/session", json=start_body(video_file))
    manager.join()
    with client.websocket_connect("/ws", headers=LOCAL) as socket:
        snapshot = socket.receive_json()
    assert snapshot["status"] == "finished"
    assert snapshot["history"]


def test_tick_is_plain_numbers_and_marks_simulated_heart_rate():
    tick = Tick(
        5.0,
        DistressScore(31.234, 0.5),
        BodyFeatures(5.0, 1, 0.123, None, 0.9),
        None,
        PulseSample(5.0, 96.4, simulated=True),
    )
    data = tick_to_dict(tick, 5.0, face_enabled=False)
    assert json.loads(json.dumps(data)) == data
    assert data["score"] == 31.23
    assert data["signals"]["heart_rate_simulated"] is True
    assert data["signals"]["face_enabled"] is False


def test_frame_encoding_leaves_the_source_frame_untouched():
    image = np.zeros((480, 1280, 3), dtype=np.uint8)
    jpeg = encode_frame(image, fake_detect(0.0, image))
    assert jpeg[:2] == b"\xff\xd8"
    assert image.sum() == 0

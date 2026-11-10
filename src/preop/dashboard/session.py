"""Runs one pipeline at a time for the dashboard and shares its ticks with connected pages."""

import asyncio
import copy
import threading
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

from preop.cli import build_pipeline
from preop.config import Config
from preop.pipeline import Pipeline, Tick
from preop.preview import draw_people
from preop.sources.webcam import WebcamSource

FRAME_WIDTH = 640
JPEG_QUALITY = 70
ACTIVE = ("starting", "running")


class SessionBusy(RuntimeError):
    """A session is already running."""


def _rounded(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def tick_to_dict(tick: Tick, elapsed: float, face_enabled: bool) -> dict:
    """Numbers only. Audio and video never pass through here."""
    score, body, vocal, face, pulse = tick.score, tick.body, tick.vocal, tick.face, tick.pulse
    return {
        "t": round(elapsed, 1),
        "score": _rounded(score.value),
        "confidence": round(score.confidence, 3),
        "progress": round(score.baseline_progress, 3),
        "upset": list(score.upset_during_baseline),
        "items": {
            name: {"rating": round(item.rating, 2), "confidence": round(item.confidence, 3)}
            for name, item in score.items.items()
        },
        "signals": {
            "people": body.people if body else 0,
            "activity": _rounded(body.activity) if body else None,
            "parent_distance": _rounded(body.parent_distance) if body else None,
            "audio": vocal is not None,
            "dbfs": _rounded(vocal.dbfs, 0) if vocal else None,
            "voice": vocal is not None and vocal.pitch_semitones is not None,
            "face_enabled": face_enabled,
            "face": face is not None and face.detected,
            "heart_rate": _rounded(pulse.bpm, 0) if pulse else None,
            "heart_rate_simulated": pulse.simulated if pulse else False,
        },
    }


def encode_frame(image: np.ndarray, people: list) -> bytes:
    canvas = image.copy()
    draw_people(canvas, people)
    height, width = canvas.shape[:2]
    if width > FRAME_WIDTH:
        canvas = cv2.resize(canvas, (FRAME_WIDTH, round(height * FRAME_WIDTH / width)))
    ok, encoded = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    return encoded.tobytes() if ok else b""


class SessionManager:
    def __init__(
        self,
        base_config: Config,
        build: Callable[[Config, WebcamSource | None], Pipeline] = build_pipeline,
        tick_s: float = 1.0,
    ) -> None:
        self.base_config = base_config
        self._build, self._tick_s = build, tick_s
        self._lock = threading.Lock()
        self._listeners: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.pipeline: Pipeline | None = None
        self.status = "idle"  # idle, starting, running, finished, stopped, error
        self.message: str | None = None
        self.settings: dict = {}
        self.history: list[dict] = []

    @property
    def active(self) -> bool:
        return self.status in ACTIVE

    def config_for(self, source: str, path: str | None, baseline_s: float) -> Config:
        config = copy.deepcopy(self.base_config)
        config.score.baseline_s = baseline_s
        if source == "camera":
            config.video.source, config.audio.source = "webcam", "mic"
        else:
            config.video.source, config.video.path = "file", str(Path(path).expanduser())
            config.audio.source, config.audio.path = "file", config.video.path
        return config

    def start(self, config: Config, settings: dict, camera: WebcamSource | None = None) -> None:
        with self._lock:
            if self.active:
                raise SessionBusy
            self.status, self.message, self.pipeline = "starting", None, None
            self.settings, self.history = settings, []
            self._stop = threading.Event()
            self._thread = threading.Thread(
                target=self._run, args=(config, camera, self._stop), daemon=True
            )
        self._publish(self.snapshot())
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float = 5.0) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self, config: Config, camera: WebcamSource | None, stop: threading.Event) -> None:
        pipeline = None
        status, message = "finished", None
        try:
            pipeline = self._build(config, camera)
            with self._lock:
                self.pipeline, self.status = pipeline, "running"
            self._publish(self.snapshot())
            started: list[float] = []

            def on_tick(tick: Tick) -> None:
                started[:] = started or [tick.t]
                data = tick_to_dict(tick, tick.t - started[0], pipeline.face_enabled)
                with self._lock:
                    self.history.append(data)
                self._publish({"type": "tick", "tick": data})

            pipeline.run(on_tick, tick_s=self._tick_s, on_idle=lambda: not stop.is_set())
            if stop.is_set():
                status = "stopped"
            elif pipeline.state.face_error:
                message = f"The face signal stopped partway: {pipeline.state.face_error}"
        except Exception as error:  # noqa: BLE001 - shown to the person running the session
            status, message = "error", str(error) or type(error).__name__
        finally:
            for close in pipeline.closers if pipeline else ():
                close()
        with self._lock:
            self.status, self.message = status, message
        self._publish(self.snapshot())

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "type": "snapshot",
                "status": self.status,
                "message": self.message,
                "settings": self.settings,
                "history": list(self.history),
            }

    def subscribe(self, loop: asyncio.AbstractEventLoop) -> tuple:
        listener = (loop, asyncio.Queue())
        with self._lock:
            self._listeners.add(listener)
        return listener

    def unsubscribe(self, listener: tuple) -> None:
        with self._lock:
            self._listeners.discard(listener)

    def _publish(self, message: dict) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for loop, queue in listeners:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, message)
            except RuntimeError:  # That page's event loop has closed.
                self.unsubscribe((loop, queue))

"""Runs each source on its own thread and publishes the latest features for a 1 Hz score tick."""

import statistics
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from preop.features.audio import VocalFeatures, VocalWindow
from preop.features.body import BodyFeatures, BodyTracker, Person
from preop.score.placeholder import PlaceholderScore, placeholder_score
from preop.sources import Source
from preop.types import AudioChunk, PulseSample, VideoFrame

STALE_AFTER_S = 3.0


@dataclass
class State:
    lock: threading.Lock = field(default_factory=threading.Lock)
    body: BodyFeatures | None = None
    vocal: VocalFeatures | None = None
    pulse: PulseSample | None = None
    pose_latencies: list[float] = field(default_factory=list)
    frames: int = 0
    latest_image: object | None = None
    latest_people: list[Person] = field(default_factory=list)
    errors: list[BaseException] = field(default_factory=list)


@dataclass(frozen=True)
class Tick:
    t: float
    score: PlaceholderScore
    body: BodyFeatures | None
    vocal: VocalFeatures | None
    pulse: PulseSample | None


class Pipeline:
    def __init__(
        self,
        video: Source[VideoFrame] | None = None,
        audio: Source[AudioChunk] | None = None,
        pulse: Source[PulseSample] | None = None,
        detect: Callable[[float, object], list[Person]] | None = None,
        vocal_window: VocalWindow | None = None,
    ) -> None:
        self._video, self._audio, self._pulse = video, audio, pulse
        self._detect = detect
        self._vocal_window = vocal_window
        self.state = State()

    def _guarded(self, target: Callable[[], None]) -> threading.Thread:
        def run() -> None:
            try:
                target()
            except BaseException as error:  # noqa: B036 - reported on the main thread
                with self.state.lock:
                    self.state.errors.append(error)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread

    def _run_video(self) -> None:
        tracker = BodyTracker()
        for frame in self._video.stream():
            height, width = frame.image.shape[:2]
            people = self._detect(frame.t, frame.image)
            features = tracker.update(frame.t, people, aspect=width / height)
            latency = time.monotonic() - frame.t
            with self.state.lock:
                self.state.body = features
                self.state.pose_latencies.append(latency)
                self.state.frames += 1
                self.state.latest_image = frame.image
                self.state.latest_people = list(tracker.confirmed)

    def _run_audio(self) -> None:
        for chunk in self._audio.stream():
            end = chunk.t + chunk.samples.size / chunk.sample_rate
            features = self._vocal_window.push(end, chunk.samples)
            if features is not None:
                with self.state.lock:
                    self.state.vocal = features

    def _run_pulse(self) -> None:
        for sample in self._pulse.stream():
            with self.state.lock:
                self.state.pulse = sample

    def snapshot(self, now: float) -> Tick:
        with self.state.lock:
            body, vocal, pulse = self.state.body, self.state.vocal, self.state.pulse
        body = body if body is not None and now - body.t <= STALE_AFTER_S else None
        vocal = vocal if vocal is not None and now - vocal.t <= STALE_AFTER_S else None
        pulse = pulse if pulse is not None and now - pulse.t <= STALE_AFTER_S else None
        score = placeholder_score(
            body.activity if body else None,
            vocal.dbfs if vocal else None,
            body.confidence if body else 1.0,
        )
        return Tick(now, score, body, vocal, pulse)

    def run(
        self,
        on_tick: Callable[[Tick], None],
        duration_s: float | None = None,
        tick_s: float = 1.0,
        on_idle: Callable[[], bool] | None = None,
    ) -> None:
        """Runs until the sources end, the duration passes, or `on_idle` returns False.

        `on_idle` runs on the calling thread, which is where macOS requires windows to be drawn.
        """
        threads = []
        if self._video is not None and self._detect is not None:
            threads.append(self._guarded(self._run_video))
        if self._audio is not None and self._vocal_window is not None:
            threads.append(self._guarded(self._run_audio))
        finite = threads[:]  # A simulated pulse never ends, so it cannot decide when replay stops.
        if self._pulse is not None:
            threads.append(self._guarded(self._run_pulse))

        start = time.monotonic()
        next_tick = start + tick_s
        try:
            while True:
                if on_idle is None:
                    time.sleep(max(next_tick - time.monotonic(), 0.0))
                else:
                    if not on_idle():
                        return
                    time.sleep(0.01)
                now = time.monotonic()
                with self.state.lock:
                    errors = list(self.state.errors)
                if errors:
                    raise errors[0]
                if now < next_tick:
                    continue
                next_tick = now + tick_s
                on_tick(self.snapshot(now))
                if duration_s is not None and now - start >= duration_s:
                    return
                if finite and not any(thread.is_alive() for thread in finite):
                    with self.state.lock:
                        errors = list(self.state.errors)
                    if errors:
                        raise errors[0]
                    return
        finally:
            for source in (self._video, self._audio, self._pulse):
                if source is not None:
                    source.stop()
            for thread in threads:
                thread.join(timeout=2.0)

    def latency_summary(self) -> str:
        with self.state.lock:
            values = list(self.state.pose_latencies)
            frames = self.state.frames
        if not values:
            return "no video frames processed"
        p50 = statistics.median(values) * 1000
        p95 = sorted(values)[int(len(values) * 0.95) - 1] * 1000
        return f"{frames} frames, capture-to-pose latency p50 {p50:.0f} ms, p95 {p95:.0f} ms"

"""Replay a recorded file through the same pipeline as live capture, paced in real time."""

import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import cv2
import numpy as np

from preop.sources.webcam import SourceUnavailable
from preop.types import AudioChunk, VideoFrame


class VideoFileSource:
    def __init__(self, path: Path, start_t: float | None = None) -> None:
        self._path, self._start_t = Path(path), start_t
        self._stop = threading.Event()

    def stream(self) -> Iterator[VideoFrame]:
        cap = cv2.VideoCapture(str(self._path))
        if not cap.isOpened():
            raise SourceUnavailable(f"Could not open video file: {self._path}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        start = self._start_t if self._start_t is not None else time.monotonic()
        index = 0
        try:
            while not self._stop.is_set():
                ok, image = cap.read()
                if not ok:
                    return
                t = start + index / fps
                index += 1
                delay = t - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                elif delay < -1 / fps:
                    continue  # Behind real time, so skip the frame as a live camera would.
                yield VideoFrame(t, image)
        finally:
            cap.release()

    def stop(self) -> None:
        self._stop.set()


class AudioFileSource:
    """Decodes a file's audio with ffmpeg. A file with no audio track simply yields nothing."""

    def __init__(
        self,
        path: Path,
        start_t: float | None = None,
        sample_rate: int = 16000,
        chunk_s: float = 0.1,
    ) -> None:
        self._path, self._start_t = Path(path), start_t
        self._rate, self._chunk_s = sample_rate, chunk_s
        self._stop = threading.Event()

    def stream(self) -> Iterator[AudioChunk]:
        command = [
            "ffmpeg", "-nostdin", "-loglevel", "quiet", "-i", str(self._path),
            "-vn", "-ac", "1", "-ar", str(self._rate), "-f", "f32le", "-",
        ]  # fmt: skip
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE)
        except FileNotFoundError as error:
            raise SourceUnavailable("ffmpeg is required to read audio from a file") from error
        start = self._start_t if self._start_t is not None else time.monotonic()
        samples_per_chunk = int(self._rate * self._chunk_s)
        position = 0
        try:
            while not self._stop.is_set():
                raw = process.stdout.read(samples_per_chunk * 4)
                if len(raw) < 4:
                    return
                t = start + position / self._rate
                samples = np.frombuffer(raw[: len(raw) // 4 * 4], dtype=np.float32).copy()
                position += len(samples)
                delay = t + len(samples) / self._rate - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                yield AudioChunk(t, samples, self._rate)
        finally:
            process.kill()
            process.wait()

    def stop(self) -> None:
        self._stop.set()

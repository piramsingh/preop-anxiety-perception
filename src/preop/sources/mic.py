import queue
import threading
import time
from collections.abc import Iterator

import numpy as np

from preop.sources.webcam import SourceUnavailable
from preop.types import AudioChunk


def pick_input_device(devices: list[dict], name_hint: str | None) -> int | None:
    """Index of the first input device whose name contains the hint, else None (system default)."""
    if not name_hint:
        return None
    for index, device in enumerate(devices):
        if device.get("max_input_channels", 0) > 0 and name_hint.lower() in device["name"].lower():
            return index
    return None


class MicSource:
    def __init__(
        self, device_hint: str | None = None, sample_rate: int = 16000, chunk_s: float = 0.1
    ) -> None:
        self._hint, self._rate, self._chunk_s = device_hint, sample_rate, chunk_s
        self._stop = threading.Event()
        self._queue: queue.Queue[AudioChunk] = queue.Queue(maxsize=100)
        self.device_name: str | None = None

    def stream(self) -> Iterator[AudioChunk]:
        # Imported here so that machines without PortAudio can still use file sources.
        import sounddevice as sd

        def on_audio(indata, frames, time_info, status) -> None:
            start = time.monotonic() - frames / self._rate
            chunk = AudioChunk(start, indata[:, 0].copy(), self._rate)
            try:
                self._queue.put_nowait(chunk)
            except queue.Full:
                pass  # The consumer stalled. Dropping is safe because audio features are windowed.

        device = pick_input_device(list(sd.query_devices()), self._hint)
        self.device_name = sd.query_devices(device, kind="input")["name"]
        print(f"Microphone: {self.device_name}", flush=True)
        try:
            stream = sd.InputStream(
                device=device,
                channels=1,
                samplerate=self._rate,
                blocksize=int(self._rate * self._chunk_s),
                dtype=np.float32,
                callback=on_audio,
            )
        except sd.PortAudioError as error:
            raise SourceUnavailable(f"Microphone did not open: {error}") from error
        with stream:
            while not self._stop.is_set():
                try:
                    yield self._queue.get(timeout=0.5)
                except queue.Empty:
                    continue

    def stop(self) -> None:
        self._stop.set()

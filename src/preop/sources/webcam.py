import threading
import time
from collections.abc import Iterator

import cv2

from preop.types import VideoFrame


class SourceUnavailable(RuntimeError):
    """A device could not be opened, usually a missing macOS permission."""


class WebcamSource:
    """Live camera. A capture thread keeps only the newest frame, so slow consumers
    skip frames instead of falling behind."""

    def __init__(self, index: int = 0, width: int = 1280, height: int = 720) -> None:
        self._index, self._width, self._height = index, width, height
        self._stop = threading.Event()
        self._cond = threading.Condition()
        self._latest: VideoFrame | None = None
        self._failed = False
        self._cap: cv2.VideoCapture | None = None

    def _capture(self, cap: cv2.VideoCapture) -> None:
        misses = 0
        try:
            while not self._stop.is_set():
                ok, image = cap.read()
                now = time.monotonic()
                if not ok:
                    misses += 1
                    if misses > 30:
                        self._failed = True
                        return
                    time.sleep(0.03)
                    continue
                misses = 0
                with self._cond:
                    self._latest = VideoFrame(now, image)
                    self._cond.notify_all()
        finally:
            cap.release()
            with self._cond:
                self._cond.notify_all()

    def open(self) -> None:
        """Open the camera. Call this on the main thread, because macOS can only show its
        camera permission prompt from there."""
        if self._cap is not None:
            return
        cap = cv2.VideoCapture(self._index, cv2.CAP_AVFOUNDATION)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        if not cap.isOpened():
            raise SourceUnavailable(
                f"Camera {self._index} did not open. Allow camera access for your terminal in "
                "System Settings > Privacy & Security > Camera, then retry."
            )
        self._cap = cap

    def stream(self) -> Iterator[VideoFrame]:
        self.open()
        cap = self._cap
        thread = threading.Thread(target=self._capture, args=(cap,), daemon=True)
        thread.start()
        while not self._stop.is_set():
            with self._cond:
                self._cond.wait_for(
                    lambda: (
                        self._latest is not None or self._stop.is_set() or not thread.is_alive()
                    ),
                    timeout=1.0,
                )
                frame, self._latest = self._latest, None
            if frame is not None:
                yield frame
            elif not thread.is_alive():
                if self._failed:
                    raise SourceUnavailable(
                        "Camera opened but returned no frames. Check camera permission."
                    )
                return

    def stop(self) -> None:
        self._stop.set()

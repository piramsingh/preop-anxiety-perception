"""Facial action units from OpenFace, through the local bridge in native/openface_bridge.

The values are observations for the mYPAS items to use, not emotion labels. OpenFace itself warns
that live action units are less accurate than offline ones, which can use the whole video.
OpenFace tracks one face and may pick the parent when two faces are in view.
"""

import json
import os
import struct
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

MAX_WIDTH = 640
LOAD_TIMEOUT_S = 60.0
DEFAULT_BRIDGE = Path("native/openface_bridge/build/openface_bridge")
DEFAULT_OPENFACE_BIN = Path.home() / "DEV/OpenFace/build/bin"


class FaceUnavailable(RuntimeError):
    """The bridge is not built, failed to start, or stopped."""


@dataclass(frozen=True)
class FaceFeatures:
    t: float
    detected: bool
    confidence: float  # 0-1 from OpenFace
    aus: dict[str, float]  # Intensity, roughly 0-5
    present: dict[str, float]  # 0 or 1

    def active(self, limit: int = 3) -> list[tuple[str, float]]:
        """The strongest action units that OpenFace also marks as present."""
        if not self.detected:
            return []
        found = [(n, v) for n, v in self.aus.items() if self.present.get(n, 0.0) >= 0.5 and v > 0]
        return sorted(found, key=lambda item: item[1], reverse=True)[:limit]


def parse_result(line: bytes, t: float) -> FaceFeatures:
    data = json.loads(line)
    return FaceFeatures(
        t,
        bool(data["detected"]),
        float(data["confidence"]),
        {name: float(value) for name, value in data["aus"].items()},
        {name: float(value) for name, value in data["present"].items()},
    )


class FaceExtractor:
    """Owns the bridge process. `analyze` must be called from one thread at a time."""

    def __init__(self, command: list[str]) -> None:
        try:
            self._process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
        except OSError as error:
            raise FaceUnavailable(f"Could not start the OpenFace bridge: {error}") from error
        self._wait_until_ready()

    @classmethod
    def from_paths(
        cls, bridge: Path | None = None, openface_bin: Path | None = None
    ) -> "FaceExtractor":
        bridge = Path(bridge or os.environ.get("OPENFACE_BRIDGE") or DEFAULT_BRIDGE)
        openface_bin = Path(openface_bin or os.environ.get("OPENFACE_BIN") or DEFAULT_OPENFACE_BIN)
        if not bridge.exists():
            raise FaceUnavailable(
                f"{bridge} not found. Build it with scripts/build_openface_bridge.sh"
            )
        if not openface_bin.exists():
            raise FaceUnavailable(f"OpenFace not found at {openface_bin}")
        return cls([str(bridge), str(openface_bin)])

    def _wait_until_ready(self) -> None:
        lines: list[bytes] = []
        reader = threading.Thread(
            target=lambda: lines.append(self._process.stdout.readline()), daemon=True
        )
        reader.start()
        reader.join(LOAD_TIMEOUT_S)
        if not lines or b"ready" not in lines[0]:
            self.close()
            raise FaceUnavailable("The OpenFace bridge did not finish loading its models")

    def analyze(self, t: float, image: np.ndarray) -> FaceFeatures:
        height, width = image.shape[:2]
        if width > MAX_WIDTH:
            scale = MAX_WIDTH / width
            image = cv2.resize(image, (MAX_WIDTH, round(height * scale)))
            height, width = image.shape[:2]
        try:
            self._process.stdin.write(struct.pack("<IId", width, height, t) + image.tobytes())
            self._process.stdin.flush()
            line = self._process.stdout.readline()
        except (BrokenPipeError, ValueError) as error:
            raise FaceUnavailable("The OpenFace bridge stopped") from error
        if not line:
            raise FaceUnavailable("The OpenFace bridge stopped")
        return parse_result(line, t)

    def close(self) -> None:
        try:
            self._process.stdin.close()
        except OSError:
            pass
        try:
            self._process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()

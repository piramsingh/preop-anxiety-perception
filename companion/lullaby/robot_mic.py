"""Listen through the robot's own microphone (Reachy Mini Audio), for the iPhone remote.

The daemon has no microphone endpoint, so this streams raw audio from `arecord` on the robot
over SSH and stops by itself like the browser panel does: 1 s of quiet after the child spoke,
nothing at all for 7 s, or 10 s max. Recording only starts after the robot has finished
talking, so it doesn't hear its own voice.

Needs SSH access to the robot (key in LULLABY_ROBOT_KEY, default ~/.ssh/id_ed25519_reachy;
user in LULLABY_ROBOT_USER, default pollen).
"""

from __future__ import annotations

import io
import os
import subprocess
import threading
import time
import wave
from pathlib import Path

import numpy as np

RATE = 16000
CHUNK = RATE // 10          # 0.1 s of audio per read
SKIP = 0.25                 # ignore the first moment (speaker tail, relay clicks)
QUIET_AFTER = 1.0           # stop this long after the child stops talking
NOTHING_FOR = 7.0           # give up if nobody speaks at all
MAX_SECONDS = 10.0

USER = os.environ.get("LULLABY_ROBOT_USER", "pollen")
KEY = Path(os.environ.get("LULLABY_ROBOT_KEY", "~/.ssh/id_ed25519_reachy")).expanduser()


class MicError(RuntimeError):
    pass


def _ssh(host: str, command: str) -> list[str]:
    args = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
    if KEY.exists():
        args += ["-i", str(KEY)]
    return args + [f"{USER}@{host}", command]


def _db(x: float) -> float:
    return 20 * np.log10(max(x, 1e-9))


def record(host: str, stop: threading.Event | None = None) -> bytes | None:
    """Record one answer from the robot's mic. Returns WAV bytes, or None if nobody spoke."""
    proc = subprocess.Popen(
        _ssh(host, f"exec arecord -q -D plughw:0,0 -f S16_LE -r {RATE} -c 1 -t raw"),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    chunks: list[np.ndarray] = []
    try:
        started = time.monotonic()
        floor = None
        spoke_at = last_loud = None
        while True:
            if stop is not None and stop.is_set():
                return None
            raw = proc.stdout.read(CHUNK * 2) if proc.stdout else b""
            if len(raw) < CHUNK * 2:
                err = proc.stderr.read().decode(errors="replace").strip() if proc.stderr else ""
                raise MicError(err or "The robot's microphone stopped.")
            x = np.frombuffer(raw, dtype="<i2")
            chunks.append(x)
            t = time.monotonic() - started
            if t < SKIP:
                continue
            level = _db(float(np.sqrt(np.mean((x.astype(np.float32) / 32768) ** 2))))
            if floor is None:
                floor = level
            # speech is clearly above the room's own noise
            loud = level > max(floor + 12, -45)
            if not loud and spoke_at is None:
                floor = floor * 0.9 + level * 0.1  # follow the room's noise, slowly
            if loud:
                last_loud = t
                spoke_at = spoke_at or t
            if spoke_at is not None and t - last_loud >= QUIET_AFTER:
                break
            if spoke_at is None and t >= NOTHING_FOR:
                return None
            if t >= MAX_SECONDS:
                break
    finally:
        proc.kill()
        proc.wait(timeout=3)
    audio = np.concatenate(chunks)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(audio.tobytes())
    return buf.getvalue()

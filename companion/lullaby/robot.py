"""Reachy Mini control: named motions plus sound playback.

Two modes:
  * robot   - real Reachy Mini via the Python SDK (motion) and the daemon REST API (sound)
  * preview - no robot; motions are printed and sound plays on this laptop (afplay)

Conventions checked against reachy_mini 1.12.0:
  * head pitch > 0 looks DOWN (the sleep pose is pitch +24 deg, z -44 mm)
  * antennas are [right, left] in radians; a symmetric pose is [-a, +a],
    0 = straight up, larger a = drooping (sleep is +/-175 deg)
"""

from __future__ import annotations

import logging
import math
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import requests

log = logging.getLogger("lullaby.robot")


@dataclass(frozen=True)
class Key:
    """One keyframe. Angles in degrees, z in mm, antennas (right, left) in degrees."""

    dur: float
    pitch: float = 0
    roll: float = 0
    yaw: float = 0
    z: float = 0
    ant: tuple[float, float] = (-10, 10)


def sym(a: float) -> tuple[float, float]:
    """Both antennas at the same droop angle (0 = straight up)."""
    return (-a, a)


def lean(a: float) -> tuple[float, float]:
    """Both antennas leaning the same way (for wiggles)."""
    return (a, a)


NEUTRAL = Key(0.6, ant=sym(10))

MOTIONS: dict[str, list[Key]] = {
    "neutral": [NEUTRAL],
    "wake": [Key(0.8, pitch=12, z=-10, ant=sym(70)), Key(1.0, pitch=-6, z=6, ant=sym(0)),
             Key(0.5, ant=sym(10))],
    "happy": [Key(0.4, pitch=-8, z=6, ant=lean(25)), Key(0.3, pitch=-8, z=6, ant=lean(-25)),
              Key(0.3, pitch=-8, z=6, ant=lean(25)), Key(0.5, pitch=-4, z=3, ant=sym(5))],
    "tilt": [Key(0.7, roll=14, pitch=-3, ant=sym(25))],
    "nod": [Key(0.35, pitch=12), Key(0.35, pitch=-4), Key(0.35, pitch=12), Key(0.4, pitch=0)],
    "think": [Key(0.9, yaw=15, pitch=-10, roll=-6, ant=(-5, 40))],
    "bounce": [Key(0.25, z=10, ant=sym(0)), Key(0.25, z=-2, ant=sym(25)),
               Key(0.25, z=10, ant=sym(0)), Key(0.3, z=0, ant=sym(10))],
    "wiggle": [Key(0.35, roll=10, ant=lean(30)), Key(0.35, roll=-10, ant=lean(-30)),
               Key(0.35, roll=10, ant=lean(30)), Key(0.4, roll=0, ant=sym(10))],
    "peekaboo": [Key(0.8, pitch=25, z=-15, ant=sym(80)), Key(0.9, pitch=25, z=-15, ant=sym(80)),
                 Key(0.3, pitch=-8, z=8, ant=sym(0)), Key(0.5, pitch=0, ant=sym(10))],
    "breathe": [Key(2.5, pitch=-6, z=8, ant=sym(0)), Key(3.5, pitch=4, z=0, ant=sym(40)),
                Key(2.5, pitch=-6, z=8, ant=sym(0)), Key(3.5, pitch=4, z=0, ant=sym(40))],
    "inhale": [Key(3.0, pitch=-8, z=10, ant=sym(0))],
    "exhale": [Key(4.0, pitch=6, z=-2, ant=sym(45))],
    "sleepy": [Key(2.5, pitch=20, z=-15, ant=sym(100))],
    "sleepy_wake": [Key(1.0, pitch=15, z=-10, ant=sym(80)), Key(2.0, pitch=0, z=0, ant=sym(20))],
    "look_around": [Key(0.8, yaw=25, ant=(-20, 5)), Key(1.2, yaw=-25, ant=(-5, 20)),
                    Key(0.8, yaw=0, ant=sym(10))],
    "celebrate": [Key(0.3, z=12, pitch=-8, ant=lean(35)), Key(0.25, z=12, pitch=-8, ant=lean(-35)),
                  Key(0.25, z=12, pitch=-8, ant=lean(35)), Key(0.25, z=12, pitch=-8, ant=lean(-35)),
                  Key(0.5, z=0, ant=sym(10))],
    "wave": [Key(0.4, roll=12, ant=(-40, 5)), Key(0.4, roll=-12, ant=(-5, 40)),
             Key(0.4, roll=12, ant=(-40, 5)), Key(0.4, roll=-12, ant=(-5, 40)),
             Key(0.5, roll=0, ant=sym(10))],
    # Recovery: tiny and slow (about 6 breaths a minute). No sudden moves.
    "recovery_in": [Key(4.0, pitch=2, z=3, ant=sym(30))],
    "recovery_out": [Key(6.0, pitch=6, z=-2, ant=sym(45))],
}


class Robot:
    def __init__(self, host: str = "reachy-mini.local", preview: bool = False):
        self.host = host
        self.preview = preview
        self.mini = None
        self.daemon_url: str | None = None
        self.error: str | None = None
        self._uploaded: set[str] = set()
        self._lock = threading.Lock()
        self._local_player: subprocess.Popen | None = None

    # ---- connection -------------------------------------------------------
    @property
    def mode(self) -> str:
        return "robot" if self.mini is not None else "preview"

    def connect(self) -> bool:
        if self.preview:
            self.error = None
            return False
        try:
            from reachy_mini import ReachyMini

            self.mini = ReachyMini(host=self.host, media_backend="no_media", timeout=5.0)
            self.daemon_url = self.mini._daemon_http_url  # same daemon the SDK connected to
            self.mini.enable_motors()
            self._uploaded.clear()
            self.set_wobble(True)
            self.move("neutral")
            self.error = None
            log.info("Connected to Reachy Mini at %s", self.daemon_url)
            return True
        except Exception as e:  # noqa: BLE001 - show any connection problem to the nurse
            self.mini = None
            self.error = "Robot not found · preview mode"
            log.warning("Robot not connected (%s). Running in preview mode.", e)
            return False

    def close(self) -> None:
        self.stop_audio()
        if self.mini is not None:
            try:
                self.move("neutral")
                self.mini.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
            self.mini = None

    # ---- motion -----------------------------------------------------------
    def move(self, name: str, stop: threading.Event | None = None) -> None:
        keys = MOTIONS.get(name) or MOTIONS["neutral"]
        for k in keys:
            if stop is not None and stop.is_set():
                return
            self._goto(k)

    def _goto(self, k: Key) -> None:
        if self.mini is None:
            time.sleep(k.dur)
            return
        from reachy_mini.utils import create_head_pose

        with self._lock:
            try:
                self.mini.goto_target(
                    head=create_head_pose(z=k.z, roll=k.roll, pitch=k.pitch, yaw=k.yaw,
                                          mm=True, degrees=True),
                    antennas=[math.radians(k.ant[0]), math.radians(k.ant[1])],
                    duration=k.dur,
                    method="minjerk",
                    body_yaw=0.0,
                )
            except Exception as e:  # noqa: BLE001
                log.warning("Move failed: %s", e)

    # ---- sound ------------------------------------------------------------
    def set_wobble(self, on: bool) -> None:
        """Small head movements that follow the robot's voice."""
        if self.daemon_url:
            self._post(f"/api/media/wobbling/{'enable' if on else 'disable'}")

    def play(self, wav: Path) -> None:
        """Start playing a sound file. Returns immediately."""
        if self.mini is None:
            self.stop_audio()
            self._local_player = subprocess.Popen(["afplay", str(wav)])
            return
        name = wav.name
        if f"{name}:{wav.stat().st_mtime}" not in self._uploaded:  # re-upload re-recordings
            self._upload(wav)
        r = self._post("/api/media/play_sound", json={"file": name})
        if r is None or not r.ok:  # daemon may have restarted and lost the upload
            self._upload(wav)
            self._post("/api/media/play_sound", json={"file": name})

    def stop_audio(self) -> None:
        if self._local_player and self._local_player.poll() is None:
            self._local_player.terminate()
        if self.daemon_url and self.mini is not None:
            self._post("/api/media/stop_sound")

    def _upload(self, wav: Path) -> None:
        with open(wav, "rb") as f:
            r = requests.post(f"{self.daemon_url}/api/media/sounds/upload",
                              files={"file": (wav.name, f, "audio/wav")}, timeout=30)
        r.raise_for_status()
        self._uploaded.add(f"{wav.name}:{wav.stat().st_mtime}")

    def _post(self, path: str, **kw) -> requests.Response | None:
        try:
            return requests.post(f"{self.daemon_url}{path}", timeout=10, **kw)
        except requests.RequestException as e:
            log.warning("Daemon request %s failed: %s", path, e)
            return None

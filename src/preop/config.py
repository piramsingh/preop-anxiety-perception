from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml


@dataclass
class VideoConfig:
    source: Literal["webcam", "file", "off"] = "webcam"
    camera_index: int = 0
    path: str | None = None
    num_poses: int = 2


@dataclass
class AudioConfig:
    source: Literal["mic", "file", "off"] = "mic"
    # Matched by substring so that connected headphones do not silently become the input.
    device_hint: str | None = "MacBook"
    path: str | None = None
    opensmile: bool = True


@dataclass
class PulseConfig:
    source: Literal["simulated", "off"] = "simulated"


@dataclass
class Config:
    video: VideoConfig = field(default_factory=VideoConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    pulse: PulseConfig = field(default_factory=PulseConfig)


def load_config(path: Path | None) -> Config:
    if path is None:
        return Config()
    raw = yaml.safe_load(Path(path).read_text()) or {}
    return Config(
        video=VideoConfig(**(raw.get("video") or {})),
        audio=AudioConfig(**(raw.get("audio") or {})),
        pulse=PulseConfig(**(raw.get("pulse") or {})),
    )

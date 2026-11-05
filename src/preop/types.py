"""Timestamped samples shared by every source. All `t` values use time.monotonic() seconds."""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class VideoFrame:
    t: float
    image: np.ndarray  # HxWx3 uint8, BGR


@dataclass(frozen=True)
class AudioChunk:
    t: float  # capture time of the chunk's first sample
    samples: np.ndarray  # 1-D float32 mono in [-1, 1]
    sample_rate: int


@dataclass(frozen=True)
class PulseSample:
    t: float
    bpm: float
    simulated: bool

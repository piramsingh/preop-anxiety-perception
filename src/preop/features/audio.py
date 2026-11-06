"""Vocal features over a rolling window."""

import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

SILENCE_DBFS = -55.0
# A pitch reading on room noise is not a voice. Measured with nobody speaking on the MacBook mic:
# hum at -46 to -49 dBFS, read as pitch up to 23 semitones. Level cannot separate this from speech,
# since quiet recorded speech sits at the same level. Speech rises and falls within a window and hum
# does not, so a voice needs this much modulation (dB between loud and quiet frames) unless loud.
MIN_VOICE_MODULATION_DB = 10.0
LOUD_ENOUGH_DBFS = -30.0  # A sustained cry can be steady, and hum at this level is unlikely.
FRAME_S = 0.05
MIN_VOICE_SEMITONES = 17.4  # About 75 Hz, below ordinary adult and child speaking pitch.
F0_COLUMN = "F0semitoneFrom27.5Hz_sma3nz_amean"
LOUDNESS_COLUMN = "loudness_sma3_amean"
HNR_COLUMN = "HNRdBACF_sma3nz_amean"


def rms_dbfs(samples: np.ndarray) -> float:
    if samples.size == 0:
        return -120.0
    rms = math.sqrt(float(np.mean(np.square(samples, dtype=np.float64))))
    return 20.0 * math.log10(max(rms, 1e-6))


def modulation_db(samples: np.ndarray, sample_rate: int) -> float:
    """How far the level moves within the window: 90th minus 10th percentile of frame level."""
    size = max(int(FRAME_S * sample_rate), 1)
    count = samples.size // size
    if count < 2:
        return 0.0
    levels = [rms_dbfs(frame) for frame in np.split(samples[: count * size], count)]
    return float(np.percentile(levels, 90) - np.percentile(levels, 10))


@dataclass(frozen=True)
class VocalFeatures:
    t: float
    dbfs: float
    voiced: bool  # Above the silence floor. Not a speech detector.
    pitch_semitones: float | None  # None when silent or pitch is undetected.
    smile_loudness: float | None
    hnr_db: float | None


def make_smile_analyzer() -> Callable[[np.ndarray, int], dict[str, float]]:
    import opensmile

    smile = opensmile.Smile(
        feature_set=opensmile.FeatureSet.eGeMAPSv02,
        feature_level=opensmile.FeatureLevel.Functionals,
    )

    def analyze(samples: np.ndarray, sample_rate: int) -> dict[str, float]:
        row = smile.process_signal(samples, sample_rate).iloc[0]
        return {name: float(row[name]) for name in (F0_COLUMN, LOUDNESS_COLUMN, HNR_COLUMN)}

    return analyze


class VocalWindow:
    """Buffers chunks and emits features once per hop over the last `window_s` seconds."""

    def __init__(
        self,
        analyzer: Callable[[np.ndarray, int], dict[str, float]],
        sample_rate: int = 16000,
        window_s: float = 2.0,
        hop_s: float = 0.5,
    ) -> None:
        self._analyzer = analyzer
        self._rate = sample_rate
        self._window = int(window_s * sample_rate)
        self._hop = int(hop_s * sample_rate)
        self._chunks: deque[np.ndarray] = deque()
        self._buffered = 0
        self._since_emit = 0

    def push(self, t_end: float, samples: np.ndarray) -> VocalFeatures | None:
        self._chunks.append(samples)
        self._buffered += samples.size
        self._since_emit += samples.size
        while self._buffered - self._chunks[0].size >= self._window:
            self._buffered -= self._chunks.popleft().size
        if self._buffered < self._window or self._since_emit < self._hop:
            return None
        self._since_emit = 0
        window = np.concatenate(self._chunks)[-self._window :]
        return self._features(t_end, window)

    def _is_voice_like(self, window: np.ndarray, dbfs: float) -> bool:
        return (
            dbfs >= LOUD_ENOUGH_DBFS or modulation_db(window, self._rate) >= MIN_VOICE_MODULATION_DB
        )

    def _features(self, t: float, window: np.ndarray) -> VocalFeatures:
        dbfs = rms_dbfs(window)
        if dbfs < SILENCE_DBFS:
            return VocalFeatures(t, dbfs, False, None, None, None)
        values = self._analyzer(window, self._rate)
        pitch = values[F0_COLUMN]
        return VocalFeatures(
            t,
            dbfs,
            True,
            # openSMILE reports 0 when it finds no voiced frames.
            pitch if pitch >= MIN_VOICE_SEMITONES and self._is_voice_like(window, dbfs) else None,
            values[LOUDNESS_COLUMN],
            values[HNR_COLUMN],
        )

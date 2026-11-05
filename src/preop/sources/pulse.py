import math
import random
import threading
import time
from collections.abc import Iterator

from preop.types import PulseSample


class SimulatedPulseSource:
    """Stand-in for a pulse oximeter. Samples are flagged simulated and never affect the score."""

    def __init__(self, base_bpm: float = 95.0, period_s: float = 1.0, seed: int = 0) -> None:
        self._base, self._period = base_bpm, period_s
        self._random = random.Random(seed)
        self._stop = threading.Event()

    def stream(self) -> Iterator[PulseSample]:
        start = time.monotonic()
        while not self._stop.wait(self._period):
            now = time.monotonic()
            drift = 6.0 * math.sin((now - start) / 20.0)
            yield PulseSample(now, self._base + drift + self._random.gauss(0, 1.0), simulated=True)

    def stop(self) -> None:
        self._stop.set()

"""Each person's own reference levels, measured during the calibration period."""

import statistics
from collections import defaultdict

MIN_SAMPLES = 10
MAD_TO_SD = 1.4826  # Makes the median absolute deviation comparable to a standard deviation.

# The smallest spread allowed for each signal. A calm person can be almost perfectly still, and
# dividing by that tiny spread would turn any small movement into a huge z-score.
# Action units: relaxed SDs of 0.2-0.5 were measured in the face check.
FLOORS = {"activity": 0.1, "loudness": 4.0, "pitch": 2.0, "heart_rate": 5.0, "parent_distance": 0.2}
AU_FLOOR = 0.3

# Used, at lower confidence, when calibration saw too little of a signal. Pitch, heart rate and
# parent distance vary too much between people to assume a level, so they have no default.
DEFAULTS = {"activity": (0.05, 0.1), "loudness": (-30.0, 4.0)}
AU_DEFAULT = (0.5, 0.4)


def _floor(name: str) -> float:
    return AU_FLOOR if name.startswith("AU") else FLOORS[name]


class Baseline:
    def __init__(self) -> None:
        self._samples: dict[str, list[float]] = defaultdict(list)

    def add(self, name: str, value: float) -> None:
        self._samples[name].append(value)

    def knows(self, name: str) -> bool:
        return len(self._samples[name]) >= MIN_SAMPLES

    def median(self, name: str) -> float | None:
        return statistics.median(self._samples[name]) if self.knows(name) else None

    def z(self, name: str, value: float) -> float | None:
        """Median and MAD rather than mean and SD, so a brief upset during calibration has less
        effect on the reference. None when there is neither a baseline nor a default."""
        if self.knows(name):
            samples = self._samples[name]
            center = statistics.median(samples)
            mad = statistics.median(abs(sample - center) for sample in samples)
            spread = max(MAD_TO_SD * mad, _floor(name))
        elif name.startswith("AU"):
            center, spread = AU_DEFAULT
        elif name in DEFAULTS:
            center, spread = DEFAULTS[name]
        else:
            return None
        return (value - center) / spread

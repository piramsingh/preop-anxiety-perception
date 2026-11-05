"""M1 placeholder score. It exists to prove the pipeline runs end to end.

It is NOT a mYPAS estimate: it has no baseline and no item mapping, and its thresholds are guesses.
Simulated pulse is deliberately excluded, so fake data can never move the score.
"""

from dataclasses import dataclass

ACTIVITY_WEIGHT = 0.6
LOUDNESS_WEIGHT = 0.4
ACTIVITY_FULL_SCALE = 2.0  # Body lengths per second treated as 100%.
QUIET_DBFS, LOUD_DBFS = -55.0, -15.0


@dataclass(frozen=True)
class PlaceholderScore:
    value: float | None  # 0-100, None when no signal is available
    confidence: float  # 0-1, the share of signal weight that was available


def _clamp01(value: float) -> float:
    return min(max(value, 0.0), 1.0)


def placeholder_score(
    activity: float | None, dbfs: float | None, body_confidence: float = 1.0
) -> PlaceholderScore:
    parts: list[tuple[float, float]] = []
    available = 0.0
    if activity is not None:
        parts.append((ACTIVITY_WEIGHT, _clamp01(activity / ACTIVITY_FULL_SCALE)))
        available += ACTIVITY_WEIGHT * _clamp01(body_confidence)
    if dbfs is not None:
        parts.append((LOUDNESS_WEIGHT, _clamp01((dbfs - QUIET_DBFS) / (LOUD_DBFS - QUIET_DBFS))))
        available += LOUDNESS_WEIGHT
    if not parts:
        return PlaceholderScore(None, 0.0)
    total = sum(weight for weight, _ in parts)
    value = 100.0 * sum(weight * level for weight, level in parts) / total
    return PlaceholderScore(value, round(available, 3))

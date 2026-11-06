"""One function per mYPAS item. Each rates its item on the item's own scale, as a continuous value.

Signals arrive as z-scores against the person's own baseline, so a relaxed face or a resting level
of movement scores as calm. A function returns None when its item cannot be observed.

Every threshold here is a starting guess that has not been fitted to human ratings. They should be
tuned on the role-play clips. Some of what raters judge is out of reach for these signals, so these
behaviors under-score:
- Withdrawal, gaze and thumb-sucking. A still, silent, frightened child can look calm.
- Whether an adult spoke to the child, so "does not respond" is only approximated by silence.
- Whose voice it is. The mic also hears the parent and staff.
"""

from dataclasses import dataclass

import numpy as np

# Action units in use. AU01/AU02 are left out because plain raised brows are not worry, and AU20
# because a big smile drives it as hard as fear does (both measured in the face check).
FACE_UNITS = ("AU04", "AU05", "AU06", "AU07", "AU09", "AU10", "AU12", "AU15")

LOW_CONFIDENCE_DEFAULTS = 0.6  # Applied when a signal has no personal baseline to compare with.
PARENT_CONFIDENCE = 0.5  # Identity can swap when people cross (#6).
VOICE_CONFIDENCE = 0.8  # The mic cannot tell the child from anyone else in the room.
SILENCE_CONFIDENCE = 0.5  # Silence fits both "quiet and fine" and "quiet and not responding".


@dataclass(frozen=True)
class ItemScore:
    rating: float  # On the item's own scale, from 1 to its maximum.
    confidence: float  # 0-1


@dataclass(frozen=True)
class Signals:
    """One moment of baseline-relative signals. None means not observed."""

    activity: float | None = None  # z
    body_confidence: float = 0.0
    loudness: float | None = None  # z. None when below the silence floor or no audio.
    pitch: float | None = None  # z. None when no voice is detected.
    audio: bool = False  # An audio signal exists, even if it is silent.
    voice_baseline_known: bool = True
    loud_share: float = 0.0  # Share of the last 10 s that was loud, 0-1.
    fell_silent: float = 0.0  # 0-1: was talkative during baseline, silent for the last 30 s.
    face: dict[str, float] | None = None  # z for each unit in FACE_UNITS.
    face_confidence: float = 0.0
    heart_rate: float | None = None  # z, from a real device only. Never a simulated source.
    parent_distance: float | None = None  # Body lengths.
    parent_ratio: float | None = None  # Distance relative to the baseline distance.
    activity_baseline_known: bool = True


def _ramp(value: float, low: float, high: float) -> float:
    """0 at or below `low`, 1 at or above `high`."""
    return float(np.clip((value - low) / (high - low), 0.0, 1.0))


def smile(s: Signals) -> float:
    if s.face is None:
        return 0.0
    drive = (s.face.get("AU06", 0.0) + s.face.get("AU12", 0.0)) / 2
    return _ramp(drive, 2.0, 5.0) * (1.0 - _worry(s))


def _worry(s: Signals) -> float:
    if s.face is None:
        return 0.0
    return max(_ramp(s.face.get("AU04", 0.0), 2.0, 5.0), _ramp(s.face.get("AU15", 0.0), 2.0, 5.0))


def _whimper(s: Signals) -> float:
    """Raised pitch without raised volume."""
    if s.pitch is None or s.loudness is None or s.loudness > 1.0:
        return 0.0
    return _ramp(s.pitch, 2.0, 5.0)


def _cry(s: Signals) -> float:
    """Loud, and more so when the pitch is raised. A smile means laughing, which rates as calm."""
    if s.loudness is None:
        return 0.0
    # Screams often defeat pitch tracking, so unknown pitch sits between flat and raised.
    pitched = 0.75 if s.pitch is None else 0.5 + 0.5 * _ramp(s.pitch, 0.0, 2.0)
    return _ramp(s.loudness, 1.0, 3.0) * pitched * (1.0 - smile(s))


def vocal_distress(s: Signals) -> float:
    return max(0.6 * _whimper(s), _cry(s))


def activity(s: Signals) -> ItemScore | None:
    """1 normal, 2 fidgeting, 3 squirming or frenzied, 4 trying to get away."""
    if s.activity is None:
        return None
    rating = float(np.interp(s.activity, [1.5, 4.0, 10.0, 18.0], [1.0, 2.0, 3.0, 4.0]))
    known = 1.0 if s.activity_baseline_known else LOW_CONFIDENCE_DEFAULTS
    return ItemScore(rating, s.body_confidence * known)


def vocalization(s: Signals) -> ItemScore | None:
    """1 talking or laughing, 3 quiet, 4 whimpering, 5 crying, 6 sustained loud crying.

    Rating 2 (whispering, nodding only) has no separate signal.
    """
    if not s.audio:
        return None
    known = 1.0 if s.voice_baseline_known else LOW_CONFIDENCE_DEFAULTS
    if s.pitch is None and s.loudness is None:
        return ItemScore(1.0 + 2.0 * s.fell_silent, SILENCE_CONFIDENCE * known)
    cry = _cry(s)
    rating = max(1.0 + 3.0 * _whimper(s), 1.0 + 4.0 * cry)
    if cry >= 0.9:
        rating = 5.0 + _ramp(s.loud_share, 0.5, 0.9)
    elif s.pitch is None:
        rating = max(rating, 1.0 + 2.0 * s.fell_silent)
    return ItemScore(rating, VOICE_CONFIDENCE * known)


def emotional_expressivity(s: Signals) -> ItemScore | None:
    """1 happy, 2 neutral, 3 worried or sad, 4 distressed or crying.

    A relaxed face rates 2, so a calm, unsmiling person sits at 2 as they would with a human rater.
    Action units are read as observations and never as a discrete emotion label.
    """
    if s.face is None:
        return None
    worry = _worry(s)
    pained = _ramp(max(s.face.get("AU09", 0.0), s.face.get("AU10", 0.0)), 2.0, 5.0) * worry
    happy = smile(s)
    rating = 2.0 - happy + worry + max(pained, vocal_distress(s))
    return ItemScore(float(np.clip(rating, 1.0, 4.0)), s.face_confidence)


def state_of_arousal(s: Signals) -> ItemScore | None:
    """1 alert, 2 withdrawn, 3 vigilant and tense, 4 panicked.

    Heart rate adds at most half a point, because it correlates only weakly with mYPAS in children.
    """
    has_voice = s.audio
    has_body = s.activity is not None
    has_face = s.face is not None
    if not (has_voice or has_body or has_face):
        return None
    moving = _ramp(s.activity, 1.5, 10.0) if has_body else 0.0
    wide_eyes = _ramp(s.face.get("AU05", 0.0), 2.0, 5.0) if has_face else 0.0
    tension = max(wide_eyes, moving)
    panic = vocal_distress(s) * (0.5 + 0.5 * moving)
    rating = max(1.0 + 2.0 * tension, 1.0 + 3.0 * panic, 1.0 + s.fell_silent)
    if s.heart_rate is not None:
        rating += 0.5 * _ramp(s.heart_rate, 1.0, 3.0)
    confidence = (
        0.4 * (s.body_confidence if has_body else 0.0)
        + 0.3 * (VOICE_CONFIDENCE if has_voice else 0.0)
        + 0.3 * (s.face_confidence if has_face else 0.0)
    )
    return ItemScore(float(np.clip(rating, 1.0, 4.0)), confidence)


def use_of_parents(s: Signals) -> ItemScore | None:
    """1 does not need the parent, 2 seeks comfort, 4 clinging desperately or pushing away.

    Only distance is observed, so "looks to the parent quietly" (3) is reached only on the way to 4.
    Distress is what separates leaning in for comfort from clinging. Not rated when no second
    person is present.
    """
    if s.parent_distance is None:
        return None
    agitation = max(_ramp(s.activity, 4.0, 10.0) if s.activity is not None else 0.0,
                    vocal_distress(s))  # fmt: skip
    contact = _ramp(1.5 - s.parent_distance, 0.0, 1.0)
    if s.parent_ratio is None:
        closer, farther, known = contact, 0.0, LOW_CONFIDENCE_DEFAULTS
    else:
        closer = max(_ramp(1.0 - s.parent_ratio, 0.2, 0.6), contact * agitation)
        farther, known = _ramp(s.parent_ratio - 1.0, 0.5, 1.5), 1.0
    # Calmly moving away rates 1 ("does not need parent"). Only distress makes distance a concern.
    rating = max(1.0 + closer * (1.0 + 2.0 * agitation), 1.0 + 3.0 * farther * agitation)
    return ItemScore(rating, PARENT_CONFIDENCE * known)

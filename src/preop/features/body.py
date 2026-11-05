"""Turns pose keypoints into activity and parent proximity. No MediaPipe import, so it is testable
with synthetic keypoints.

Keypoint indices follow the 33-point BlazePose layout. Coordinates are normalized image coordinates.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP = 11, 12, 23, 24
MIN_VISIBILITY = 0.5
MIN_POINTS = 5
FALLBACK_BODY_SCALE = 0.25
# Measured seated at a laptop: hips are out of frame and guessed, giving scales as low as 0.06,
# which inflated speed. Scale also uses shoulder width and has this floor.
MIN_BODY_SCALE = 0.12
# Whole-body speed above this (body lengths per second) means tracking jumped, not real movement.
MAX_PLAUSIBLE_SPEED = 5.0
MAX_GAP_S = 1.0  # Longer gaps reset motion, so the jump is not read as movement.
# Motion is measured over this interval. Frame-to-frame at 30 fps mostly measures keypoint jitter.
MOTION_INTERVAL_S = 0.2
# Per-keypoint movement below this many body lengths per interval counts as jitter, not motion.
JITTER_DEADBAND = 0.03
# People whose keypoints differ by less than this many body lengths are one person detected twice.
# It compares all keypoints, so a child on a parent's lap (close hips, separate heads) stays two.
DUPLICATE_DISTANCE = 0.3
# MediaPipe sometimes reports brief false people that jump around the frame. Measured with one
# person in view: bursts of at most 0.33 s. A second person counts only after staying in about the
# same place (image widths per frame) for this long.
SECOND_PERSON_CONFIRM_S = 0.75
SECOND_PERSON_MAX_JUMP = 0.25
SECOND_PERSON_GRACE_S = 0.3  # Brief dropouts of a confirmed person are tolerated.


@dataclass(frozen=True)
class Person:
    """points has shape (33, 3): x, y, visibility."""

    points: np.ndarray

    def center(self) -> np.ndarray:
        """Hip midpoint, or the mean of visible points when the hips are out of frame."""
        hips = self.points[[LEFT_HIP, RIGHT_HIP]]
        if (hips[:, 2] >= MIN_VISIBILITY).all():
            return hips[:, :2].mean(axis=0)
        visible = self.points[self.points[:, 2] >= MIN_VISIBILITY]
        source = visible if len(visible) else self.points
        return source[:, :2].mean(axis=0)

    def body_scale(self, aspect: float = 1.0) -> float:
        """Larger of torso length and shoulder width, so distance from the camera cancels out."""
        points = self.points
        if (points[[LEFT_SHOULDER, RIGHT_SHOULDER], 2] < MIN_VISIBILITY).any():
            return FALLBACK_BODY_SCALE
        left, right = points[LEFT_SHOULDER, :2], points[RIGHT_SHOULDER, :2]
        scale = _distance(left, right, aspect)
        if (points[[LEFT_HIP, RIGHT_HIP], 2] >= MIN_VISIBILITY).all():
            hips = points[[LEFT_HIP, RIGHT_HIP], :2].mean(axis=0)
            scale = max(scale, _distance((left + right) / 2, hips, aspect))
        return max(scale, MIN_BODY_SCALE)


def _distance(a: np.ndarray, b: np.ndarray, aspect: float) -> float:
    return math.hypot((a[0] - b[0]) * aspect, a[1] - b[1])


def drop_duplicates(people: Sequence[Person], aspect: float = 1.0) -> list[Person]:
    kept: list[Person] = []
    for person in people:
        scale = person.body_scale(aspect)
        is_duplicate = False
        for other in kept:
            delta = person.points[:, :2] - other.points[:, :2]
            delta[:, 0] *= aspect
            if float(np.hypot(delta[:, 0], delta[:, 1]).mean()) / scale < DUPLICATE_DISTANCE:
                is_duplicate = True
                break
        if not is_duplicate:
            kept.append(person)
    return kept


def identify_child(
    people: Sequence[Person], previous_center: np.ndarray | None, aspect: float = 1.0
) -> int | None:
    """Follow the nearest person to the previous position. With no history, use the most central.

    This is a stopgap for M1. It is not re-identification and can swap people when they cross.
    """
    if not people:
        return None
    reference = previous_center if previous_center is not None else np.array([0.5, 0.5])
    return min(range(len(people)), key=lambda i: _distance(people[i].center(), reference, aspect))


@dataclass(frozen=True)
class BodyFeatures:
    t: float
    people: int
    activity: float | None  # Body lengths per second. None until two usable frames exist.
    parent_distance: float | None  # Child-to-other distance in body lengths. None if alone.
    confidence: float  # Mean visibility of the child's keypoints, 0-1.


class SecondPersonFilter:
    """Passes a second person only once they have persisted in about the same place."""

    def __init__(self) -> None:
        self._last: Person | None = None
        self._since = 0.0
        self._seen = 0.0

    def update(self, t: float, others: Sequence[Person], aspect: float = 1.0) -> Person | None:
        if self._last is not None and t - self._seen > SECOND_PERSON_GRACE_S:
            self._last = None
        if others:
            center = self._last.center() if self._last is not None else None
            current = others[identify_child(others, center, aspect)]
            if (
                center is None
                or _distance(current.center(), center, aspect) > SECOND_PERSON_MAX_JUMP
            ):
                self._since = t
            self._last, self._seen = current, t
        if self._last is None or t - self._since < SECOND_PERSON_CONFIRM_S:
            return None
        return self._last


class BodyTracker:
    def __init__(self, smoothing: float = 0.3) -> None:
        self.confirmed: list[Person] = []  # People who passed the filters, for display.
        self._second = SecondPersonFilter()
        self._smoothing = smoothing
        self._previous: Person | None = None  # Last frame, for following the child.
        self._reference: Person | None = None  # Last motion sample.
        self._reference_t: float | None = None
        self._activity: float | None = None

    def update(self, t: float, people: Sequence[Person], aspect: float = 1.0) -> BodyFeatures:
        people = drop_duplicates(people, aspect)
        center = self._previous.center() if self._previous is not None else None
        index = identify_child(people, center, aspect)
        if index is None:
            self.confirmed = []
            self._second = SecondPersonFilter()
            self._previous = self._reference = self._reference_t = self._activity = None
            return BodyFeatures(t, 0, None, None, 0.0)

        child = people[index]
        scale = child.body_scale(aspect)
        self._update_activity(t, child, scale, aspect)
        others = [person for i, person in enumerate(people) if i != index]
        second = self._second.update(t, others, aspect)
        distance = None
        if second is not None:
            distance = _distance(child.center(), second.center(), aspect) / scale
        self.confirmed = [child] if second is None else [child, second]

        self._previous = child
        confidence = float(child.points[:, 2].mean())
        return BodyFeatures(t, len(self.confirmed), self._activity, distance, confidence)

    def _update_activity(self, t: float, child: Person, scale: float, aspect: float) -> None:
        reference, reference_t = self._reference, self._reference_t
        if reference is None or reference_t is None or t - reference_t > MAX_GAP_S:
            self._reference, self._reference_t, self._activity = child, t, None
            return
        elapsed = t - reference_t
        if elapsed < MOTION_INTERVAL_S:
            return
        self._reference, self._reference_t = child, t
        both = (child.points[:, 2] >= MIN_VISIBILITY) & (reference.points[:, 2] >= MIN_VISIBILITY)
        if both.sum() < MIN_POINTS:
            return  # Too little is visible. Keep the last value and let staleness handle it.
        delta = child.points[both, :2] - reference.points[both, :2]
        delta[:, 0] *= aspect
        moved = np.hypot(delta[:, 0], delta[:, 1]) / scale
        if float(np.median(moved)) / elapsed > MAX_PLAUSIBLE_SPEED:
            return  # Tracking jumped, so keep the last value.
        # Averaging over all points keeps limb-only fidgeting visible, which a median would hide.
        speed = float(np.where(moved < JITTER_DEADBAND, 0.0, moved).mean()) / elapsed
        if self._activity is None:
            self._activity = speed
        else:
            self._activity += self._smoothing * (speed - self._activity)

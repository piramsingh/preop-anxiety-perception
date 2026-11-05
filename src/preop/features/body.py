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
MAX_GAP_S = 1.0  # Longer gaps reset motion, so the jump is not read as movement.
# Motion is measured over this interval. Frame-to-frame at 30 fps mostly measures keypoint jitter.
MOTION_INTERVAL_S = 0.2
# Per-keypoint movement below this many body lengths per interval counts as jitter, not motion.
JITTER_DEADBAND = 0.03
# People whose keypoints differ by less than this many body lengths are one person detected twice.
# It compares all keypoints, so a child on a parent's lap (close hips, separate heads) stays two.
DUPLICATE_DISTANCE = 0.3


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
        """Shoulder-to-hip distance, so that a person's distance from the camera cancels out."""
        indices = [LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP]
        if (self.points[indices, 2] < MIN_VISIBILITY).any():
            return FALLBACK_BODY_SCALE
        shoulders = self.points[[LEFT_SHOULDER, RIGHT_SHOULDER], :2].mean(axis=0)
        hips = self.points[[LEFT_HIP, RIGHT_HIP], :2].mean(axis=0)
        return max(_distance(shoulders, hips, aspect), 1e-3)


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


class BodyTracker:
    def __init__(self, smoothing: float = 0.3) -> None:
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
            self._previous = self._reference = self._reference_t = self._activity = None
            return BodyFeatures(t, 0, None, None, 0.0)

        child = people[index]
        scale = child.body_scale(aspect)
        self._update_activity(t, child, scale, aspect)
        others = [person for i, person in enumerate(people) if i != index]
        distance = None
        if others:
            nearest = min(_distance(child.center(), o.center(), aspect) for o in others)
            distance = nearest / scale

        self._previous = child
        confidence = float(child.points[:, 2].mean())
        return BodyFeatures(t, len(people), self._activity, distance, confidence)

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
        # Averaging over all points keeps limb-only fidgeting visible, which a median would hide.
        speed = float(np.where(moved < JITTER_DEADBAND, 0.0, moved).mean()) / elapsed
        if self._activity is None:
            self._activity = speed
        else:
            self._activity += self._smoothing * (speed - self._activity)

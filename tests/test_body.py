import numpy as np
import pytest

from preop.features.body import (
    JITTER_DEADBAND,
    LEFT_HIP,
    LEFT_SHOULDER,
    RIGHT_HIP,
    RIGHT_SHOULDER,
    BodyTracker,
    Person,
    drop_duplicates,
    identify_child,
)


def person(cx: float, cy: float = 0.5, visibility: float = 1.0, jitter: float = 0.0) -> Person:
    points = np.zeros((33, 3), dtype=np.float32)
    points[:, 0] = cx + jitter
    points[:, 1] = cy
    points[:, 2] = visibility
    points[[LEFT_SHOULDER, RIGHT_SHOULDER], 1] = cy - 0.2  # One body length is 0.2.
    points[[LEFT_HIP, RIGHT_HIP], 1] = cy
    return Person(points)


def test_activity_is_in_body_lengths_per_second():
    tracker = BodyTracker(smoothing=1.0)
    tracker.update(0.0, [person(0.5)])
    # 0.2 of the image in 1 s, with a 0.2 body length, is 1 body length per second.
    assert tracker.update(1.0, [person(0.7)]).activity == pytest.approx(1.0, rel=1e-3)


def test_still_person_has_zero_activity():
    tracker = BodyTracker()
    tracker.update(0.0, [person(0.5)])
    assert tracker.update(0.25, [person(0.5)]).activity == pytest.approx(0.0)


def test_long_gap_is_not_read_as_movement():
    tracker = BodyTracker()
    tracker.update(0.0, [person(0.2)])
    assert tracker.update(5.0, [person(0.8)]).activity is None


def test_nobody_in_frame_clears_features():
    tracker = BodyTracker()
    tracker.update(0.0, [person(0.5)])
    features = tracker.update(0.1, [])
    assert (features.people, features.activity, features.confidence) == (0, None, 0.0)


def test_low_visibility_points_do_not_count_as_motion():
    tracker = BodyTracker(smoothing=1.0)
    tracker.update(0.0, [person(0.5)])
    assert tracker.update(0.25, [person(0.9, visibility=0.1)]).activity is None


def feed_two_people(tracker: BodyTracker, seconds: float):
    features = None
    for frame in range(int(seconds * 30) + 1):
        features = tracker.update(frame / 30, [person(0.5), person(0.8)])
    return features


def test_parent_distance_needs_a_confirmed_second_person():
    tracker = BodyTracker()
    assert tracker.update(0.0, [person(0.5)]).parent_distance is None
    features = feed_two_people(BodyTracker(), 1.0)
    assert features.people == 2
    # The people are 0.3 apart and a body length is 0.2, so 1.5 body lengths.
    assert features.parent_distance == pytest.approx(1.5, rel=1e-3)


def test_brief_false_person_is_ignored():
    tracker = BodyTracker()
    tracker.update(0.0, [person(0.5)])
    for frame in range(1, 10):  # 0.3 s burst
        features = tracker.update(frame / 30, [person(0.5), person(0.9)])
        assert features.people == 1
        assert features.parent_distance is None


def test_false_person_that_keeps_jumping_is_ignored():
    tracker = BodyTracker()
    for frame in range(60):
        ghost = person(0.1 if frame % 2 else 0.9)
        features = tracker.update(frame / 30, [person(0.5), ghost])
    assert features.people == 1


def test_confirmed_person_survives_a_brief_dropout():
    tracker = BodyTracker()
    feed_two_people(tracker, 1.0)
    assert tracker.update(1.1, [person(0.5)]).people == 2
    assert tracker.update(2.0, [person(0.5)]).people == 1


def test_child_is_followed_by_position_regardless_of_detection_order():
    people = [person(0.9), person(0.3)]
    assert identify_child(people, np.array([0.28, 0.5])) == 1
    assert identify_child(list(reversed(people)), np.array([0.28, 0.5])) == 0


def test_first_identification_picks_most_central():
    assert identify_child([person(0.1), person(0.55)], None) == 1


def test_jitter_below_the_deadband_reads_as_still():
    tracker = BodyTracker(smoothing=1.0)
    t = 0.0
    tracker.update(t, [person(0.5)])
    wobble = JITTER_DEADBAND * 0.2 * 0.5  # Half the deadband, in image units.
    for frame in range(1, 31):
        t = frame / 30
        features = tracker.update(t, [person(0.5, jitter=wobble if frame % 2 else -wobble)])
    assert features.activity == pytest.approx(0.0)


def test_limb_only_motion_still_registers():
    tracker = BodyTracker(smoothing=1.0)
    still = person(0.5)
    tracker.update(0.0, [still])
    moving = person(0.5)
    moving.points[15:17, 0] += 0.2  # Only the wrists move.
    assert tracker.update(0.25, [moving]).activity > 0.0


def test_duplicate_detection_of_one_person_is_dropped():
    assert len(drop_duplicates([person(0.5), person(0.5, jitter=0.01)])) == 1


def test_child_on_lap_is_not_treated_as_a_duplicate():
    parent = person(0.5, cy=0.7)
    child = person(0.5, cy=0.7)
    child.points[:11, 1] = 0.2  # Same hips, but the heads are far apart.
    assert len(drop_duplicates([parent, child])) == 2


def test_guessed_hips_cannot_shrink_the_scale_and_inflate_speed():
    squashed = person(0.5)
    squashed.points[[LEFT_SHOULDER, RIGHT_SHOULDER], 1] = 0.49  # Torso looks almost zero long.
    assert squashed.body_scale() >= 0.12


def test_whole_body_teleport_is_not_read_as_movement():
    tracker = BodyTracker(smoothing=1.0)
    tracker.update(0.0, [person(0.2)])
    assert tracker.update(0.25, [person(0.2)]).activity == pytest.approx(0.0)
    assert tracker.update(0.5, [person(0.9)]).activity == pytest.approx(0.0)

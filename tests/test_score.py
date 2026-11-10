"""Scoring tests on generated signals. No real audio or video is used."""

import pytest

from preop.features.audio import VocalFeatures
from preop.features.body import BodyFeatures
from preop.features.face import FaceFeatures
from preop.score.scorer import (
    ITEM_MAX,
    MYPAS_MAX,
    MYPAS_MIN,
    DistressScore,
    MypasScorer,
    fuse,
    mypas_total,
)
from preop.types import PulseSample

BASELINE_S = 20.0
RELAXED = {"AU04": 0.3, "AU05": 0.9, "AU06": 0.4, "AU07": 0.6, "AU09": 0.4, "AU10": 0.5,
           "AU12": 0.3, "AU15": 0.5}  # fmt: skip


def body(t, activity=0.02, parent=None):
    return BodyFeatures(t, 1 if parent is None else 2, activity, parent, 0.95)


def voice(t, dbfs=-32.0, pitch=30.0):
    return VocalFeatures(t, dbfs, True, pitch, 1.0, 5.0)


def silence(t):
    return VocalFeatures(t, -70.0, False, None, None, None)


def face(t, **units):
    return FaceFeatures(t, True, 0.95, {**RELAXED, **units}, {})


def calibrated(parent=None) -> MypasScorer:
    """Calm and talking during calibration, with small natural variation."""
    scorer = MypasScorer(baseline_s=BASELINE_S)
    for i in range(int(BASELINE_S)):
        wobble = (i % 3) - 1
        scorer.update(
            float(i),
            body(i, 0.02 + 0.01 * wobble, parent),
            voice(i, -32.0 + wobble, 30.0 + 0.5 * wobble),
            face(i),
        )
    return scorer


def hold(scorer: MypasScorer, seconds: int = 8, start: float = 100.0, **signals) -> DistressScore:
    result = None
    for i in range(seconds):
        t = start + i
        result = scorer.update(
            t,
            signals["body"](t) if "body" in signals else None,
            signals["vocal"](t) if "vocal" in signals else None,
            signals["face"](t) if "face" in signals else None,
            signals["pulse"](t) if "pulse" in signals else None,
        )
    return result


CALM = {"body": body, "vocal": voice, "face": face}
RESTLESS = {
    "body": lambda t: body(t, 0.45),
    "vocal": voice,
    "face": lambda t: face(t, AU04=1.2),
}
DISTRESSED = {
    "body": lambda t: body(t, 1.8),
    "vocal": lambda t: voice(t, -14.0, 38.0),
    "face": lambda t: face(t, AU04=3.0, AU05=2.8, AU09=2.5, AU15=2.0),
}


def test_published_formula():
    assert mypas_total(dict.fromkeys(ITEM_MAX, 1)) == pytest.approx(23.33, abs=0.01)
    assert mypas_total(ITEM_MAX) == pytest.approx(100.0)
    ratings = {"activity": 2, "vocalization": 3, "emotional_expressivity": 2,
               "state_of_arousal": 1, "use_of_parents": 1}  # fmt: skip
    expected = (2 / 4 + 3 / 6 + 2 / 4 + 1 / 4 + 1 / 4) / 5 * 100
    assert mypas_total(ratings) == pytest.approx(expected)


def test_fusion_matches_the_formula_when_all_items_are_present():
    ratings = {"activity": 2.5, "vocalization": 4.0, "emotional_expressivity": 3.0,
               "state_of_arousal": 2.0, "use_of_parents": 1.5}  # fmt: skip
    assert fuse(ratings) == pytest.approx(mypas_total(ratings))


def test_fusion_stays_on_the_range_with_any_items_missing():
    assert fuse({"activity": 1.0}) == pytest.approx(MYPAS_MIN)
    assert fuse({"vocalization": 6.0}) == pytest.approx(MYPAS_MAX)
    assert fuse({"activity": 4.0, "state_of_arousal": 4.0}) == pytest.approx(MYPAS_MAX)


def test_no_score_while_calibrating():
    scorer = MypasScorer(baseline_s=BASELINE_S)
    first = scorer.update(0.0, body(0.0))
    later = scorer.update(10.0, body(10.0))
    assert first.value is None and first.calibrating
    assert later.value is None and later.baseline_progress == pytest.approx(0.5)


def test_calibration_clock_waits_for_the_first_signal():
    scorer = MypasScorer(baseline_s=BASELINE_S)
    scorer.update(0.0)
    assert scorer.update(100.0, body(100.0)).baseline_progress == 0.0


def test_empty_room_does_not_use_up_calibration():
    scorer = MypasScorer(baseline_s=BASELINE_S)
    empty = BodyFeatures(0.0, 0, None, None, 0.0)
    for i in range(100):
        assert scorer.update(float(i), empty, silence(i)).baseline_progress == 0.0
    assert scorer.update(100.0, body(100.0)).calibrating


def test_score_tracks_calm_restless_distressed():
    scorer = calibrated()
    calm = hold(scorer, **CALM)
    restless = hold(scorer, start=110.0, **RESTLESS)
    distressed = hold(scorer, start=120.0, **DISTRESSED)
    assert calm.value < 30.0  # Neutral face at 2, everything else at 1, gives about 28.
    assert calm.value < restless.value < distressed.value
    assert distressed.value > 70.0
    assert distressed.items["vocalization"].rating > 5.0


def test_score_falls_again_after_distress():
    scorer = calibrated()
    high = hold(scorer, **DISTRESSED)
    recovered = hold(scorer, seconds=30, start=120.0, **CALM)
    assert recovered.value < high.value - 30.0


def test_rises_within_two_ticks():
    scorer = calibrated()
    calm = hold(scorer, **CALM)
    risen = hold(scorer, seconds=2, start=120.0, **DISTRESSED)
    assert risen.value - calm.value > 0.8 * (
        hold(scorer, start=130.0, **DISTRESSED).value - calm.value
    )


def test_still_baseline_does_not_explode_on_a_tiny_movement():
    scorer = MypasScorer(baseline_s=BASELINE_S)
    for i in range(int(BASELINE_S)):
        scorer.update(float(i), body(i, 0.0))
    assert hold(scorer, body=lambda t: body(t, 0.1)).items["activity"].rating == pytest.approx(1.0)


def test_ordinary_talking_is_calm_when_baseline_included_talking():
    result = hold(calibrated(), **CALM)
    assert result.items["vocalization"].rating == pytest.approx(1.0)


def test_laughing_is_not_read_as_crying():
    smiling = lambda t: face(t, AU06=3.2, AU12=2.0)  # noqa: E731
    result = hold(calibrated(), vocal=lambda t: voice(t, -18.0, 34.0), face=smiling)
    assert result.items["emotional_expressivity"].rating == pytest.approx(1.0)
    assert result.items["vocalization"].rating == pytest.approx(1.0)


def test_big_smile_and_hard_frown_move_expressivity_opposite_ways():
    smile = hold(calibrated(), face=lambda t: face(t, AU06=3.2, AU12=2.0))
    frown = hold(calibrated(), face=lambda t: face(t, AU04=2.2))
    assert smile.items["emotional_expressivity"].rating < 1.5
    assert frown.items["emotional_expressivity"].rating > 2.8


def test_missing_signals_keep_scoring_at_lower_confidence():
    full = hold(calibrated(), **DISTRESSED)
    no_face = hold(calibrated(), body=DISTRESSED["body"], vocal=DISTRESSED["vocal"])
    only_voice = hold(calibrated(), vocal=DISTRESSED["vocal"])
    assert full.confidence > no_face.confidence > only_voice.confidence > 0.0
    assert "emotional_expressivity" not in no_face.items
    assert no_face.value > 60.0  # Losing the face does not hide distress elsewhere.
    assert only_voice.value > 60.0


def test_no_signals_means_no_score():
    result = hold(calibrated(), seconds=5)
    assert (result.value, result.confidence) == (None, 0.0)


def test_lost_face_is_held_briefly_then_dropped():
    scorer = calibrated()
    hold(scorer, **CALM)
    undetected = FaceFeatures(108.0, False, 0.0, {}, {})
    held = scorer.update(108.0, body(108.0), voice(108.0), undetected)
    gone = scorer.update(112.0, body(112.0), voice(112.0), undetected)
    assert "emotional_expressivity" in held.items
    assert "emotional_expressivity" not in gone.items


def test_simulated_pulse_never_moves_the_score():
    def racing(t):
        return PulseSample(t, 190.0, simulated=True)

    without = hold(calibrated(), **CALM)
    with_simulated = hold(calibrated(), **CALM, pulse=racing)
    assert with_simulated == without


def test_real_heart_rate_only_nudges_arousal():
    scorer = MypasScorer(baseline_s=BASELINE_S)
    for i in range(int(BASELINE_S)):
        scorer.update(float(i), body(i), voice(i), face(i), PulseSample(i, 90.0, simulated=False))
    result = hold(scorer, **CALM, pulse=lambda t: PulseSample(t, 180.0, simulated=False))
    assert 1.0 < result.items["state_of_arousal"].rating <= 1.5


def test_parent_item_needs_a_second_person():
    assert "use_of_parents" not in hold(calibrated(), **CALM).items


def test_clinging_needs_distress_and_leaning_in_does_not():
    leaning = hold(calibrated(parent=2.0), body=lambda t: body(t, 0.02, 1.0))
    clinging = hold(calibrated(parent=2.0), **{**DISTRESSED, "body": lambda t: body(t, 1.8, 0.3)})
    assert 1.5 < leaning.items["use_of_parents"].rating <= 2.0
    assert clinging.items["use_of_parents"].rating > 3.5


def test_calmly_moving_away_from_the_parent_stays_calm():
    result = hold(calibrated(parent=1.0), body=lambda t: body(t, 0.02, 3.0))
    assert result.items["use_of_parents"].rating == pytest.approx(1.0)


def test_pushing_away_from_the_parent_while_distressed_rates_high():
    result = hold(calibrated(parent=1.0), **{**DISTRESSED, "body": lambda t: body(t, 1.8, 3.0)})
    assert result.items["use_of_parents"].rating > 3.5


def test_going_silent_after_a_talkative_baseline_raises_the_score():
    scorer = calibrated()
    start = hold(scorer, seconds=2, **{**CALM, "vocal": silence})
    later = hold(scorer, seconds=40, start=110.0, **{**CALM, "vocal": silence})
    assert start.items["vocalization"].rating == pytest.approx(1.0)
    assert later.items["vocalization"].rating == pytest.approx(3.0, abs=0.01)
    assert later.value > start.value


def test_silence_after_a_quiet_baseline_stays_calm():
    scorer = MypasScorer(baseline_s=BASELINE_S)
    for i in range(int(BASELINE_S)):
        scorer.update(float(i), body(i), silence(i))
    result = hold(scorer, seconds=40, vocal=silence)
    assert result.items["vocalization"].rating == pytest.approx(1.0)


def test_upset_during_calibration_is_flagged_and_the_score_still_shows():
    scorer = MypasScorer(baseline_s=BASELINE_S)
    for i in range(int(BASELINE_S)):
        scorer.update(float(i), body(i, 1.2), voice(i, -14.0), face(i, AU04=2.5))
    result = hold(scorer, body=lambda t: body(t, 1.2))
    assert set(result.upset_during_baseline) == {"movement", "voice", "face"}
    assert result.value is not None


def test_calm_baseline_is_not_flagged():
    assert hold(calibrated(), **CALM).upset_during_baseline == ()


def test_score_stays_on_the_range_at_extremes():
    result = hold(
        calibrated(),
        body=lambda t: body(t, 50.0, 0.1),
        vocal=lambda t: voice(t, 0.0, 80.0),
        face=lambda t: face(t, AU04=5, AU05=5, AU09=5, AU10=5, AU15=5),
        seconds=20,
    )
    assert MYPAS_MIN <= result.value <= MYPAS_MAX
    for name, item in result.items.items():
        assert 1.0 <= item.rating <= ITEM_MAX[name]

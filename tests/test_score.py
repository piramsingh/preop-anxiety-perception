import pytest

from preop.score.placeholder import placeholder_score


def test_no_signals_means_no_score():
    result = placeholder_score(None, None)
    assert (result.value, result.confidence) == (None, 0.0)


def test_missing_signal_keeps_scoring_at_lower_confidence():
    both = placeholder_score(1.0, -35.0)
    audio_only = placeholder_score(None, -35.0)
    video_only = placeholder_score(1.0, None)
    assert both.confidence == pytest.approx(1.0)
    assert audio_only.value == pytest.approx(50.0)
    assert audio_only.confidence == pytest.approx(0.4)
    assert video_only.value == pytest.approx(50.0)
    assert video_only.confidence == pytest.approx(0.6)


def test_score_stays_in_range():
    assert placeholder_score(100.0, 0.0).value == pytest.approx(100.0)
    assert placeholder_score(0.0, -120.0).value == pytest.approx(0.0)


def test_poor_visibility_lowers_confidence():
    assert placeholder_score(1.0, None, body_confidence=0.5).confidence == pytest.approx(0.3)

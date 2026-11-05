import pytest

from preop.face_check import phase_at, summarize

PHASES = [("a", "A", 2.0), ("b", "B", 3.0)]


def test_phase_at_walks_through_and_finishes():
    assert phase_at(0.5, PHASES) == (0, pytest.approx(1.5))
    assert phase_at(2.5, PHASES) == (1, pytest.approx(2.5))
    assert phase_at(5.0, PHASES) is None


def row(phase, since, au04, detected=True):
    return {"phase": phase, "since": since, "detected": detected, "AU04": au04}


def test_summary_compares_with_relaxed_and_skips_reaction_time():
    rows = [
        row("neutral", 2.0, 0.5),
        row("frown", 0.1, 9.0),  # Still reacting, so ignored.
        row("frown", 2.0, 2.5),
        row("frown", 3.0, 0.0, detected=False),  # No face, so ignored.
    ]
    text = summarize(rows)
    line = next(item for item in text.splitlines() if item.startswith("frown"))
    assert "+2.00" in line
    assert "75% of 4 frames" in text


def test_summary_reports_missing_data():
    assert "no data" in summarize([row("neutral", 2.0, 0.5)])

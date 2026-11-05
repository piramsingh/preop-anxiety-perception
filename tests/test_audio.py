import numpy as np
import pytest

from preop.features.audio import (
    F0_COLUMN,
    HNR_COLUMN,
    LOUDNESS_COLUMN,
    VocalWindow,
    make_smile_analyzer,
    rms_dbfs,
)
from preop.sources.mic import pick_input_device

RATE = 16000


def tone(seconds: float, hz: float = 220.0, amplitude: float = 0.1) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    return (amplitude * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def fake_analyzer(samples, rate):
    return {F0_COLUMN: 30.0, LOUDNESS_COLUMN: 1.0, HNR_COLUMN: 5.0}


def test_rms_dbfs_of_full_scale_sine():
    assert rms_dbfs(tone(1.0, amplitude=1.0)) == pytest.approx(-3.01, abs=0.05)


def test_window_waits_until_full_then_emits_per_hop():
    window = VocalWindow(fake_analyzer, RATE, window_s=1.0, hop_s=0.5)
    chunk = tone(0.25)
    results = [window.push(i * 0.25, chunk) for i in range(1, 9)]
    emitted = [i for i, result in enumerate(results) if result is not None]
    assert emitted == [3, 5, 7]


def test_silence_skips_analysis_and_reports_no_pitch():
    def fail(samples, rate):
        raise AssertionError("analyzer should not run on silence")

    window = VocalWindow(fail, RATE, window_s=0.5, hop_s=0.5)
    features = window.push(0.5, np.zeros(RATE // 2, dtype=np.float32))
    assert features is not None
    assert (features.voiced, features.pitch_semitones) == (False, None)


def test_opensmile_finds_higher_pitch_for_higher_tone():
    analyze = make_smile_analyzer()
    low = analyze(tone(2.0, 220.0), RATE)[F0_COLUMN]
    high = analyze(tone(2.0, 440.0), RATE)[F0_COLUMN]
    assert high - low == pytest.approx(12.0, abs=1.0)  # An octave is 12 semitones.


def test_mic_selection_prefers_hint_and_skips_output_only_devices():
    devices = [
        {"name": "AirPods", "max_input_channels": 1},
        {"name": "MacBook Pro Speakers", "max_input_channels": 0},
        {"name": "MacBook Pro Microphone", "max_input_channels": 1},
    ]
    assert pick_input_device(devices, "MacBook") == 2
    assert pick_input_device(devices, "Missing") is None
    assert pick_input_device(devices, None) is None

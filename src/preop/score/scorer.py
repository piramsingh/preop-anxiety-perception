"""Baseline calibration and fusion of the five items into one score on the mYPAS range."""

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from preop.features.audio import VocalFeatures
from preop.features.body import BodyFeatures
from preop.features.face import FaceFeatures
from preop.mypas import items
from preop.mypas.items import FACE_UNITS, ItemScore, Signals
from preop.score.baseline import Baseline
from preop.types import PulseSample

ITEM_MAX = {
    "activity": 4,
    "vocalization": 6,
    "emotional_expressivity": 4,
    "state_of_arousal": 4,
    "use_of_parents": 4,
}
ITEM_FUNCTIONS: dict[str, Callable[[Signals], ItemScore | None]] = {
    "activity": items.activity,
    "vocalization": items.vocalization,
    "emotional_expressivity": items.emotional_expressivity,
    "state_of_arousal": items.state_of_arousal,
    "use_of_parents": items.use_of_parents,
}
MYPAS_MIN = 100.0 * sum(1 / maximum for maximum in ITEM_MAX.values()) / len(ITEM_MAX)  # 23.33
MYPAS_MAX = 100.0
# How many points of the total each item can move, from its lowest rating to its highest.
ITEM_RANGE = {
    name: 100.0 * (maximum - 1) / maximum / len(ITEM_MAX) for name, maximum in ITEM_MAX.items()
}

# Rises quickly, to stay inside the latency target, and falls slowly, so it does not flicker.
RISE, FALL = 0.7, 0.2  # Share of the gap closed per tick.
HOLD_S = 3.0  # An item that drops out keeps its last rating for this long, at half confidence.
MIN_FACE_CONFIDENCE = 0.5
SHARED_FRAME_FACE_CONFIDENCE = 0.7  # OpenFace may be tracking the other person's face (#6).
LOUD_Z = 3.0
LOUD_WINDOW_S = 10.0
SILENCE_WINDOW_S = 30.0
TALKATIVE_SHARE = 0.3  # Share of calibration with a voice, needed before silence means anything.

# Absolute levels that suggest the person was already upset during calibration.
UPSET_ACTIVITY = 0.5  # Body lengths per second.
UPSET_DBFS = -18.0
UPSET_AU = 1.5  # A hard frown measured AU04 at 2.2 against 0.3 relaxed.


def mypas_total(ratings: Mapping[str, float]) -> float:
    """The published formula, for all five items. Also applies to human ratings."""
    return 100.0 * sum(ratings[name] / ITEM_MAX[name] for name in ITEM_MAX) / len(ITEM_MAX)


def fuse(ratings: Mapping[str, float]) -> float:
    """Equals `mypas_total` when all five items are present. Otherwise each missing item's share of
    the range goes to the observed items in proportion, so the result stays on the mYPAS range."""
    available = sum(ITEM_RANGE[name] for name in ratings)
    severity = sum(
        ITEM_RANGE[name] * (rating - 1) / (ITEM_MAX[name] - 1) for name, rating in ratings.items()
    )
    return MYPAS_MIN + (MYPAS_MAX - MYPAS_MIN) * severity / available


@dataclass(frozen=True)
class DistressScore:
    value: float | None  # On the mYPAS range, 23.33-100. None while calibrating or with no signal.
    confidence: float  # 0-1
    items: dict[str, ItemScore] = field(default_factory=dict)
    baseline_progress: float = 1.0  # 0-1, reaches 1 when calibration ends.
    upset_during_baseline: tuple[str, ...] = ()  # Which signals looked upset during calibration.

    @property
    def calibrating(self) -> bool:
        return self.baseline_progress < 1.0


class MypasScorer:
    def __init__(self, baseline_s: float = 60.0) -> None:
        self._baseline_s = baseline_s
        self._baseline = Baseline()
        self._started: float | None = None
        self._calibrated = False
        self._upset: tuple[str, ...] = ()
        self._audio_ticks = 0
        self._voiced_ticks = 0
        self._recent: deque[tuple[float, bool, bool]] = deque()  # t, has voice, is loud
        self._smoothed: dict[str, float] = {}
        self._last_seen: dict[str, tuple[float, float]] = {}  # t, confidence

    def update(
        self,
        t: float,
        body: BodyFeatures | None = None,
        vocal: VocalFeatures | None = None,
        face: FaceFeatures | None = None,
        pulse: PulseSample | None = None,
    ) -> DistressScore:
        if pulse is not None and pulse.simulated:
            pulse = None  # Simulated data must never reach the score.
        if face is not None and (not face.detected or face.confidence < MIN_FACE_CONFIDENCE):
            face = None
        if self._started is None:
            someone_there = (
                (body is not None and body.people > 0)
                or face is not None
                or (vocal is not None and vocal.pitch_semitones is not None)
            )
            if not someone_there:  # An empty room must not use up the calibration period.
                return DistressScore(None, 0.0, baseline_progress=0.0)
            self._started = t

        if not self._calibrated:
            elapsed = t - self._started
            if elapsed < self._baseline_s:
                self._add_to_baseline(body, vocal, face, pulse)
                return DistressScore(None, 0.0, baseline_progress=elapsed / self._baseline_s)
            self._calibrated = True
            self._upset = self._check_upset()

        return self._score(t, self._signals(t, body, vocal, face, pulse))

    def _add_to_baseline(self, body, vocal, face, pulse) -> None:
        add = self._baseline.add
        if body is not None:
            if body.activity is not None:
                add("activity", body.activity)
            if body.parent_distance is not None:
                add("parent_distance", body.parent_distance)
        if vocal is not None:
            self._audio_ticks += 1
            # Only windows with a voice set the voice level. Otherwise a quiet room becomes the
            # reference, and ordinary talking looks like shouting.
            if vocal.pitch_semitones is not None:
                self._voiced_ticks += 1
                add("loudness", vocal.dbfs)
                add("pitch", vocal.pitch_semitones)
        if face is not None:
            for unit in FACE_UNITS:
                if unit in face.aus:
                    add(unit, face.aus[unit])
        if pulse is not None:
            add("heart_rate", pulse.bpm)

    def _check_upset(self) -> tuple[str, ...]:
        median = self._baseline.median
        reasons = []
        if (median("activity") or 0.0) >= UPSET_ACTIVITY:
            reasons.append("movement")
        talkative = self._voiced_ticks >= TALKATIVE_SHARE * max(self._audio_ticks, 1)
        loudness = median("loudness")
        if talkative and loudness is not None and loudness >= UPSET_DBFS:
            reasons.append("voice")
        if max(median("AU04") or 0.0, median("AU15") or 0.0) >= UPSET_AU:
            reasons.append("face")
        return tuple(reasons)

    def _signals(self, t, body, vocal, face, pulse) -> Signals:
        z, knows = self._baseline.z, self._baseline.knows
        activity = parent_distance = parent_ratio = None
        body_confidence = 0.0
        if body is not None:
            body_confidence = body.confidence
            if body.activity is not None:
                activity = z("activity", body.activity)
            parent_distance = body.parent_distance
            reference = self._baseline.median("parent_distance")
            if parent_distance is not None and reference:
                parent_ratio = parent_distance / reference

        loudness = pitch = None
        loud_share = fell_silent = 0.0
        if vocal is not None:
            if vocal.voiced:
                loudness = z("loudness", vocal.dbfs)
            if vocal.pitch_semitones is not None:
                pitch = z("pitch", vocal.pitch_semitones)
            loud_share, fell_silent = self._track_voice(t, vocal, loudness)

        face_z = None
        face_confidence = 0.0
        if face is not None:
            face_z = {unit: z(unit, face.aus[unit]) for unit in FACE_UNITS if unit in face.aus}
            known = all(knows(unit) for unit in face_z)
            shared = body is not None and body.people > 1
            face_confidence = (
                face.confidence
                * (1.0 if known else items.LOW_CONFIDENCE_DEFAULTS)
                * (SHARED_FRAME_FACE_CONFIDENCE if shared else 1.0)
            )
        return Signals(
            activity=activity,
            body_confidence=body_confidence,
            activity_baseline_known=knows("activity"),
            loudness=loudness,
            pitch=pitch,
            audio=vocal is not None,
            voice_baseline_known=knows("loudness"),
            loud_share=loud_share,
            fell_silent=fell_silent,
            face=face_z,
            face_confidence=face_confidence,
            heart_rate=z("heart_rate", pulse.bpm) if pulse is not None else None,
            parent_distance=parent_distance,
            parent_ratio=parent_ratio,
        )

    def _track_voice(self, t, vocal, loudness) -> tuple[float, float]:
        has_voice = vocal.pitch_semitones is not None
        self._recent.append((t, has_voice, loudness is not None and loudness >= LOUD_Z))
        while self._recent and t - self._recent[0][0] > SILENCE_WINDOW_S:
            self._recent.popleft()
        last_loud = [loud for seen, _, loud in self._recent if t - seen <= LOUD_WINDOW_S]
        loud_share = sum(last_loud) / len(last_loud)
        fell_silent = 0.0
        talkative = self._voiced_ticks >= TALKATIVE_SHARE * max(self._audio_ticks, 1)
        covered = t - self._recent[0][0] >= SILENCE_WINDOW_S * 0.9
        if talkative and self._audio_ticks and covered:
            voiced_share = sum(voice for _, voice, _ in self._recent) / len(self._recent)
            fell_silent = 1.0 if voiced_share <= 0.05 else 0.0
        return loud_share, fell_silent

    def _score(self, t: float, signals: Signals) -> DistressScore:
        current: dict[str, ItemScore] = {}
        for name, function in ITEM_FUNCTIONS.items():
            item = function(signals)
            if item is not None:
                previous = self._smoothed.get(name)
                if previous is None:
                    rating = item.rating
                else:
                    rate = RISE if item.rating > previous else FALL
                    rating = previous + rate * (item.rating - previous)
                self._smoothed[name] = rating
                self._last_seen[name] = (t, item.confidence)
                current[name] = ItemScore(rating, item.confidence)
            elif name in self._last_seen and t - self._last_seen[name][0] <= HOLD_S:
                current[name] = ItemScore(self._smoothed[name], self._last_seen[name][1] / 2)
            else:
                self._smoothed.pop(name, None)

        if not current:
            return DistressScore(None, 0.0, upset_during_baseline=self._upset)
        value = fuse({name: item.rating for name, item in current.items()})
        confidence = sum(ITEM_RANGE[name] * item.confidence for name, item in current.items())
        confidence /= sum(ITEM_RANGE.values())
        return DistressScore(value, confidence, current, 1.0, self._upset)

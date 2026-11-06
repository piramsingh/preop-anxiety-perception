"""Local camera window showing tracked keypoints and the current numbers. Nothing is saved."""

import cv2
import numpy as np

from preop.features.body import MIN_VISIBILITY, Person
from preop.pipeline import Tick

WINDOW = "Pre-op perception (press Q to close)"
BONES = [
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (11, 23), (12, 24), (23, 24),
    (23, 25), (25, 27), (24, 26), (26, 28), (0, 11), (0, 12),
]  # fmt: skip
GREEN, WHITE, BLACK = (80, 220, 80), (255, 255, 255), (0, 0, 0)


def _text(image: np.ndarray, text: str, y: int, scale: float = 0.7) -> None:
    cv2.putText(image, text, (16, y), cv2.FONT_HERSHEY_SIMPLEX, scale, BLACK, 5, cv2.LINE_AA)
    cv2.putText(image, text, (16, y), cv2.FONT_HERSHEY_SIMPLEX, scale, WHITE, 2, cv2.LINE_AA)


def _number(value: float | None, spec: str = ".2f") -> str:
    return "--" if value is None else format(value, spec)


def _face_text(tick: Tick) -> str:
    if tick.face is None:
        return "--"
    if not tick.face.detected:
        return "no face"
    active = " ".join(f"{name} {value:.1f}" for name, value in tick.face.active())
    return active or "neutral"


def draw_people(canvas: np.ndarray, people: list[Person]) -> None:
    height, width = canvas.shape[:2]
    for person in people:
        points = person.points
        xy = [(int(x * width), int(y * height)) for x, y, _ in points]
        for a, b in BONES:
            if points[a, 2] >= MIN_VISIBILITY and points[b, 2] >= MIN_VISIBILITY:
                cv2.line(canvas, xy[a], xy[b], GREEN, 3, cv2.LINE_AA)
        for index, point in enumerate(xy):
            if points[index, 2] >= MIN_VISIBILITY:
                cv2.circle(canvas, point, 4, WHITE, -1, cv2.LINE_AA)


def draw(image: np.ndarray, people: list[Person], tick: Tick | None) -> np.ndarray:
    canvas = image.copy()
    height = canvas.shape[0]
    draw_people(canvas, people)
    _text(canvas, f"People detected: {len(people)}", 34)
    if tick is not None:
        body, vocal = tick.body, tick.vocal
        if tick.score.calibrating:
            _text(canvas, f"Calibrating: {tick.score.baseline_progress:.0%}", 68, 0.9)
        else:
            value = _number(tick.score.value, ".0f")
            _text(canvas, f"mYPAS: {value}  conf {tick.score.confidence:.2f}", 68, 0.9)
        _text(canvas, f"Movement: {_number(body.activity if body else None)}", 102)
        _text(canvas, f"Loudness: {_number(vocal.dbfs if vocal else None, '.0f')} dB", 134)
        _text(canvas, f"Pitch: {_number(vocal.pitch_semitones if vocal else None, '.1f')}", 166)
        _text(canvas, f"Face: {_face_text(tick)}", 198)
    _text(canvas, "Unvalidated research estimate", height - 20, 0.6)
    return canvas


class PreviewWindow:
    def __init__(self) -> None:
        self._opened = False

    def show(self, image: np.ndarray) -> bool:
        """Show a frame. Returns False once the user closes the window."""
        cv2.imshow(WINDOW, image)
        if not self._opened:
            self._opened = True
            cv2.setWindowProperty(WINDOW, cv2.WND_PROP_TOPMOST, 1)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            return False
        return cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) >= 1

    def close(self) -> None:
        cv2.destroyAllWindows()
        cv2.waitKey(1)

"""Guided check: prompts for each expression and reports what OpenFace measured.

Saves action unit numbers to data/face_checks/ (gitignored). Never saves video or images.
Run with: uv run preop-face-check
"""

import csv
import statistics
import time
from pathlib import Path

import cv2

from preop.features.face import FaceExtractor, FaceFeatures
from preop.preview import PreviewWindow

REACTION_S = 1.5  # Skip the start of each prompt while the person reacts.
PHASES = [
    ("ready", "GET READY", 8.0),
    ("neutral", "Relax your face", 6.0),
    ("smile", "BIG SMILE", 6.0),
    ("neutral", "Relax your face", 5.0),
    ("frown", "HARD FROWN", 6.0),
    ("neutral", "Relax your face", 5.0),
    ("brows", "RAISE EYEBROWS", 6.0),
    ("neutral", "Relax your face", 5.0),
]
EXPECTED = {"smile": ["AU12", "AU06"], "frown": ["AU04"], "brows": ["AU01", "AU02"]}


def phase_at(elapsed: float, phases=PHASES) -> tuple[int, float] | None:
    """Index of the current phase and the seconds left in it, or None when finished."""
    start = 0.0
    for index, (_, _, length) in enumerate(phases):
        if elapsed < start + length:
            return index, start + length - elapsed
        start += length
    return None


def summarize(rows: list[dict]) -> str:
    """Compares each expression with the relaxed face. Rows hold phase, since, detected, AUs."""
    usable = [r for r in rows if r["detected"] and r["since"] >= REACTION_S]

    def mean(phase: str, unit: str) -> float | None:
        values = [r[unit] for r in usable if r["phase"] == phase and unit in r]
        return statistics.fmean(values) if values else None

    total = [r for r in rows if r["phase"] != "ready"]
    found = sum(r["detected"] for r in total) / max(len(total), 1)
    lines = [f"Face found in {found:.0%} of {len(total)} frames", ""]
    lines.append(f"{'Expression':<12}{'Unit':<7}{'Relaxed':>9}{'During':>9}{'Change':>9}")
    for phase, units in EXPECTED.items():
        for unit in units:
            relaxed, during = mean("neutral", unit), mean(phase, unit)
            if relaxed is None or during is None:
                lines.append(f"{phase:<12}{unit:<7}{'no data':>9}")
                continue
            change = during - relaxed
            lines.append(f"{phase:<12}{unit:<7}{relaxed:>9.2f}{during:>9.2f}{change:>+9.2f}")
    return "\n".join(lines)


def _row(phase: str, since: float, t: float, face: FaceFeatures) -> dict:
    return {"phase": phase, "since": round(since, 3), "t": round(t, 3), "detected": face.detected,
            "confidence": face.confidence, **face.aus}  # fmt: skip


def _save(rows: list[dict]) -> Path:
    folder = Path("data/face_checks")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"face_check_{time.strftime('%Y%m%d_%H%M%S')}.csv"
    columns = sorted({key for row in rows for key in row})
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return path


def main() -> int:
    camera = cv2.VideoCapture(0, cv2.CAP_AVFOUNDATION)
    if not camera.isOpened():
        print("Camera did not open.")
        return 1
    extractor = FaceExtractor.from_paths()
    window = PreviewWindow()
    rows: list[dict] = []
    start = time.monotonic()
    phase_started = {}
    try:
        while True:
            ok, frame = camera.read()
            if not ok:
                continue
            now = time.monotonic()
            current = phase_at(now - start)
            if current is None:
                break
            index, remaining = current
            name, prompt, _ = PHASES[index]
            phase_started.setdefault(index, now)
            face = extractor.analyze(now, frame)
            rows.append(_row(name, now - phase_started[index], now - start, face))

            canvas = cv2.flip(frame, 1)
            text = f"{prompt}  {remaining:.0f}"
            cv2.putText(canvas, text, (40, 90), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 0, 0), 12)
            cv2.putText(canvas, text, (40, 90), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255, 255, 255), 4)
            status = "Face found" if face.detected else "NO FACE: look at the camera"
            cv2.putText(canvas, status, (40, 150), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (80, 220, 80), 3)
            if not window.show(canvas):
                print("Stopped early.")
                break
    finally:
        camera.release()
        extractor.close()
        window.close()
    print(summarize(rows))
    print(f"\nSaved numbers only (no video): {_save(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

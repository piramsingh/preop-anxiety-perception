"""Listen to a whole story with its sounds, the way the child hears it, on the Mac.

    uv run python -m lullaby.preview dinosaurs            # story part 1, breathing, part 2
    uv run python -m lullaby.preview heroes --play         # and play it right away
    uv run python -m lullaby.preview --all                # make every sound (no story)

Writes audio_cache/preview_<theme>.wav and prints each line's levels: the voice peak, the
finished mix peak (never above the voice) and which sounds are under it.
"""

from __future__ import annotations

import argparse
import subprocess
import wave

import numpy as np

from . import sfx, voice
from .content import STEPS_BY_KEY, THEMES, fill, plain
from .director import LINE_GAP

STORY = ["got_name", "chapter1", "breathing", "chapter2"]


def _read(path) -> np.ndarray:
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("theme", nargs="?", choices=sorted(THEMES))
    ap.add_argument("--kid", default="Sam")
    ap.add_argument("--robot", default="Juni")
    ap.add_argument("--play", action="store_true")
    ap.add_argument("--all", action="store_true", help="make every sound effect and bed")
    a = ap.parse_args()

    if a.all:
        for key in sfx.all_sound_keys():
            path = sfx._effect_file(key)
            print(f"  {key:14s} {'ok' if path else 'MISSING'}")
        if not a.theme:
            return
    if not a.theme:
        ap.error("pick a theme")

    theme = THEMES[a.theme]
    gap = np.zeros(int(voice.RATE_HZ * (LINE_GAP + 0.4)), dtype="<i2")  # + a typical motion
    parts = []
    print(f"{'step':10s} {'voice':>6s} {'mix':>6s}  sounds / line")
    for key in STORY:
        for beat, (text, _) in enumerate(STEPS_BY_KEY[key].beats):
            if not text:
                continue
            line = fill(text, a.kid, a.robot, theme)
            speech = voice.tts_line(line, a.theme)
            cue = sfx.cue_for(key, beat, a.theme)
            mixed = sfx.with_effect(speech, cue)
            v_peak, m_peak = sfx._levels(speech)[0], sfx._levels(mixed)[0]
            sounds = " + ".join(filter(None, [
                cue.start and cue.start.key, cue.end and f"{cue.end.key}@end", cue.bed]))
            print(f"{key:10s} {sfx._db(v_peak):5.1f}dB {sfx._db(m_peak):5.1f}dB  "
                  f"{sounds or '-':28s} {plain(line)[:50]}")
            parts += [_read(mixed), gap]
    out = voice.CACHE / f"preview_{a.theme}.wav"
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(voice.RATE_HZ)
        w.writeframes(np.concatenate(parts).tobytes())
    print(f"\n{out}  ({voice.duration(out):.0f}s)")
    if a.play:
        subprocess.run(["afplay", str(out)], check=False)


if __name__ == "__main__":
    main()

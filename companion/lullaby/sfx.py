"""Gentle sound effects for the stories.

Each effect is made once with ElevenLabs (text-to-sound), saved, and then mixed
softly under the start of a story line, so the robot plays one file per line.
Nothing loud or sudden, and never in quiet mode (only story steps get effects).
If there's no ElevenLabs key, or making an effect fails, the line just plays without it.
Set LULLABY_SFX=0 to turn effects off.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import wave
from pathlib import Path

import numpy as np

from . import voice
from .content import STEPS

log = logging.getLogger("lullaby.sfx")

ENABLED = os.environ.get("LULLABY_SFX", "1") != "0"
SFX_VOLUME = float(os.environ.get("LULLABY_SFX_VOLUME", "0.35"))  # under the voice, never over it

# key: (what to ask ElevenLabs for, seconds)
EFFECTS: dict[str, tuple[str, float]] = {
    "vroom": ("A friendly toy monster truck engine revving softly twice, playful, cartoon, "
              "no crash, no horn", 2.0),
    "sparkle": ("A soft magical sparkle, gentle twinkling chimes, fairy tale, calm", 2.0),
    "stomp": ("Two soft, bouncy cartoon dinosaur footsteps, playful and friendly, not scary, "
              "no roar", 1.8),
    "rocket": ("A soft cartoon rocket whoosh lifting off, gentle and airy, no explosion", 2.0),
    "puppy": ("A happy little puppy giving two soft, gentle barks, friendly", 1.5),
    "whoosh": ("A soft superhero cape whoosh flying by, gentle and airy", 1.5),
    "boing": ("A soft, playful cartoon boing, quiet and cute", 1.0),
    "lullaby": ("A slow, soft music box lullaby twinkle, calm and sleepy", 2.5),
    "birds": ("Two clear, cheerful little bird chirps close up, soft morning birdsong", 2.5),
    "chime": ("A gentle, cheerful success chime, soft bells, calm", 1.5),
}

THEME_SFX = {"trucks": "vroom", "princess": "sparkle", "dinosaurs": "stomp",
             "space": "rocket", "animals": "puppy", "heroes": "whoosh"}

# (step, a snippet of the line's script, effect or "theme" for the child's story sound)
_RULES = [
    ("got_name", "I love it", "chime"),
    ("chapter1", "{picked}", "theme"),
    ("chapter1", "loved {fun}", "theme"),
    ("chapter1", "Peekaboo", "boing"),
    ("chapter1", "cozy nap", "lullaby"),
    ("breathing", "super breather", "chime"),
    ("chapter2", "You woke up", "birds"),
    ("chapter2", "back to {fun}", "theme"),
    ("chapter2", "brave badge", "chime"),
]


def _build_index() -> dict[tuple[str, int], str]:
    index = {}
    for rule_step, snippet, key in _RULES:
        for st in STEPS:
            if st.key != rule_step:
                continue
            for i, (text, _) in enumerate(st.beats):
                if snippet in text:
                    index[(st.key, i)] = key
    return index


SFX_BY_BEAT = _build_index()


def effect_for(step_key: str | None, beat: int, theme: str) -> str | None:
    """Which effect (if any) goes under this line of this step."""
    if not ENABLED or not step_key:
        return None
    key = SFX_BY_BEAT.get((step_key, beat))
    if key == "theme":
        key = THEME_SFX.get(theme)
    return key


def _effect_file(key: str) -> Path | None:
    """The effect's audio, made once with ElevenLabs and cached. None if unavailable."""
    prompt, seconds = EFFECTS[key]
    digest = hashlib.sha1(f"{prompt}|{seconds}".encode()).hexdigest()[:10]
    out = voice.CACHE / f"sfx_{key}_{digest}.wav"
    if out.exists():
        return out
    if not voice.EL_KEY:
        return None
    try:
        voice.CACHE.mkdir(parents=True, exist_ok=True)
        # Ask for MP3: it carries its own sample rate. (Raw PCM from the sound-effects
        # endpoint came back at a different rate than requested: twice as long, an octave low.)
        mp3 = b"".join(voice._el().text_to_sound_effects.convert(
            text=prompt, duration_seconds=seconds, prompt_influence=0.5,
            model_id="eleven_text_to_sound_v3", output_format="mp3_44100_128",
        ))
        if len(mp3) < 1000:
            raise RuntimeError("almost no audio")
        src = voice._tmp(out).with_suffix(".mp3")
        src.write_bytes(mp3)
        try:
            voice.to_wav(src, out)  # 22 kHz mono PCM16, same as the voice
        finally:
            src.unlink(missing_ok=True)
        log.info("Made sound effect %s", key)
        return out
    except Exception as e:  # noqa: BLE001 - a story without a sound effect is fine
        log.warning("Sound effect %s unavailable: %s", key, e)
        return None


def _peak(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    return float(np.abs(data).max()) / 32768 if len(data) else 0.0


def with_effect(speech: Path, key: str | None) -> Path:
    """The line with its effect softly underneath: the effect starts, the voice comes in
    a moment later, and the effect fades out. Returns the plain line if anything fails."""
    if not key or key not in EFFECTS:
        return speech
    fx = _effect_file(key)
    if fx is None:
        return speech
    gain = SFX_VOLUME * min(8.0, 0.6 / max(_peak(fx), 1e-3))  # every effect at the same soft level
    out = voice.CACHE / f"mix_{key}_{speech.stem}_{gain:.3f}.wav"
    if out.exists():
        return out
    fx_len = voice.duration(fx)
    lead = min(fx_len * 0.5, 0.8)  # seconds of effect before the voice starts
    fade_at = max(0.0, fx_len - 0.6)
    delay = int(lead * 1000)
    tmp = voice._tmp(out)
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(fx), "-i", str(speech),
             "-filter_complex",
             f"[0]volume={gain:.3f},afade=t=in:d=0.08,afade=t=out:st={fade_at:.2f}:d=0.6[f];"
             f"[1]adelay={delay}|{delay}[v];"
             "[f][v]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.95",
             "-ac", "1", "-ar", str(voice.RATE_HZ), "-sample_fmt", "s16", str(tmp)],
            check=True,
        )
        tmp.replace(out)
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("Couldn't mix sound effect %s: %s", key, e)
        tmp.unlink(missing_ok=True)
        return speech

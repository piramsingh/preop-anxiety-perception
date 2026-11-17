"""Story sound design: soft ambience beds and spot effects, mixed under the robot's voice.

The stories should feel like a little audio show, but never too loud for a scared child:
  * Each scene has a quiet ambience bed (the hero's world, a cozy music-box room, morning birds).
  * Spot effects land on the words they belong to, at the start or the end of a line.
  * Levels are set against the line's own voice, not absolute: spots sit about a quarter of
    the voice (-12 dB), beds far lower (-26 dB). Every sound fades in (no sudden starts),
    harsh highs and rumble are filtered out, and the finished line is limited so its peak is
    never above the voice alone.

Each effect is made once with ElevenLabs (text-to-sound) and cached; mixes are cached too,
so the robot still plays one file per line. Only story steps get sound: never quiet mode,
parent messages, the goodbye, quick lines or re-ask lines. With no ElevenLabs key, or if
anything fails, a line plays without its sound. LULLABY_SFX=0 turns everything off;
LULLABY_SFX_VOLUME scales all sound levels (1.0 = the levels above).
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import voice
from .content import STEPS

log = logging.getLogger("lullaby.sfx")

ENABLED = os.environ.get("LULLABY_SFX", "1") != "0"
VOLUME = float(os.environ.get("LULLABY_SFX_VOLUME", "1.0"))

SPOT_DB = -12.0     # spot effects vs the voice (about a quarter)
SOFT_DB = -18.0     # the breathing game: barely there
BED_DB = -26.0      # ambience beds: felt more than heard
SPOT_PEAK = 0.5     # a spot's peak never above half the voice's peak (clicks, bells)
BED_PEAK = 0.2
BED_TAIL = 0.4      # seconds the bed rings on after the voice, so lines don't cut off dead

# key: (what to ask ElevenLabs for, seconds)
EFFECTS: dict[str, tuple[str, float]] = {
    # theme sounds: one when the child picks the story, a second one later in it
    "sparkle": ("A soft magical sparkle, gentle twinkling chimes, fairy tale, calm", 2.0),
    "stomp": ("Two soft, bouncy cartoon dinosaur footsteps, playful and friendly, not scary, "
              "no roar", 1.8),
    "whoosh": ("A soft superhero cape whoosh flying by, gentle and airy", 1.5),
    "bells": ("Gentle faraway castle bells ringing softly, warm and calm", 2.0),
    "chirp": ("A tiny friendly baby dinosaur chirp, cute and soft, cartoon, not scary", 1.2),
    "cape": ("A soft cloth cape flapping gently in the wind, superhero", 1.2),
    # story moments
    "once": ("A soft storybook opening, a gentle harp glissando with a light twinkle, calm", 2.0),
    "click": ("A tiny soft plastic snap, like a bracelet clicking closed, quiet", 0.8),
    "rustle": ("Soft cotton pajamas rustling gently, cozy and quiet", 1.2),
    "balloon": ("A soft, airy whoosh like a balloon gently letting out air, calm, cartoon", 1.5),
    "boing": ("A soft, playful cartoon boing, quiet and cute", 1.0),
    "lullaby": ("A slow, soft music box lullaby twinkle, calm and sleepy", 2.5),
    "tbc": ("A short, soft, curious music box phrase that ends on a question, to be continued",
            2.0),
    "birds": ("Two clear, cheerful little bird chirps close up, soft morning birdsong", 2.5),
    "chime": ("A gentle, cheerful success chime, soft bells, calm", 1.5),
    "badge": ("A short, soft, happy celebration jingle on glockenspiel and bells, gentle", 2.0),
    # superhero story: it should sound like a soft comic-book cartoon
    "hero_sting": ("A short, soft heroic cartoon fanfare, gentle brass and strings rising, "
                   "comic book superhero intro, warm, not loud", 2.5),
    "hero_fanfare": ("A short, happy superhero victory flourish, soft brass and twinkling bells, "
                     "cartoon, warm, not loud", 2.5),
    # breathing game
    "breath_in": ("A very soft rising airy chime, like a gentle breath in, calm", 1.5),
    "candles": ("A soft gentle puff of breath blowing out tiny candles, with a faint twinkle", 1.2),
}

# key: (what to ask ElevenLabs for, seconds). Looped under a scene's lines, very quietly.
BEDS: dict[str, tuple[str, float]] = {
    "bed_princess": ("Calm castle garden ambience, a small fountain trickling and soft birdsong, "
                     "peaceful, steady", 12.0),
    "bed_dinosaurs": ("Calm, friendly jungle ambience, soft leaves rustling, gentle insects and "
                      "distant tropical birds, peaceful, no animal roars, steady", 12.0),
    "bed_heroes": ("Soft, gentle heroic adventure music for a children's cartoon, light strings "
                   "and warm, quiet brass, hopeful and calm, steady, no drums", 12.0),
    "bed_cozy": ("Soft, slow, warm music box and gentle pad, a calm cozy room, sleepy, "
                 "steady, no percussion", 12.0),
    "bed_morning": ("Calm early morning ambience, soft birdsong outside a window, peaceful, "
                    "steady", 12.0),
}

THEME_SFX = {"princess": "sparkle", "dinosaurs": "stomp", "heroes": "whoosh"}
# A theme can swap a story moment's sound for its own (the superhero story gets comic-book stings).
THEME_OVERRIDES = {
    "heroes": {"once": "hero_sting", "sparkle": "hero_fanfare"},
}

THEME_SFX2 = {"princess": "bells", "dinosaurs": "chirp", "heroes": "cape"}

# (step, a snippet of the line's script, what plays). Effects: "key" plays at the start of
# the line, "key@end" as the line finishes. "theme"/"theme2" are the child's story sounds.
# "bed:..." is the scene's ambience; "bed:world" is the hero's world for the child's theme.
_RULES = [
    ("got_name", "I love it", "chime"),
    ("chapter1", "{picked}", "theme"),
    ("chapter1", "Once upon a time", "once"),
    ("chapter1", "Once upon a time", "bed:world"),
    ("chapter1", "loved {fun}", "theme"),
    ("chapter1", "loved {fun}", "bed:world"),
    ("chapter1", "<hero>{catch}</hero>", "bed:world"),
    ("chapter1", "a little fix", "theme2@end"),
    ("chapter1", "a little fix", "bed:world"),
    ("chapter1", "tiny bit nervous", "bed:cozy"),
    ("chapter1", "Lots of friends feel nervous", "bed:cozy"),
    ("chapter1", "special bracelet", "click"),
    ("chapter1", "special bracelet", "bed:cozy"),
    ("chapter1", "comfy pajamas", "rustle"),
    ("chapter1", "comfy pajamas", "bed:cozy"),
    ("chapter1", "Peekaboo", "boing@end"),
    ("chapter1", "Peekaboo", "bed:cozy"),
    ("chapter1", "sleepy mask", "balloon@end"),
    ("chapter1", "sleepy mask", "bed:cozy"),
    ("chapter1", "big, slow breaths", "bed:cozy"),
    ("chapter1", "cozy nap", "lullaby"),
    ("chapter1", "cozy nap", "bed:cozy"),
    ("chapter1", "chapter two", "tbc@end"),
    ("breathing", "Smell the flower", "~breath_in@end"),
    ("breathing", "blow out the birthday", "~candles@end"),
    ("breathing", "Blow out the candles", "~candles@end"),
    ("breathing", "blow them all out", "~candles@end"),
    ("breathing", "super breather", "chime"),
    ("chapter2", "You woke up", "birds"),
    ("chapter2", "woke up in a cozy room", "bed:morning"),
    ("chapter2", "kind nurse", "bed:morning"),
    ("chapter2", "Thank you for telling me", "bed:morning"),
    ("chapter2", "tell your nurse how you feel", "bed:morning"),
    ("chapter2", "fix worked", "sparkle"),
    ("chapter2", "fix worked", "bed:world"),
    ("chapter2", "<hero>{catch}</hero>", "theme@end"),
    ("chapter2", "<hero>{catch}</hero>", "bed:world"),
    ("chapter2", "brave badge", "badge"),
]


@dataclass(frozen=True)
class Spot:
    key: str
    at_end: bool = False
    soft: bool = False   # the breathing game's quieter level


@dataclass(frozen=True)
class Cue:
    """Everything that plays under one line."""
    start: Spot | None = None
    end: Spot | None = None
    bed: str | None = None

    def __bool__(self) -> bool:
        return bool(self.start or self.end or self.bed)


def _build_index() -> dict[tuple[str, int], list[str]]:
    index: dict[tuple[str, int], list[str]] = {}
    for rule_step, snippet, what in _RULES:
        for st in STEPS:
            if st.key != rule_step:
                continue
            for i, (text, _) in enumerate(st.beats):
                if snippet in text:
                    index.setdefault((st.key, i), []).append(what)
    return index


SFX_BY_BEAT = _build_index()


def cue_for(step_key: str | None, beat: int, theme: str) -> Cue:
    """What plays under this line of this step (an empty Cue for none)."""
    if not ENABLED or not step_key:
        return Cue()
    start = end = bed = None
    for what in SFX_BY_BEAT.get((step_key, beat), []):
        if what.startswith("bed:"):
            name = what[4:]
            bed = f"bed_{theme}" if name == "world" else f"bed_{name}"
            bed = bed if bed in BEDS else None
            continue
        soft = what.startswith("~")
        key, _, where = what.lstrip("~").partition("@")
        if key == "theme":
            key = THEME_SFX.get(theme)
        elif key == "theme2":
            key = THEME_SFX2.get(theme)
        key = THEME_OVERRIDES.get(theme, {}).get(key, key)
        if key not in EFFECTS:
            continue
        if where == "end":
            end = Spot(key, at_end=True, soft=soft)
        else:
            start = Spot(key, soft=soft)
    return Cue(start, end, bed)


# ---- making the sounds ------------------------------------------------------
def _effect_file(key: str) -> Path | None:
    """The effect or bed audio, made once with ElevenLabs and cached. None if unavailable."""
    prompt, seconds = EFFECTS.get(key) or BEDS[key]
    digest = hashlib.sha1(f"{prompt}|{seconds}".encode()).hexdigest()[:10]
    out = voice.CACHE / f"sfx_{key}_{digest}.wav"
    if out.exists():
        return out
    if not voice.EL_KEY:
        return None
    try:
        voice.CACHE.mkdir(parents=True, exist_ok=True)
        # Ask for MP3: it carries its own sample rate and channel count. (Raw PCM from the
        # sound-effects endpoint is stereo, which played back as mono sounds twice as long
        # and an octave low.)
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
        log.info("Made sound %s", key)
        return out
    except Exception as e:  # noqa: BLE001 - a story without a sound effect is fine
        log.warning("Sound %s unavailable: %s", key, e)
        return None


def _levels(path: Path) -> tuple[float, float]:
    """(peak, rms) of a WAV as fractions of full scale. RMS skips near-silence, so pauses
    between words don't make the voice look quieter than it sounds."""
    with wave.open(str(path), "rb") as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
    if not len(data):
        return 0.0, 0.0
    peak = float(np.abs(data).max())
    frames = data[: len(data) // 512 * 512].reshape(-1, 512)
    frame_rms = np.sqrt((frames ** 2).mean(axis=1)) if len(frames) else np.array([peak])
    loud = frame_rms[frame_rms > max(peak * 0.05, 1e-4)]
    rms = float(np.sqrt((loud ** 2).mean())) if len(loud) else float(frame_rms.mean())
    return peak, rms


def _gain(fx: Path, voice_peak: float, voice_rms: float, rel_db: float, peak_cap: float) -> float:
    """Gain that puts `fx` at rel_db under the voice, never peaking above peak_cap x voice."""
    peak, rms = _levels(fx)
    if peak <= 0 or rms <= 0:
        return 0.0
    g = voice_rms * 10 ** (rel_db / 20) / rms
    g = min(g, peak_cap * voice_peak / peak)
    return g * VOLUME


def with_effect(speech: Path, cue: Cue | None) -> Path:
    """The line with its sounds mixed underneath. A start effect leads the voice in, an end
    effect lands as the last word finishes, and the bed runs under the whole line. Returns
    the plain line if there's nothing to add or anything fails."""
    if not cue:
        return speech
    start = _effect_file(cue.start.key) if cue.start else None
    end = _effect_file(cue.end.key) if cue.end else None
    bed = _effect_file(cue.bed) if cue.bed else None
    if not (start or end or bed):
        return speech

    v_peak, v_rms = _levels(speech)
    if v_peak <= 0:
        return speech
    v_len = voice.duration(speech)
    spot_db = lambda s: SOFT_DB if s.soft else SPOT_DB  # noqa: E731
    g_start = _gain(start, v_peak, v_rms, spot_db(cue.start), SPOT_PEAK) if start else 0.0
    g_end = _gain(end, v_peak, v_rms, spot_db(cue.end), SPOT_PEAK) if end else 0.0
    g_bed = _gain(bed, v_peak, v_rms, BED_DB, BED_PEAK) if bed else 0.0

    # timing (seconds)
    lead = min(voice.duration(start) * 0.5, 0.8) if start else (0.3 if bed else 0.0)
    end_at = lead + max(0.0, v_len - 0.25)
    total = lead + v_len
    if end:
        total = max(total, end_at + voice.duration(end))
    if bed:
        total += BED_TAIL

    tag = "|".join([speech.stem, repr(cue), f"{g_start:.4f}", f"{g_end:.4f}", f"{g_bed:.4f}",
                    str(lead)])
    out = voice.CACHE / f"mix2_{speech.stem}_{hashlib.sha1(tag.encode()).hexdigest()[:10]}.wav"
    if out.exists():
        return out

    soften = "highpass=f=120,lowpass=f=7000"
    inputs = ["-i", str(speech)]
    chains = [f"[0]adelay={int(lead * 1000)}:all=1[v]"]
    labels = ["[v]"]

    def spot(path: Path, gain: float, at: float, name: str) -> None:
        n = len(inputs) // 2
        inputs.extend(["-i", str(path)])
        fx_len = voice.duration(path)
        chains.append(
            f"[{n}]{soften},volume={gain:.4f},afade=t=in:d=0.08,"
            f"afade=t=out:st={max(0.0, fx_len - 0.6):.2f}:d=0.6,"
            f"adelay={int(at * 1000)}:all=1[{name}]")
        labels.append(f"[{name}]")

    if start:
        spot(start, g_start, 0.0, "s")
    if end:
        spot(end, g_end, end_at, "e")
    if bed:
        n = len(inputs) // 2
        inputs.extend(["-stream_loop", "-1", "-i", str(bed)])
        chains.append(
            f"[{n}]highpass=f=120,lowpass=f=5000,volume={g_bed:.4f},atrim=0:{total:.2f},"
            f"afade=t=in:d=0.6,afade=t=out:st={max(0.0, total - 0.8):.2f}:d=0.8[b]")
        labels.append("[b]")

    # The finished line never peaks above the voice alone (level=disabled: limit only,
    # never turn anything up).
    limit = max(0.0625, min(1.0, v_peak))
    graph = ";".join(chains) + ";" + "".join(labels) + (
        f"amix=inputs={len(labels)}:duration=longest:normalize=0,"
        f"alimiter=limit={limit:.4f}:level=disabled:attack=2:release=50")
    tmp = voice._tmp(out)
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", graph,
             "-t", f"{total:.2f}", "-ac", "1", "-ar", str(voice.RATE_HZ), "-sample_fmt", "s16",
             str(tmp)],
            check=True,
        )
        tmp.replace(out)
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("Couldn't mix sounds %s: %s", cue, e)
        tmp.unlink(missing_ok=True)
        return speech


def all_sound_keys() -> list[str]:
    return list(EFFECTS) + list(BEDS)


def _db(x: float) -> float:
    return 20 * math.log10(max(x, 1e-9))

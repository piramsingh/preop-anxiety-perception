"""Speech-to-text for the child's answers, fully offline (local Whisper).

The child's voice never leaves the laptop: the recording is transcribed here and
deleted right away. The nurse always sees the result and can correct it.
"""

from __future__ import annotations

import difflib
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

import numpy as np

log = logging.getLogger("lullaby.listen")

MODEL_NAME = os.environ.get("LULLABY_WHISPER", "base.en")  # "small.en" is more accurate, slower
_model = None
_lock = threading.Lock()

HINTS = {
    "nickname": "A child says a nickname for a friendly robot, like Sparkle, Beepy or Mr. Wiggles.",
    "story": "Monster trucks, princesses, dinosaurs, outer space, animals, or superheroes.",
}

# Words a child might say for each story theme.
THEME_WORDS: dict[str, tuple[str, ...]] = {
    "trucks": ("truck", "monster", "car", "vroom", "wheel", "tractor", "digger"),
    "princess": ("princess", "prince", "queen", "king", "castle", "royal", "fairy"),
    "dinosaurs": ("dino", "dinosaur", "rex", "roar", "raptor", "jurassic"),
    "space": ("space", "rocket", "astronaut", "star", "planet", "moon", "alien", "blast"),
    "animals": ("animal", "puppy", "dog", "doggy", "cat", "kitty", "bunny", "lion", "bear",
                "horse", "pet", "woof"),
    "heroes": ("superhero", "super hero", "hero", "super", "batman", "spider", "flying"),
}

# Whisper sometimes "hears" these in silence.
_PHANTOMS = {"", "you", "thank you", "thanks", "thanks for watching", "bye", "okay", "ok"}


def warm_up() -> None:
    """Load the model in the background so the first answer isn't slow."""
    threading.Thread(target=_get_model, daemon=True).start()


def _get_model():
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel

            _model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
            log.info("Whisper %s ready", MODEL_NAME)
        return _model


_run_lock = threading.Lock()  # one Whisper run at a time


def _whisper(audio: np.ndarray, purpose: str, beam: int = 5) -> str:
    with _run_lock:
        segments, _ = _get_model().transcribe(
            audio, language="en", beam_size=beam, vad_filter=True,
            initial_prompt=HINTS.get(purpose), condition_on_previous_text=False,
        )
        return " ".join(s.text.strip() for s in segments).strip()


def _decode_bytes(data: bytes, filename: str) -> np.ndarray:
    with tempfile.TemporaryDirectory(prefix="lullaby_listen_") as tmp:
        raw = Path(tmp) / ("answer" + (Path(filename or "a.webm").suffix or ".webm"))
        raw.write_bytes(data)
        return _decode_16k(raw)


# Words that don't count as the child saying something new.
_FILLER = {"a", "an", "the", "and", "or", "um", "uh", "oh", "i", "you", "it", "is", "to", "me",
           "my", "of", "in", "on", "yes", "yeah", "no", "ok", "okay", "hmm", "so"}


def _novel(word: str, robot_words: list[str]) -> bool:
    if len(word) < 3 or word in _FILLER:
        return False
    return not any(difflib.SequenceMatcher(None, word, r).ratio() >= 0.75 for r in robot_words)


def peek(data: bytes, filename: str, purpose: str, robot_near: str, robot_all: str,
         window: float = 3.0, robot_wide: str = "") -> dict:
    """While the robot is still asking: is the child saying something the robot isn't?

    robot_near: what the robot said in the last few seconds (what can leak into the mic now).
    robot_all: everything the robot says in this question.
    """
    audio = _decode_bytes(data, filename)[-int(window * 16000):]
    if len(audio) < 16000 * 0.4:
        return {"barge": False, "text": ""}
    text = _whisper(audio, purpose, beam=1)
    if text.lower().strip(" .!?,") in _PHANTOMS:
        return {"barge": False, "text": ""}
    words = _words(text)
    if purpose == "story":
        # Take out the robot's own run of words ("princesses, dinosaurs, outer space"). A story
        # word left over (out of the robot's order, or said again) is the child picking one.
        # The panel only stops the robot when two checks in a row agree, to skip glitches.
        near = (robot_wide or robot_near).lower()
        for key, kws in THEME_WORDS.items():   # a story the robot isn't naming around now
            if any(k in text.lower() for k in kws) and not any(k in near for k in kws):
                return {"barge": True, "theme": key, "text": text}
        left = strip_robot(text, robot_near).lower()
        for key, kws in THEME_WORDS.items():
            if any(k in left for k in kws):
                return {"barge": False, "candidate": key, "text": text}
        novel = [w for w in words if _novel(w, _words(robot_all))]
        return {"barge": len(novel) >= 2, "text": text}
    novel = [w for w in words if _novel(w, _words(robot_all))]
    return {"barge": bool(novel), "text": text, "novel": novel}


def transcribe(data: bytes, filename: str, purpose: str, start: float = 0.0,
               robot_text: str = "") -> str:
    """Turn a short recording into text. The recording is deleted before returning.

    start: skip this many seconds (the part where only the robot was talking).
    robot_text: what the robot said; any of it that leaked into the mic is removed.
    """
    audio = _decode_bytes(data, filename)[int(max(0.0, start) * 16000):]
    if len(audio) < 16000 * 0.3:
        return ""
    text = _whisper(audio, purpose)
    if robot_text:
        # If everything heard matches the robot's words, the child said exactly what the robot
        # was saying ("Monster trucks!" over "Monster trucks"). Keep it rather than drop it.
        text = strip_robot(text, robot_text) or text
    if text.lower().strip(" .!?,") in _PHANTOMS:
        return ""
    return text


_LEADS = [
    r"(um+|uh+|hmm+|erm+|well|like|okay|ok|so|yeah|yes)\b[,.!]?",
    r"(i (want to|wanna|will|'ll|would|'d like to)?\s*call you|i name you|call you|name you)",
    r"(your name is|your name should be|you('re| are)|you can be|you should be)",
    r"(how about|maybe|i think|it's|its|it is)",
]


def _decode_16k(path: Path) -> np.ndarray:
    """Decode any recording to 16 kHz mono float32 samples with ffmpeg (what Whisper wants)."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("Listening needs ffmpeg: brew install ffmpeg")
    pcm = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", "16000",
         "-f", "f32le", "pipe:1"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(pcm, dtype=np.float32).copy()


def clean_nickname(text: str) -> str:
    """'Um, I wanna call you sparkle!' -> 'Sparkle'."""
    t = text.strip()
    for _ in range(4):  # peel off filler and lead-in phrases
        before = t
        for lead in _LEADS:
            t = re.sub(rf"^\s*{lead}\s*[,.!]?\s*", "", t, flags=re.I)
        if t == before:
            break
    t = re.sub(r"[^\w\s'.-]", "", t)  # drop emoji and stray punctuation
    t = re.sub(r"\s+", " ", t).strip(" .-'")
    words = t.split(" ")[:4]  # a nickname, not a sentence
    return " ".join(w[:1].upper() + w[1:] for w in words if w)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def robot_tail(line: str, fraction: float, before: int = 1, after: int = 4) -> str:
    """The few words the robot was saying when it got interrupted, `fraction` of the way
    through `line`. Only these can leak into the child's answer; filtering the whole line
    would throw away a child repeating its first words ("Monster trucks!")."""
    words = _words(line)
    i = int(max(0.0, min(1.0, fraction)) * len(words))
    return " ".join(words[max(0, i - before): i + after])


def strip_robot(text: str, robot_text: str) -> str:
    """Remove the robot's own words that the mic picked up, keeping the child's.

    Only runs of 2+ words in the robot's order are removed, so a child repeating
    one word the robot said ("dinosaurs!") is kept.
    """
    said = re.findall(r"\S+", text)
    plain = [(_words(w) or [""])[0] for w in said]
    robot = _words(robot_text)
    sm = difflib.SequenceMatcher(a=robot, b=plain, autojunk=False)
    drop = set()
    for block in sm.get_matching_blocks():
        if block.size >= 2:
            drop.update(range(block.b, block.b + block.size))
    return " ".join(w for i, w in enumerate(said) if i not in drop).strip(" ,.")


def match_theme(text: str, prefer_last: bool = False) -> str | None:
    """'I want the dinosaur one!' -> 'dinosaurs'. None if no theme is clearly named.

    prefer_last: when the child talked over the robot, the theme said last is theirs.
    """
    low = text.lower()
    if prefer_last:
        last = {key: max((low.rfind(w) for w in words), default=-1)
                for key, words in THEME_WORDS.items()}
        best = max(last, key=last.get)
        return best if last[best] >= 0 else None
    scores = {key: sum(low.count(w) for w in words) for key, words in THEME_WORDS.items()}
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return None
    if list(scores.values()).count(scores[best]) > 1:
        return None  # a tie: let the nurse decide
    return best

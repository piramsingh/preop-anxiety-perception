"""Runs one thing at a time on the robot: a story step, a reaction, or recovery quiet mode."""

from __future__ import annotations

import logging
import shutil
import threading
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path

from . import sfx, voice
from .content import FLOW_LINES, REACTIONS, STEPS, STEPS_BY_KEY, THEMES, fill
from .robot import Robot

log = logging.getLogger("lullaby.director")

LINE_GAP = 0.35  # seconds of quiet between lines
PARENT_DIR = Path(__file__).resolve().parent.parent / "parent_messages"
PARENT_SLOTS = {
    "1": "Message 1 (e.g. 'I'm right outside')",
    "2": "Message 2 (e.g. 'You were so brave')",
    "3": "Message 3 (e.g. 'See you really soon')",
}


class Busy(Exception):
    pass


@dataclass
class Session:
    kid: str = ""
    age: str = ""
    robot_name: str = ""
    theme: str = ""
    done: list[str] = field(default_factory=list)


class Director:
    def __init__(self, robot: Robot):
        self.robot = robot
        self.session = Session()
        self.activity = "idle"  # idle | talking | recovery
        self.label = ""
        self.line = ""
        self.history: list[str] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.voice_problem: str | None = None
        self.parent_play: dict | None = None
        self._step_key: str | None = None
        self._planned = ""
        self._speaking: tuple[str, float, float] | None = None  # (line, started, seconds)
        self._spoken: list[tuple[str, float, float]] = []  # every line of the current performance
        self.barge_tail = ""  # robot words that may have leaked into the child's answer
        self._warm_lock = threading.Lock()
        self._warming = False
        self._warm_again = False
        PARENT_DIR.mkdir(exist_ok=True)

    # ---- state for the panel ---------------------------------------------
    def state(self) -> dict:
        s = self.session
        return {
            "mode": self.robot.mode,
            "robot_error": self.robot.error,
            "activity": self.activity,
            "label": self.label,
            "line": self.line,
            "session": s.__dict__,
            "steps": [{"key": st.key, "label": st.label, "phase": st.phase, "hint": st.hint,
                       "needs_theme": st.needs_theme,
                       "lines": [t for t, _ in self._lines_for(st.beats) if t]
                       if (s.theme or not st.needs_theme) else []} for st in STEPS],
            "themes": [{"key": t.key, "label": t.label, "emoji": t.emoji} for t in THEMES.values()],
            "reactions": [{"key": k, "label": v[0]} for k, v in REACTIONS.items()],
            "parent": [{"slot": k, "label": v, "recorded": self._parent_path(k).exists()}
                       for k, v in PARENT_SLOTS.items()],
            "parent_playback": self.parent_playback(),
            "history": self.history[-12:],
            "voice": {"engine": voice.engine_label(),
                      "problem": self.voice_problem or voice.status["last_error"]},
        }

    def _note(self, msg: str) -> None:
        self.history.append(f"{time.strftime('%H:%M:%S')}  {msg}")

    # ---- session ----------------------------------------------------------
    def update_session(self, **fields: str) -> None:
        for k, v in fields.items():
            if v is not None and hasattr(self.session, k):
                setattr(self.session, k, v.strip())
        with self._warm_lock:
            self._warm_again = True
            if self._warming:
                return  # the running warm-up will pick up the new details
            self._warming = True
        threading.Thread(target=self._warm_cache, daemon=True).start()

    def _lines_for(self, beats) -> list[tuple[str, str]]:
        s = self.session
        theme = THEMES.get(s.theme)
        return [(fill(t, s.kid, s.robot_name, theme) if t else "", m) for t, m in beats]

    def _warm_cache(self) -> None:
        """Pre-make every line's audio so there is no pause between lines."""
        while True:
            with self._warm_lock:
                if not self._warm_again:
                    self._warming = False
                    return
                self._warm_again = False
            try:
                for st in STEPS:
                    if st.needs_theme and not self.session.theme:
                        continue
                    for beat, (text, _) in enumerate(self._lines_for(st.beats)):
                        if text:
                            wav = voice.tts(text)
                            sfx.with_effect(wav, sfx.effect_for(st.key, beat,
                                                                self.session.theme))
            except Exception as e:  # noqa: BLE001
                log.warning("Could not pre-make audio: %s", e)

    def end_session(self) -> None:
        """Stop, delete the parent's recordings, and clear the child's details."""
        self.stop()
        shutil.rmtree(PARENT_DIR, ignore_errors=True)
        PARENT_DIR.mkdir(exist_ok=True)
        self.session = Session()
        self.history.clear()
        self._note("Session ended; recordings deleted")

    # ---- performances -----------------------------------------------------
    def run_step(self, key: str) -> None:
        st = STEPS_BY_KEY[key]
        if st.needs_theme and not self.session.theme:
            raise ValueError("Pick a story first")
        if key == "got_name" and not self.session.robot_name:
            raise ValueError("Add a nickname first")
        self._start(st.label, self._lines_for(st.beats), step_key=key)

    def react(self, key: str) -> None:
        label, text, motion = REACTIONS[key]
        self._start(label, self._lines_for([(text, motion)]))

    def flow_line(self, key: str) -> None:
        text, motion = FLOW_LINES[key]
        self._start(f"Dr. Juni: {key.replace('_', ' ')}", self._lines_for([(text, motion)]))

    def say(self, text: str) -> None:
        text = text.strip()[:300]
        if not text:
            raise ValueError("Type a line")
        self._start("Custom line", [(text, "nod")])

    def _start(self, label: str, lines, step_key: str | None = None) -> None:
        if self.activity == "talking":
            raise Busy("Robot is talking")
        if self.activity == "recovery":
            self.stop()
        self.parent_play = None  # the robot's own voice replaces a parent message
        self._stop = threading.Event()
        self.activity, self.label = "talking", label
        self._note(f"Start: {label}")
        self._step_key = step_key
        self._spoken = []
        self._planned = " ".join(t for t, _ in lines if t)
        self._thread = threading.Thread(target=self._perform, args=(lines, step_key, self._stop),
                                        daemon=True)
        self._thread.start()

    def _perform(self, lines, step_key, stop: threading.Event) -> None:
        try:
            for beat, (text, motion) in enumerate(lines):
                if stop.is_set():
                    break
                self.line = text
                if not text:
                    self.robot.move(motion, stop)
                    continue
                wav = voice.tts(text)
                # Story lines can carry a soft sound effect mixed under their start.
                wav = sfx.with_effect(wav, sfx.effect_for(step_key, beat, self.session.theme))
                length = voice.duration(wav)
                began = time.monotonic()
                self._speaking = (text, began, length)
                self._spoken.append((text, began, length))
                self.robot.play(wav)
                self.robot.move(motion, stop)
                stop.wait(max(0.0, length - (time.monotonic() - began)) + LINE_GAP)
            if not stop.is_set() and step_key and step_key not in self.session.done:
                self.session.done.append(step_key)
        except Exception as e:
            log.exception("Performance failed")
            self._note(f"Error: {e}")
        finally:
            if not stop.is_set():
                self.robot.move("neutral")
                self.activity, self.label, self.line = "idle", "", ""

    def robot_window(self, back: float, ahead: float = 0.6) -> str:
        """The robot's words spoken between `back` seconds ago and `ahead` seconds from now."""
        now = time.monotonic()
        out = []
        for text, began, length in self._spoken:
            words = text.split()
            if not words or length <= 0:
                continue
            a = max(0.0, (now - back - began) / length)
            b = min(1.0, (now + ahead - began) / length)
            if b > 0 and a < 1 and b > a:
                out.extend(words[int(a * len(words)): max(int(a * len(words)) + 1,
                                                           int(b * len(words) + 0.999))])
        return " ".join(out)

    def barge_in(self) -> None:
        """The child started answering: stop talking right away and look at them."""
        if self.activity != "talking":
            return
        key = self._step_key
        self.barge_tail = ""
        if self._speaking:
            line, started, length = self._speaking
            # Everything the robot said in the last 3.5 s can be in the child's answer audio.
            self.barge_tail = self.robot_window(back=3.5, ahead=0.8)
        self._stop.set()
        self.robot.stop_audio()
        if key and key not in self.session.done:
            self.session.done.append(key)  # the question was asked; the child is answering it
        self._note(f"Child answered during: {self.label}")
        self.activity, self.label, self.line = "idle", "", ""
        threading.Thread(target=self.robot.move, args=("tilt",), daemon=True).start()

    # ---- recovery quiet mode ----------------------------------------------
    def start_recovery(self) -> None:
        self.stop()
        self._stop = threading.Event()
        self.activity, self.label, self.line = "recovery", "Recovery quiet mode", ""
        self._note("Recovery quiet mode on")
        self.robot.set_wobble(False)  # parent's voice should not shake the head
        self._thread = threading.Thread(target=self._recovery_loop, args=(self._stop,), daemon=True)
        self._thread.start()

    def _recovery_loop(self, stop: threading.Event) -> None:
        while not stop.is_set():
            self.robot.move("recovery_in", stop)
            self.robot.move("recovery_out", stop)

    def stop(self) -> None:
        was_recovery = self.activity == "recovery"
        self._stop.set()
        self.robot.stop_audio()
        self.parent_play = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=7)  # a keyframe can take a few seconds to finish
        if was_recovery:
            self.robot.set_wobble(True)
        if self.activity != "idle":
            self._note(f"Stopped: {self.label}")
        self.activity, self.label, self.line = "idle", "", ""
        self.robot.move("neutral")

    # ---- parent messages --------------------------------------------------
    def _parent_path(self, slot: str) -> Path:
        return PARENT_DIR / f"parent_{slot}.wav"

    def save_parent_message(self, slot: str, data: bytes, filename: str) -> None:
        if slot not in PARENT_SLOTS:
            raise ValueError("Unknown message")
        suffix = Path(filename or "rec.webm").suffix or ".webm"
        raw = PARENT_DIR / f"raw_{slot}{suffix}"
        raw.write_bytes(data)
        try:
            voice.to_wav(raw, self._parent_path(slot))
        finally:
            raw.unlink(missing_ok=True)
        if self.parent_play and self.parent_play["slot"] == slot:
            self.stop_parent_message()
        self._note(f"Parent message {slot} saved")

    def parent_path(self, slot: str) -> Path:
        if slot not in PARENT_SLOTS:
            raise ValueError("Unknown message")
        path = self._parent_path(slot)
        if not path.exists():
            raise ValueError("No recording")
        return path

    def _parent_position(self) -> float:
        pp = self.parent_play
        if pp is None:
            return 0.0
        if pp["state"] == "paused":
            return pp["offset"]
        return pp["offset"] + (time.monotonic() - pp["started"])

    def parent_playback(self) -> dict | None:
        """What the robot is doing with a parent message right now, for the panel's player."""
        pp = self.parent_play
        if pp is None:
            return None
        pos = self._parent_position()
        if pp["state"] == "playing" and pos >= pp["duration"]:
            self.parent_play = None  # finished on its own
            return None
        return {"slot": pp["slot"], "state": pp["state"], "position": round(pos, 2),
                "duration": round(pp["duration"], 2)}

    def play_parent_message(self, slot: str) -> None:
        """Start a parent message on the robot, or resume it if it is paused."""
        path = self.parent_path(slot)
        if self.activity == "talking":
            raise Busy("Robot is talking")
        length = voice.duration(path)
        pp = self.parent_play
        offset = pp["offset"] if pp and pp["slot"] == slot and pp["state"] == "paused" else 0.0
        if pp and pp["slot"] == slot and pp["state"] == "playing":
            return  # already playing
        if offset >= length - 0.2:
            offset = 0.0
        # The robot can't pause a sound, so "resume" plays a copy that starts where we paused.
        self.robot.play(path if offset == 0 else self._trimmed(path, slot, offset))
        self.parent_play = {"slot": slot, "state": "playing", "offset": offset,
                            "started": time.monotonic(), "duration": length}
        self._note(f"{'Resumed' if offset else 'Played'} parent message {slot}")

    def pause_parent_message(self) -> None:
        pp = self.parent_play
        if pp is None or pp["state"] != "playing":
            return
        pos = self._parent_position()
        self.robot.stop_audio()
        if pos >= pp["duration"]:
            self.parent_play = None
            return
        pp.update(state="paused", offset=pos)
        self._note(f"Paused parent message {pp['slot']}")

    def stop_parent_message(self) -> None:
        if self.parent_play is not None:
            self.robot.stop_audio()
            self._note(f"Stopped parent message {self.parent_play['slot']}")
        self.parent_play = None

    def _trimmed(self, path: Path, slot: str, offset: float) -> Path:
        with wave.open(str(path), "rb") as src:
            rate = src.getframerate()
            src.setpos(min(int(offset * rate), src.getnframes()))
            frames = src.readframes(src.getnframes())
            params = src.getparams()
        out = PARENT_DIR / f"parent_{slot}_from{int(offset * 1000)}.wav"
        with wave.open(str(out), "wb") as dst:
            dst.setparams(params)
            dst.writeframes(frames)
        return out

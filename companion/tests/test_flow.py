"""Runs the whole flow in preview mode with fast fake speech and motion."""

import string
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lullaby import director as director_mod
from lullaby import robot as robot_mod
from lullaby import voice
from lullaby.content import FLOW_LINES, REACTIONS, STEPS, THEMES, fill
from lullaby.robot import MOTIONS
from lullaby.server import build_app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(voice, "tts", lambda text: Path("fake.wav"))
    monkeypatch.setattr(voice, "duration", lambda path: 0.01)
    monkeypatch.setattr(robot_mod.time, "sleep", lambda s: None)  # motions are instant
    monkeypatch.setattr(robot_mod.Robot, "play", lambda self, wav: None)
    monkeypatch.setattr(director_mod, "PARENT_DIR", tmp_path)
    monkeypatch.setattr(director_mod, "LINE_GAP", 0.0)
    from lullaby import sfx

    monkeypatch.setattr(sfx, "ENABLED", False)  # no ElevenLabs calls from tests

    def fake_wav(src, dst):  # a real 2-second silent WAV
        import wave

        with wave.open(str(dst), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(22050)
            w.writeframes(b"\x00\x00" * 44100)

    monkeypatch.setattr(voice, "to_wav", fake_wav)
    with TestClient(build_app(robot_mod.Robot(preview=True))) as c:
        yield c


def wait_idle(c):
    for _ in range(200):
        s = c.get("/api/state").json()
        if s["activity"] == "idle":
            return s
        time.sleep(0.02)
    raise AssertionError("robot never finished")


def test_every_line_fills_and_every_motion_exists():
    parse = string.Formatter().parse
    fields = {f for st in STEPS for t, _ in st.beats for _, f, _, _ in parse(t) if f}
    assert fields <= {"kid", "robot", "hero", "short", "fun", "place", "picked"}
    for theme in THEMES.values():
        for st in STEPS:
            for text, motion in st.beats:
                assert motion in MOTIONS
                assert "{" not in fill(text, "Maya", "Sparkle", theme)
    for _, text, motion in REACTIONS.values():
        assert motion in MOTIONS
    for text, motion in FLOW_LINES.values():
        assert motion in MOTIONS and "{" not in fill(text, "Maya", "Sparkle", None)


def test_no_scary_promises():
    lines = " ".join(t for st in STEPS for t, _ in st.beats).lower()
    for banned in ["won't hurt", "will not hurt", "needle", "shot", "cut"]:
        assert banned not in lines


def test_full_flow(client):
    assert client.get("/").status_code == 200
    assert client.post("/api/step/chapter1").status_code == 400  # no theme yet
    client.post("/api/session", json={"kid": "Maya", "age": "5"})
    assert client.post("/api/step/got_name").status_code == 400  # no robot name yet
    client.post("/api/session", json={"robot_name": "Sparkle", "theme": "dinosaurs"})
    for key in ["greet", "ask_name", "got_name", "ask_story", "chapter1", "breathing", "promise"]:
        assert client.post(f"/api/step/{key}").status_code == 200, key
        wait_idle(client)

    r = client.post("/api/parent/1", files={"file": ("rec.webm", b"x" * 100, "audio/webm")})
    assert r.json()["parent"][0]["recorded"]
    assert client.post("/api/recovery").json()["activity"] == "recovery"
    assert client.post("/api/parent/1/play").status_code == 200
    assert client.post("/api/step/chapter2").status_code == 200  # leaves recovery by itself
    s = wait_idle(client)
    assert "chapter2" in s["session"]["done"]

    s = client.post("/api/end").json()
    assert s["session"]["kid"] == "" and not s["parent"][0]["recorded"]


def test_busy_robot_refuses_second_line(client, monkeypatch):
    monkeypatch.setattr(voice, "duration", lambda path: 2.0)
    client.post("/api/session", json={"kid": "Leo"})
    assert client.post("/api/step/greet").status_code == 200
    assert client.post("/api/react/great").status_code == 409
    assert client.post("/api/stop").json()["activity"] == "idle"
    assert client.post("/api/react/great").status_code == 200


def test_elevenlabs_wraps_pcm_and_falls_back(monkeypatch, tmp_path):
    import wave

    class FakeTTS:
        def __init__(self, fail=None):
            self.fail = fail

        def convert(self, **kw):
            assert kw["output_format"] == "pcm_22050" and kw["voice_id"] == voice.EL_VOICE
            if self.fail:
                raise RuntimeError(self.fail)
            return iter([b"\x00\x01" * 11025, b"\x00\x01" * 11025])

    class FakeClient:
        def __init__(self, fail=None):
            self.text_to_speech = FakeTTS(fail)

    monkeypatch.setattr(voice, "CACHE", tmp_path)
    monkeypatch.setattr(voice, "EL_KEY", "test-key")
    monkeypatch.setattr(voice, "_el", lambda: FakeClient())
    out = voice.tts("Hello Maya")
    assert out.name.startswith("lullaby_el_")
    with wave.open(str(out)) as w:
        assert w.getframerate() == voice.RATE_HZ and w.getnframes() == 22050
    assert voice.engine_label() == "ElevenLabs"

    # A failing request falls back to the Mac voice instead of going silent.
    monkeypatch.setattr(voice, "_el", lambda: FakeClient(fail="HTTP 429 rate limited"))
    calls = []
    monkeypatch.setattr(voice.subprocess, "run",
                        lambda cmd, check: calls.append(cmd) or Path(cmd[6]).write_bytes(b"x"))
    out = voice.tts("A brand new line")
    assert out.name.startswith("lullaby_say_") and calls
    assert "429" in voice.status["last_error"]


def test_parent_message_play_pause_resume_stop(client, monkeypatch):
    import wave

    def wav_seconds(path):
        with wave.open(str(path)) as w:
            return w.getnframes() / w.getframerate()

    monkeypatch.setattr(voice, "duration", wav_seconds)
    played = []
    monkeypatch.setattr(robot_mod.Robot, "play", lambda self, wav: played.append(Path(wav).name))

    client.post("/api/parent/2", files={"file": ("rec.webm", b"x" * 100, "audio/webm")})
    audio = client.get("/api/parent/2/audio")
    assert audio.status_code == 200 and audio.content[:4] == b"RIFF"
    assert client.get("/api/parent/3/audio").status_code == 404

    s = client.post("/api/parent/2/play").json()
    assert s["parent_playback"]["state"] == "playing" and s["parent_playback"]["duration"] == 2.0
    t0 = time.monotonic()
    while time.monotonic() - t0 < 0.3:  # time.sleep is faked out in these tests
        pass
    s = client.post("/api/parent/pause").json()
    pos = s["parent_playback"]["position"]
    assert s["parent_playback"]["state"] == "paused" and 0.2 < pos < 1.0

    s = client.post("/api/parent/2/play").json()  # resume from where it paused
    assert s["parent_playback"]["state"] == "playing"
    assert played[0] == "parent_2.wav" and played[1].startswith("parent_2_from")
    assert s["parent_playback"]["position"] >= pos

    assert client.post("/api/parent/stop").json()["parent_playback"] is None
    client.post("/api/parent/2/play")
    client.post("/api/session", json={"kid": "Leo"})
    s = client.post("/api/react/great").json()  # the robot talking ends the parent message
    assert s["parent_playback"] is None


def test_nickname_cleanup_and_theme_matching():
    from lullaby.listen import clean_nickname, match_theme

    assert clean_nickname("Um, I wanna call you sparkle!") == "Sparkle"
    assert clean_nickname("Your name is mister wiggles.") == "Mister Wiggles"
    assert clean_nickname("Beepy") == "Beepy"
    assert clean_nickname("okay, how about Sparklew") == "Sparklew"
    assert match_theme("I want the dinosaur one!") == "dinosaurs"
    assert match_theme("Monster trucks!") == "trucks"
    assert match_theme("rockets and space") == "space"
    assert match_theme("a puppy story") == "animals"
    assert match_theme("I don't know") is None


def test_robot_words_are_removed_but_child_words_kept():
    from lullaby.listen import match_theme, strip_robot

    q = "Monster trucks, princesses, dinosaurs, outer space, animals, or superheroes?"
    heard = "Monster trucks, princesses, dinosaurs. Monster trucks!"
    assert strip_robot(heard, q) == "Monster trucks!"
    assert strip_robot("Dinosaurs!", q) == "Dinosaurs!"  # one word the robot also said: keep it
    assert match_theme("dinosaurs outer space monster trucks", prefer_last=True) == "trucks"
    # Interrupted about 40% in: only the words around "dinosaurs, outer space" can leak.
    from lullaby.listen import robot_tail
    tail = robot_tail(q, 0.4)
    assert "monster" not in tail and "dinosaurs" in tail
    assert strip_robot("dinosaurs outer Monster trucks!", tail) == "Monster trucks!"


def test_barge_in_stops_robot_and_counts_the_question(client, monkeypatch):
    monkeypatch.setattr(voice, "duration", lambda path: 2.0)
    client.post("/api/session", json={"kid": "Leo"})
    assert client.post("/api/step/ask_story").json()["activity"] == "talking"
    s = client.post("/api/bargein").json()
    assert s["activity"] == "idle" and "ask_story" in s["session"]["done"]
    assert client.post("/api/bargein").status_code == 200  # nothing to stop: harmless


def test_flow_lines_play(client):
    client.post("/api/session", json={"kid": "Maya"})
    for key in ["again_name", "no_name", "again_story", "tap_story"]:
        assert client.post(f"/api/flow/{key}").status_code == 200, key
        wait_idle(client)
    assert client.post("/api/flow/nope").status_code == 400


def test_sound_effects_map_to_real_story_lines():
    from lullaby import sfx

    # every rule found its line, and every effect is defined
    assert len(sfx.SFX_BY_BEAT) == len(sfx._RULES)
    assert set(sfx.THEME_SFX) == set(THEMES)
    for key in sfx.SFX_BY_BEAT.values():
        assert key == "theme" or key in sfx.EFFECTS
    # the story sound follows the child's theme; quiet mode and parent messages get none
    first = next(i for (s, i), k in sfx.SFX_BY_BEAT.items() if s == "chapter1" and k == "theme")
    assert sfx.effect_for("chapter1", first, "dinosaurs") == "stomp"
    assert sfx.effect_for(None, 0, "dinosaurs") is None
    assert sfx.effect_for("promise", 0, "dinosaurs") is None


def test_sound_effect_mix_falls_back_to_plain_line(monkeypatch, tmp_path):
    from lullaby import sfx

    speech = tmp_path / "line.wav"
    speech.write_bytes(b"RIFF")
    monkeypatch.setattr(sfx, "_effect_file", lambda key: None)  # no key / ElevenLabs down
    assert sfx.with_effect(speech, "stomp") == speech
    assert sfx.with_effect(speech, None) == speech

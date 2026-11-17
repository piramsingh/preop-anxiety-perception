"""Runs the whole flow in preview mode with fast fake speech and motion."""

import shutil
import string
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lullaby import director as director_mod
from lullaby import robot as robot_mod
from lullaby import voice
from lullaby.content import FLOW_LINES, REACTIONS, STEPS, STEPS_BY_KEY, THEMES, fill
from lullaby.robot import MOTIONS
from lullaby.server import build_app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(voice, "tts", lambda text, voice_id=None: Path("fake.wav"))
    monkeypatch.setattr(voice, "tts_line", lambda text, theme="": Path("fake.wav"))
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
    assert fields <= {"kid", "robot", "hero", "short", "fun", "place", "picked", "catch"}
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
    assert match_theme("Princesses!") == "princess"
    assert match_theme("the superhero one") == "heroes"
    assert match_theme("Monster trucks!") is None  # not a story any more
    assert match_theme("I don't know") is None


def test_robot_words_are_removed_but_child_words_kept():
    from lullaby.listen import match_theme, strip_robot

    q = "Do you want to hear a story? You get to pick! Princesses, dinosaurs, or superheroes?"
    heard = "You get to pick! Princesses, dinosaurs. Superheroes!"
    assert strip_robot(heard, q) == "Superheroes!"
    assert strip_robot("Dinosaurs!", q) == "Dinosaurs!"  # one word the robot also said: keep it
    assert match_theme("princesses dinosaurs superheroes", prefer_last=True) == "heroes"
    # Interrupted near the end: only the words around "princesses, dinosaurs" can leak.
    from lullaby.listen import robot_tail
    tail = robot_tail(q, 0.8)
    assert "want" not in tail and "dinosaurs" in tail
    assert strip_robot("princesses dinosaurs Superheroes!", tail) == "Superheroes!"


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
    from lullaby.content import STEPS

    # every rule found its line, and every sound it names exists
    for step, snippet, what in sfx._RULES:
        st = next(s for s in STEPS if s.key == step)
        assert any(snippet in text for text, _ in st.beats), (step, snippet)
        key = what.lstrip("~").split("@")[0]
        if what.startswith("bed:"):
            assert what[4:] == "world" or f"bed_{what[4:]}" in sfx.BEDS
        else:
            assert key in ("theme", "theme2") or key in sfx.EFFECTS, what
    # every theme has its two story sounds and its own world ambience
    assert set(sfx.THEME_SFX) == set(sfx.THEME_SFX2) == set(THEMES)
    for t in THEMES:
        assert f"bed_{t}" in sfx.BEDS
        assert {sfx.THEME_SFX[t], sfx.THEME_SFX2[t]} <= set(sfx.EFFECTS)

    # the story sounds follow the child's theme
    first = next(i for (s, i), w in sfx.SFX_BY_BEAT.items() if s == "chapter1" and "theme" in w)
    assert sfx.cue_for("chapter1", first, "dinosaurs").start.key == "stomp"
    once = next(i for i, (t, _) in enumerate(STEPS_BY_KEY["chapter1"].beats) if "Once upon" in t)
    cue = sfx.cue_for("chapter1", once, "dinosaurs")
    assert cue.start.key == "once" and cue.bed == "bed_dinosaurs"
    assert sfx.cue_for("chapter1", once, "heroes").start.key == "hero_sting"  # its own sting
    peek = next(i for i, (t, _) in enumerate(STEPS_BY_KEY["chapter1"].beats) if "Peekaboo" in t)
    assert sfx.cue_for("chapter1", peek, "princess").end.key == "boing"

    # no sound outside the stories: quick lines, the goodbye, quiet mode, parent messages
    assert not sfx.cue_for(None, 0, "dinosaurs")
    for st in STEPS:
        if st.key in ("greet", "ask_name", "ask_story", "mask", "promise"):
            for i in range(len(st.beats)):
                assert not sfx.cue_for(st.key, i, "dinosaurs"), st.key


def _tone(path, seconds, amp, hz=440.0):
    import wave

    import numpy as np

    t = np.arange(int(22050 * seconds)) / 22050
    data = (amp * 32767 * np.sin(2 * np.pi * hz * t)).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(data.tobytes())


def test_sound_effect_mix_falls_back_to_plain_line(monkeypatch, tmp_path):
    from lullaby import sfx

    speech = tmp_path / "line.wav"
    speech.write_bytes(b"RIFF")
    monkeypatch.setattr(sfx, "_effect_file", lambda key: None)  # no key / ElevenLabs down
    assert sfx.with_effect(speech, sfx.Cue(sfx.Spot("stomp"), bed="bed_heroes")) == speech
    assert sfx.with_effect(speech, sfx.Cue()) == speech
    assert sfx.with_effect(speech, None) == speech


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_sounds_are_never_louder_than_the_voice(monkeypatch, tmp_path):
    """Even a full-blast effect and bed end up well under the voice, and the mix never
    peaks above the voice alone."""
    import wave

    import numpy as np

    from lullaby import sfx

    monkeypatch.setattr(voice, "CACHE", tmp_path)
    speech, loud_fx, loud_bed = tmp_path / "v.wav", tmp_path / "fx.wav", tmp_path / "bed.wav"
    _tone(speech, 3.0, 0.3)
    _tone(loud_fx, 1.5, 0.99, hz=1000)
    _tone(loud_bed, 2.0, 0.99, hz=300)  # shorter than the line, so it has to loop
    files = {"stomp": loud_fx, "boing": loud_fx, "bed_heroes": loud_bed}
    monkeypatch.setattr(sfx, "_effect_file", lambda key: files[key])

    out = sfx.with_effect(speech, sfx.Cue(sfx.Spot("stomp"), sfx.Spot("boing", at_end=True),
                                          "bed_heroes"))
    assert out != speech
    with wave.open(str(out)) as w:
        mix = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2") / 32768
    assert np.abs(mix).max() <= 0.3 * 1.02  # the voice's own peak, plus rounding
    assert len(mix) / 22050 > 3.0  # the effects lead in / ring out around the voice
    # the effect alone (before the voice comes in) sits at about a quarter of the voice
    lead = mix[: int(22050 * 0.4)]
    assert 0.3 * 0.15 < np.abs(lead).max() <= 0.3 * sfx.SPOT_PEAK * 1.02


def test_characters_speak_in_their_own_voices(monkeypatch, tmp_path):
    """Tagged words go to the character's voice; the panel and listening see plain words."""
    import wave

    from lullaby.content import CHARACTER_VOICES, plain, segments

    line = fill("{short} said, <hero>I feel a little sore.</hero>", "Sam", "Juni", THEMES["heroes"])
    assert segments(line) == [(None, "Captain Brave said,"), ("hero", "I feel a little sore.")]
    assert plain(line) == "Captain Brave said, I feel a little sore."
    for st in STEPS:  # every tag in the script is closed and known
        for text, _ in st.beats:
            assert "<" not in plain(fill(text, "Sam", "Juni", THEMES["heroes"]))

    calls = []

    def fake_tts(text, voice_id=None):
        calls.append((text, voice_id))
        out = tmp_path / f"{len(calls)}.wav"
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(22050)
            w.writeframes(b"\x01\x00" * 2205)
        return out

    monkeypatch.setattr(voice, "EL_KEY", "test")
    monkeypatch.setattr(voice, "CACHE", tmp_path)
    monkeypatch.setattr(voice, "tts", fake_tts)
    out = voice.tts_line(line, "heroes")
    assert calls == [("Captain Brave said,", None),
                     ("I feel a little sore.", CHARACTER_VOICES["hero:heroes"])]
    assert voice.duration(out) > 0.2  # both pieces plus the pause between them

    calls.clear()  # a theme without a hero voice reads the hero's words as Dr. Juni
    monkeypatch.delitem(CHARACTER_VOICES, "hero:princess", raising=False)
    voice.tts_line(fill("<hero>{catch}</hero>", "Sam", "Juni", THEMES["princess"]), "princess")
    assert calls == [("Twirl, twirl, twirl! What a beautiful day!", None)]


def test_intro_runs_by_itself_and_listens_for_answers(client, monkeypatch):
    """The intro asks, listens on the robot, fills in the answers, and stops before the
    steps that need the nurse (mask practice, goodbye)."""
    answers = {"nickname": "Sparky", "story": "dinosaurs"}
    heard = []

    def fake_listen(self, purpose):
        heard.append(purpose)
        result = answers[purpose]
        if purpose == "nickname":
            self.session.robot_name = result
        else:
            self.session.theme = result
        return {"purpose": purpose, "text": result, "result": result}

    monkeypatch.setattr(director_mod.Director, "listen_on_robot", fake_listen)
    client.post("/api/session", json={"kid": "Sam"})
    assert client.post("/api/intro").status_code == 200
    deadline = time.time() + 10
    while client.get("/api/state").json()["auto"] and time.time() < deadline:
        time.sleep(0.05)
    s = client.get("/api/state").json()
    assert s["auto"] is None
    assert heard == ["nickname", "story"]
    assert s["session"]["robot_name"] == "Sparky" and s["session"]["theme"] == "dinosaurs"
    assert s["session"]["done"] == ["greet", "ask_name", "got_name", "ask_story", "chapter1",
                                    "breathing"]


def test_stop_ends_the_intro(client, monkeypatch):
    def slow_listen(self, purpose):
        self._auto_stop.wait(5)  # like a child who never answers, until Stop
        return {}

    monkeypatch.setattr(director_mod.Director, "listen_on_robot", slow_listen)
    client.post("/api/session", json={"kid": "Sam"})
    client.post("/api/intro")
    time.sleep(0.3)
    assert client.get("/api/state").json()["auto"] == "intro"
    client.post("/api/stop")
    deadline = time.time() + 3
    while client.get("/api/state").json()["auto"] and time.time() < deadline:
        time.sleep(0.05)
    s = client.get("/api/state").json()
    assert s["auto"] is None and "chapter1" not in s["session"]["done"]


def test_intro_continues_where_the_visit_is(client, monkeypatch):
    """Steps already done and answers already given are skipped; no name is needed."""
    heard = []

    def fake_listen(self, purpose):
        heard.append(purpose)
        self.session.theme = "heroes"
        return {"purpose": purpose, "text": "heroes", "result": "heroes"}

    monkeypatch.setattr(director_mod.Director, "listen_on_robot", fake_listen)
    client.post("/api/step/greet")
    wait_idle(client)
    client.post("/api/session", json={"robot_name": "Sparky"})
    assert client.post("/api/intro").status_code == 200  # no child's name, still runs
    deadline = time.time() + 10
    while client.get("/api/state").json()["auto"] and time.time() < deadline:
        time.sleep(0.05)
    s = client.get("/api/state").json()
    assert heard == ["story"]  # nickname was already given
    assert s["session"]["robot_name"] == "Sparky"
    assert s["session"]["done"] == ["greet", "got_name", "ask_story", "chapter1", "breathing"]


def test_start_over_runs_the_intro_from_hello(client, monkeypatch):
    def fake_listen(self, purpose):
        result = "Sparky" if purpose == "nickname" else "princess"
        if purpose == "nickname":
            self.session.robot_name = result
        else:
            self.session.theme = result
        return {"purpose": purpose, "text": result, "result": result}

    monkeypatch.setattr(director_mod.Director, "listen_on_robot", fake_listen)
    client.post("/api/session", json={"kid": "Sam", "robot_name": "Old", "theme": "heroes"})
    client.post("/api/step/chapter1")
    wait_idle(client)
    assert client.post("/api/intro?restart=true").status_code == 200
    deadline = time.time() + 10
    while client.get("/api/state").json()["auto"] and time.time() < deadline:
        time.sleep(0.05)
    s = client.get("/api/state").json()["session"]
    assert s["kid"] == "Sam"  # kept
    assert s["robot_name"] == "Sparky" and s["theme"] == "princess"  # asked again
    assert s["done"][0] == "greet" and s["done"][-1] == "breathing"

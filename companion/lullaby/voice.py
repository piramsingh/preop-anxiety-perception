"""Text-to-speech, cached as WAV files, plus audio conversion.

Voice engines:
  * ElevenLabs - used when ELEVENLABS_API_KEY is set (in the environment or companion/.env)
  * macOS `say` - always available offline; used as the fallback if ElevenLabs fails

Every line is cached by (engine, voice, settings, text), so each line is only
generated once. Lines without the child's name are shared across children.
"""

import hashlib
import logging
import os
import shutil
import subprocess
import threading
import wave
from pathlib import Path

from dotenv import load_dotenv
from elevenlabs import ElevenLabs, VoiceSettings
from elevenlabs.core.api_error import ApiError

log = logging.getLogger("lullaby.voice")

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "audio_cache"


load_dotenv(ROOT / ".env")  # puts ELEVENLABS_API_KEY etc. in the environment; never in code

# macOS voice (fallback)
SAY_VOICE = os.environ.get("LULLABY_VOICE", "Samantha")
SAY_RATE = os.environ.get("LULLABY_RATE", "160")  # words per minute; slower is calmer

# ElevenLabs
EL_KEY = os.environ.get("ELEVENLABS_API_KEY", "").strip()
EL_VOICE = os.environ.get("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")  # premade "George"
EL_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_v4")
EL_SPEED = float(os.environ.get("ELEVENLABS_SPEED", "0.9"))  # only used by v2/v3 models
_client: ElevenLabs | None = None


def _el() -> ElevenLabs:
    global _client
    if _client is None:
        # The key comes from .env via the environment. Pass it explicitly: the SDK reads the
        # environment when it is imported, which happens before load_dotenv runs.
        _client = ElevenLabs(api_key=EL_KEY)
    return _client


RATE_HZ = 22050  # ElevenLabs sends raw 16-bit PCM at this rate; we wrap it as WAV

status = {"engine": "elevenlabs" if EL_KEY else "mac", "last_error": None}


def engine_label() -> str:
    return "ElevenLabs" if status["engine"] == "elevenlabs" else "Mac voice"


def tts_line(text: str, theme: str = "") -> Path:
    """A whole script line as one WAV: Dr. Juni narrates, and words in <hero>/<helper> tags are
    spoken in that character's voice (CHARACTER_VOICES), joined with short natural pauses."""
    from .content import CHARACTER_VOICES, plain, segments

    segs = segments(text)
    if not EL_KEY or len(segs) <= 1 and (not segs or segs[0][0] is None):
        return tts(plain(text))
    parts = []
    for speaker, words in segs:
        vid = None
        if speaker == "helper":
            vid = CHARACTER_VOICES.get("helper")
        elif speaker == "hero":
            vid = CHARACTER_VOICES.get(f"hero:{theme}")
        part = tts(words, vid)
        parts.append(_leveled(part) if speaker else part)
    if len(parts) == 1:
        return parts[0]
    out = CACHE / ("line_" + hashlib.sha1("|".join(p.name for p in parts).encode()).hexdigest()[:16]
                   + ".wav")
    if out.exists():
        return out
    gap = b"\x00\x00" * int(RATE_HZ * 0.18)
    tmp = _tmp(out)
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE_HZ)
        for i, part in enumerate(parts):
            with wave.open(str(part), "rb") as r:
                if r.getframerate() != RATE_HZ or r.getnchannels() != 1:
                    raise RuntimeError(f"unexpected audio format in {part.name}")
                w.writeframes((gap if i else b"") + r.readframes(r.getnframes()))
    tmp.replace(out)
    return out


CHARACTER_RMS_DB = -16.0  # Dr. Juni's speaking level; every character is matched to it


def _leveled(path: Path) -> Path:
    """A character's line at Dr. Juni's loudness, so no voice is much quieter or louder than
    the narrator. Peaks stay under -1 dB."""
    import numpy as np

    out = path.with_name(f"lvl_{path.stem}.wav")
    if out.exists():
        return out
    with wave.open(str(path), "rb") as r:
        params = r.getparams()
        data = np.frombuffer(r.readframes(r.getnframes()), dtype="<i2").astype(np.float32) / 32768
    if not len(data):
        return path
    frames = data[: len(data) // 512 * 512].reshape(-1, 512)
    frame_rms = np.sqrt((frames ** 2).mean(axis=1)) if len(frames) else np.array([0.0])
    peak = float(np.abs(data).max())
    loud = frame_rms[frame_rms > max(peak * 0.05, 1e-4)]
    rms = float(np.sqrt((loud ** 2).mean())) if len(loud) else 0.0
    if rms <= 0:
        return path
    gain = min(10 ** (CHARACTER_RMS_DB / 20) / rms, 10 ** (-1 / 20) / peak)
    tmp = _tmp(out)
    with wave.open(str(tmp), "wb") as w:
        w.setparams(params)
        w.writeframes(np.clip(data * gain * 32768, -32768, 32767).astype("<i2").tobytes())
    tmp.replace(out)
    return out


def tts(text: str, voice_id: str | None = None) -> Path:
    """Return a WAV file of `text` spoken in a calm voice (cached). `voice_id` picks another
    ElevenLabs voice (a story character); the default is Dr. Juni."""
    CACHE.mkdir(parents=True, exist_ok=True)
    if EL_KEY:
        vid = voice_id or EL_VOICE
        out = _cached("el", f"{vid}|{EL_MODEL}|{_voice_settings().model_dump_json()}", text)
        if out.exists():
            return out
        try:
            _elevenlabs(text, out, vid)
            status["engine"], status["last_error"] = "elevenlabs", None
            return out
        except Exception as e:  # noqa: BLE001 - never leave the child waiting in silence
            status["engine"], status["last_error"] = "mac", f"ElevenLabs failed: {e}"
            log.warning("ElevenLabs failed, using the Mac voice for this line: %s", e)
    out = _cached("say", f"{SAY_VOICE}|{SAY_RATE}", text)
    if not out.exists():
        tmp = _tmp(out)
        subprocess.run(
            ["say", "-v", SAY_VOICE, "-r", SAY_RATE, "-o", str(tmp),
             f"--data-format=LEI16@{RATE_HZ}", text],
            check=True,
        )
        tmp.replace(out)
    return out


def _cached(engine: str, settings: str, text: str) -> Path:
    digest = hashlib.sha1(f"{engine}|{settings}|{text}".encode()).hexdigest()[:16]
    return CACHE / f"lullaby_{engine}_{digest}.wav"


def _tmp(out: Path) -> Path:
    return out.with_name(f"{out.stem}.{os.getpid()}.{threading.get_ident()}.tmp.wav")


def _voice_settings() -> VoiceSettings:
    # Steady and calm for a scared child. Eleven v4 only takes stability + similarity;
    # older models also take style and speed.
    if EL_MODEL.startswith("eleven_v4"):
        return VoiceSettings(stability=0.6, similarity_boost=0.75)
    return VoiceSettings(stability=0.6, similarity_boost=0.75, style=0.15,
                         use_speaker_boost=True, speed=EL_SPEED)


def _elevenlabs(text: str, out: Path, voice_id: str | None = None) -> None:
    audio = _el().text_to_speech.convert(
        voice_id=voice_id or EL_VOICE,
        text=text,
        model_id=EL_MODEL,
        output_format=f"pcm_{RATE_HZ}",
        voice_settings=_voice_settings(),
    )
    pcm = b"".join(audio)
    if len(pcm) < 1000:
        raise RuntimeError("ElevenLabs returned almost no audio")
    tmp = _tmp(out)
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE_HZ)
        w.writeframes(pcm[: len(pcm) // 2 * 2])
    tmp.replace(out)


def check_elevenlabs() -> str | None:
    """Quick key + voice check at startup. Returns a problem to show, or None if all is well."""
    if not EL_KEY:
        return None
    try:
        _el().voices.get(EL_VOICE)
        return None
    except ApiError as e:
        status["engine"] = "mac"
        if e.status_code == 401:
            return "ElevenLabs key rejected"
        if e.status_code in (400, 404):
            return "ElevenLabs voice not found"
        return f"ElevenLabs error {e.status_code} · using Mac voice"
    except Exception:  # noqa: BLE001 - offline, DNS, timeouts
        status["engine"] = "mac"
        return "ElevenLabs offline · using Mac voice"


def duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def to_wav(src: Path, dst: Path) -> None:
    """Convert any recording (webm, m4a, mp3...) to 22 kHz mono PCM16 WAV."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("Converting recordings needs ffmpeg: brew install ffmpeg")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", "22050",
         "-sample_fmt", "s16", str(dst)],
        check=True,
    )

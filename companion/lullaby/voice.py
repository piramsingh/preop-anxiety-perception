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


def tts(text: str) -> Path:
    """Return a WAV file of `text` spoken in a calm voice (cached)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    if EL_KEY:
        out = _cached("el", f"{EL_VOICE}|{EL_MODEL}|{_voice_settings().model_dump_json()}", text)
        if out.exists():
            return out
        try:
            _elevenlabs(text, out)
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


def _elevenlabs(text: str, out: Path) -> None:
    audio = _el().text_to_speech.convert(
        voice_id=EL_VOICE,
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

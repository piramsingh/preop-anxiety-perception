"""Nurse control panel: a local web page that drives the robot.

Run:  uv run lullaby                 (finds the robot on the network or USB)
      uv run lullaby --preview       (no robot: sound plays on the laptop)
Then open http://127.0.0.1:8890
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import listen, voice
from .director import Busy, Director
from .robot import Robot

STATIC = Path(__file__).resolve().parent / "static"


class SessionIn(BaseModel):
    kid: str | None = None
    age: str | None = None
    robot_name: str | None = None
    theme: str | None = None


class SayIn(BaseModel):
    text: str


def build_app(robot: Robot) -> FastAPI:
    director = Director(robot)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        robot.connect()
        director.voice_problem = voice.check_elevenlabs()
        listen.warm_up()
        print(f"  Voice: {voice.engine_label()}"
              + (f"  ({director.voice_problem})" if director.voice_problem else ""))
        yield
        director.stop()
        robot.close()

    app = FastAPI(title="Lullaby companion", lifespan=lifespan)

    def guard(fn, *a):
        try:
            fn(*a)
        except Busy as e:
            raise HTTPException(409, str(e)) from e
        except (ValueError, KeyError, RuntimeError) as e:
            raise HTTPException(400, str(e)) from e
        return director.state()

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/state")
    def state():
        return director.state()

    @app.post("/api/session")
    def session(body: SessionIn):
        return guard(lambda: director.update_session(**body.model_dump()))

    @app.post("/api/step/{key}")
    def step(key: str):
        return guard(director.run_step, key)

    @app.post("/api/react/{key}")
    def react(key: str):
        return guard(director.react, key)

    @app.post("/api/flow/{key}")
    def flow(key: str):
        return guard(director.flow_line, key)

    @app.post("/api/say")
    def say(body: SayIn):
        return guard(director.say, body.text)

    @app.post("/api/stop")
    def stop():
        return guard(director.stop)

    @app.post("/api/recovery")
    def recovery():
        return guard(director.start_recovery)

    @app.post("/api/parent/pause")
    def pause_parent():
        return guard(director.pause_parent_message)

    @app.post("/api/parent/stop")
    def stop_parent():
        return guard(director.stop_parent_message)

    @app.post("/api/parent/{slot}")
    async def upload_parent(slot: str, file: UploadFile = File(...)):
        data = await file.read()
        if len(data) > 20_000_000:
            raise HTTPException(400, "Recording is too long.")
        return guard(director.save_parent_message, slot, data, file.filename or "")

    @app.post("/api/parent/{slot}/play")
    def play_parent(slot: str):
        return guard(director.play_parent_message, slot)

    @app.get("/api/parent/{slot}/audio")
    def parent_audio(slot: str):
        """The recording itself, so the parent can listen back in the browser."""
        try:
            path = director.parent_path(slot)
        except ValueError as e:
            raise HTTPException(404, str(e)) from e
        return FileResponse(path, media_type="audio/wav",
                            headers={"Cache-Control": "no-store"})

    @app.post("/api/bargein")
    def barge_in():
        """The child started answering while the robot was still asking."""
        return guard(director.barge_in)

    @app.post("/api/listen/peek")
    async def listen_peek(purpose: str, file: UploadFile = File(...)):
        """While the robot asks: is the child already answering? Decided by words, not volume."""
        if director.activity != "talking":
            return {"barge": False, "text": "", "talking": False}
        data = await file.read()
        try:
            out = await asyncio.to_thread(listen.peek, data, file.filename or "", purpose,
                                          director.robot_window(back=3.5), director._planned)
        except Exception as e:  # noqa: BLE001 - a failed peek just means "keep waiting"
            return {"barge": False, "text": "", "error": str(e)}
        if out.get("barge"):
            logging.getLogger("lullaby.listen").info("Barge-in heard: %r", out.get("text"))
        return out

    @app.post("/api/listen")
    async def listen_answer(purpose: str, file: UploadFile = File(...), start: float = 0.0,
                            step: str = "", barged: bool = False):
        """Transcribe the child's spoken answer on this laptop (offline Whisper)."""
        if purpose not in ("nickname", "story"):
            raise HTTPException(400, "Unknown purpose.")
        data = await file.read()
        if len(data) > 5_000_000:
            raise HTTPException(400, "Answer is too long.")
        try:
            text = await asyncio.to_thread(listen.transcribe, data, file.filename or "", purpose,
                                           start, director.barge_tail if barged else "")
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, f"Couldn't understand the recording ({e}).") from e
        out = {"text": text}
        if purpose == "nickname":
            out["nickname"] = listen.clean_nickname(text)
        else:
            out["theme"] = listen.match_theme(text, prefer_last=barged)
        return out

    @app.post("/api/reconnect")
    def reconnect():
        director.stop()
        robot.close()
        robot.connect()
        return director.state()

    @app.post("/api/end")
    def end():
        return guard(director.end_session)

    return app


def main() -> None:
    p = argparse.ArgumentParser(description="Lullaby surgery companion for Reachy Mini")
    p.add_argument("--host", default="reachy-mini.local", help="robot hostname or IP")
    p.add_argument("--preview", action="store_true", help="run without a robot")
    p.add_argument("--port", type=int, default=8890)
    p.add_argument("--lan", action="store_true",
                   help="let a tablet on the same wifi open the panel (recording needs localhost)")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    app = build_app(Robot(host=a.host, preview=a.preview))
    print(f"\n  Nurse panel: http://127.0.0.1:{a.port}\n")
    uvicorn.run(app, host="0.0.0.0" if a.lan else "127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()

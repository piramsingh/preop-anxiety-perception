"""Local web dashboard. It only listens on this computer and refuses requests from other sites,
because a website could otherwise reach a local server and turn on the camera."""

import argparse
import asyncio
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from preop.config import load_config
from preop.dashboard.session import SessionBusy, SessionManager, encode_frame
from preop.sources.webcam import SourceUnavailable, WebcamSource

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
LOCAL_NAMES = {"127.0.0.1", "localhost"}
FRAME_INTERVAL_S = 1 / 12
STATIC = Path(__file__).parent / "static"


class LocalOnly:
    """Blocks other websites (Origin) and DNS rebinding (Host), for HTTP and WebSockets alike."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] in ("http", "websocket"):
            headers = {key.decode(): value.decode() for key, value in scope["headers"]}
            host, origin = headers.get("host", ""), headers.get("origin")
            allowed = urlsplit(f"//{host}").hostname in LOCAL_NAMES and (
                origin is None or urlsplit(origin).netloc == host
            )
            if not allowed:
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                else:
                    await send(
                        {"type": "http.response.start", "status": 403, "headers": []},
                    )
                    await send({"type": "http.response.body", "body": b"Local use only"})
                return
        await self.app(scope, receive, send)


class StartRequest(BaseModel):
    source: Literal["camera", "file"]
    path: str | None = None
    baseline_s: float = Field(default=60.0, ge=10.0, le=600.0)


def create_app(manager: SessionManager, default_video: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        manager.stop()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(LocalOnly)

    @app.get("/api/defaults")
    async def defaults() -> dict:
        return {
            "video": default_video,
            "baseline_s": manager.base_config.score.baseline_s,
        }

    @app.post("/api/session")
    async def start(request: StartRequest) -> dict:
        if manager.active:
            raise HTTPException(409, "A session is already running.")
        camera = None
        if request.source == "file":
            if not request.path or not Path(request.path).expanduser().is_file():
                raise HTTPException(400, "That video file wasn't found. Check the path.")
        config = manager.config_for(request.source, request.path, request.baseline_s)
        if request.source == "camera":
            # Handlers run on the main thread, which macOS needs for its permission prompt.
            camera = WebcamSource(config.video.camera_index)
            try:
                camera.open()
            except SourceUnavailable as error:
                raise HTTPException(400, str(error)) from error
        settings = {
            "source": request.source,
            "name": Path(request.path).name if request.path else None,
            "baseline_s": request.baseline_s,
        }
        try:
            manager.start(config, settings, camera)
        except SessionBusy as error:
            raise HTTPException(409, "A session is already running.") from error
        return {"status": manager.status}

    @app.post("/api/session/stop")
    async def stop() -> dict:
        manager.stop()
        return {"status": manager.status}

    @app.websocket("/ws")
    async def updates(socket: WebSocket) -> None:
        await socket.accept()
        listener = manager.subscribe(asyncio.get_running_loop())
        try:
            await socket.send_json(manager.snapshot())
            while True:
                await socket.send_json(await listener[1].get())
        except WebSocketDisconnect:
            pass
        finally:
            manager.unsubscribe(listener)

    async def frames():
        last_t = None
        while manager.active:
            pipeline = manager.pipeline
            image, people, t = pipeline.latest_frame() if pipeline else (None, [], None)
            if image is not None and t != last_t:
                last_t = t
                jpeg = await asyncio.to_thread(encode_frame, image, people)
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            await asyncio.sleep(FRAME_INTERVAL_S)

    @app.get("/video.mjpeg")
    async def video() -> StreamingResponse:
        return StreamingResponse(
            frames(),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-store"},
        )

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="preop-dashboard", description=__doc__)
    parser.add_argument("--config", type=Path, default=None, help="YAML config (default: built-in)")
    parser.add_argument("--video-file", type=Path, help="Fill in this video on the start screen")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-open", action="store_true", help="Do not open the browser")
    args = parser.parse_args(argv)

    default_video = str(args.video_file.expanduser().resolve()) if args.video_file else None
    app = create_app(SessionManager(load_config(args.config)), default_video)
    url = f"http://{HOST}:{args.port}"
    print(f"Lullaby dashboard: {url}  (this computer only, nothing is saved). Ctrl-C to stop.")
    if not args.no_open:
        threading.Timer(1.0, webbrowser.open, [url]).start()
    uvicorn.run(app, host=HOST, port=args.port, log_level="warning", timeout_graceful_shutdown=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

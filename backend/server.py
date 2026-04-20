import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict

import websockets
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaPlayer, MediaRelay
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=False)

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("webrtc-4cams")


def _install_asyncio_exception_handler() -> None:
    loop = asyncio.get_event_loop()
    original = loop.default_exception_handler

    def _handler(loop: asyncio.AbstractEventLoop, ctx: dict) -> None:
        exc = ctx.get("exception")
        source = ctx.get("source_traceback") or []
        source_str = "".join(str(frame) for frame in source)
        if isinstance(exc, asyncio.InvalidStateError) and "stun.py" in source_str:
            return
        original(ctx)

    loop.set_exception_handler(_handler)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


SIGNALING_HOST = os.environ.get("SIGNALING_HOST", "0.0.0.0")
SIGNALING_PORT = _env_int("SIGNALING_PORT", 8765)

DEFAULT_CAMERAS = [
    "rtsp://user:pass@192.168.1.10:554/stream1",
    "rtsp://user:pass@192.168.1.11:554/stream1",
    "rtsp://user:pass@192.168.1.12:554/stream1",
    "rtsp://user:pass@192.168.1.13:554/stream1",
]


def load_camera_sources() -> list[str]:
    cams: list[str] = []
    for i in range(4):
        v = os.environ.get(f"CAMERA_{i}")
        if isinstance(v, str) and v.strip():
            # Strip inline comments (e.g. "rtsp://... # Wisenet")
            cams.append(v.strip().split(" #")[0].strip())

    if cams:
        return cams

    raw = os.environ.get("CAMERA_SOURCES")
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list) and all(isinstance(x, str) for x in data):
                data2 = [x.strip() for x in data if x.strip()]
                if data2:
                    return data2
        except Exception:
            pass

    return DEFAULT_CAMERAS


# FFmpeg options for low-latency RTSP — passed directly to MediaPlayer
RTSP_OPTIONS = {
    "rtsp_transport": "tcp",       # TCP — надёжнее UDP на LAN
    "fflags": "nobuffer",          # без буфера
    "flags": "low_delay",          # режим минимальной задержки
    "max_delay": "0",              # нет дополнительного буфера
    "reorder_queue_size": "0",     # не ждать переупорядочивания пакетов
    "analyzeduration": "0",        # не анализировать поток долго при старте
    "probesize": "32768",          # минимальный размер зонда
}


class App:
    def __init__(self, sources: list[str]):
        self.relay = MediaRelay()
        self.players: list[MediaPlayer] = []
        self.tracks = []

        for src in sources:
            logger.info("Opening camera: %s", src)
            opts = RTSP_OPTIONS.copy() if src.startswith("rtsp://") else {}
            player = MediaPlayer(src, options=opts)
            self.players.append(player)
            if player.video:
                self.tracks.append(player.video)
                logger.info("Video track ready for: %s", src)
            else:
                logger.warning("No video track for: %s", src)
                self.tracks.append(None)

    def get_track(self, camera_index: int):
        if camera_index < 0 or camera_index >= len(self.tracks):
            raise ValueError("cameraIndex out of range")
        track = self.tracks[camera_index]
        if track is None:
            raise ValueError(f"No video track for camera {camera_index}")
        return self.relay.subscribe(track)

    def shutdown(self):
        for player in self.players:
            try:
                player._MediaPlayer__thread_quit.set()
            except Exception:
                pass


class SignalingError(Exception):
    pass


def _json_dumps(msg: Dict[str, Any]) -> str:
    return json.dumps(msg, separators=(",", ":"))


async def _send(ws, msg: Dict[str, Any]) -> None:
    try:
        await ws.send(_json_dumps(msg))
    except websockets.exceptions.ConnectionClosed:
        pass


async def handle_client(ws, app: App, num_cameras: int):
    client_id = str(uuid.uuid4())
    pcs: dict[str, RTCPeerConnection] = {}

    logger.info("client connected id=%s cameras=%d", client_id, num_cameras)
    await _send(ws, {"type": "hello", "clientId": client_id, "cameras": num_cameras})

    async def close_all():
        for pc in list(pcs.values()):
            try:
                await pc.close()
            except Exception:
                pass
        pcs.clear()
        logger.info("client closed id=%s", client_id)

    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
                if not isinstance(msg, dict):
                    raise SignalingError("Message must be a JSON object")
                mtype = msg.get("type")

                if mtype == "offer":
                    camera_index = int(msg.get("cameraIndex", -1))
                    sdp = msg.get("sdp", "")
                    offer_type = msg.get("sdpType", "offer")
                    logger.info("offer client=%s cam=%d", client_id, camera_index)

                    pc_key = f"cam{camera_index}"
                    if pc_key in pcs:
                        await pcs[pc_key].close()
                        del pcs[pc_key]

                    pc = RTCPeerConnection()
                    pcs[pc_key] = pc

                    @pc.on("iceconnectionstatechange")
                    async def on_ice():
                        if pc.iceConnectionState in ("failed", "closed", "disconnected"):
                            await pc.close()
                            pcs.pop(pc_key, None)

                    await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=offer_type))

                    track = app.get_track(camera_index)
                    pc.addTrack(track)

                    answer = await pc.createAnswer()
                    await pc.setLocalDescription(answer)

                    await _send(ws, {
                        "type": "answer",
                        "cameraIndex": camera_index,
                        "sdp": pc.localDescription.sdp,
                        "sdpType": pc.localDescription.type,
                    })

                elif mtype == "ice":
                    await _send(ws, {"type": "ice-ack"})

                elif mtype == "close":
                    await close_all()
                    await _send(ws, {"type": "closed"})

                else:
                    raise SignalingError(f"Unknown message type: {mtype}")

            except SignalingError as e:
                logger.warning("signaling error client=%s err=%s", client_id, e)
                await _send(ws, {"type": "error", "message": str(e)})
            except Exception as e:
                logger.exception("server error client=%s", client_id)
                await _send(ws, {"type": "error", "message": f"Server error: {e.__class__.__name__}"})
    finally:
        await close_all()


async def main():
    _install_asyncio_exception_handler()
    sources = load_camera_sources()
    app = App(sources)

    logger.info("Signaling WS on ws://%s:%s", SIGNALING_HOST, SIGNALING_PORT)
    logger.info("Cameras (%d): %s", len(sources), sources)

    try:
        async with websockets.serve(
            lambda ws: handle_client(ws, app, len(sources)),
            SIGNALING_HOST,
            SIGNALING_PORT,
        ):
            await asyncio.Future()
    finally:
        app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())

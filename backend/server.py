import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import cv2
import websockets
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaRelay
from aiortc.mediastreams import MediaStreamTrack, VideoStreamTrack
from av import VideoFrame
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
    """
    Suppress the harmless aioice race that logs:
      'Exception in callback Transaction.__retry() ... InvalidStateError: invalid state'
    This happens when an ICE transaction timer fires after the connection is
    already closed/succeeded – it is a known aioice quirk, not a real error.
    """
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


def _env_str(name: str, default: str) -> str:
    v = os.environ.get(name)
    return default if v is None else str(v)


SIGNALING_HOST = os.environ.get("SIGNALING_HOST", "0.0.0.0")
SIGNALING_PORT = _env_int("SIGNALING_PORT", 8765)
OPENCV_FFMPEG_CAPTURE_OPTIONS = _env_str("OPENCV_FFMPEG_CAPTURE_OPTIONS", "")
CAMERA_BUFFERSIZE = _env_int("CAMERA_BUFFERSIZE", 1)


DEFAULT_CAMERAS = [
    "rtsp://user:pass@192.168.1.10:554/stream1",
    "rtsp://user:pass@192.168.1.11:554/stream1",
    "rtsp://user:pass@192.168.1.12:554/stream1",
    "rtsp://user:pass@192.168.1.13:554/stream1",
]


def load_camera_sources() -> list[str]:
    """
    Load camera sources from env.

    Preferred format (easy / non-JSON):
      CAMERA_0, CAMERA_1, CAMERA_2, CAMERA_3  (empty values are ignored)

    Optional advanced format:
      CAMERA_SOURCES='["rtsp://...","rtsp://..."]'  (JSON list of strings)
    """
    cams: list[str] = []
    for i in range(4):
        v = os.environ.get(f"CAMERA_{i}")
        if isinstance(v, str) and v.strip():
            cams.append(v.strip())

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


@dataclass
class CameraConfig:
    sources: list[str]
    width: int = 1280
    height: int = 720
    fps: int = 30
    buffersize: int = 1


class OpenCVCameraTrack(VideoStreamTrack):
    """
    OpenCV capture -> WebRTC VideoStreamTrack.

    All blocking OpenCV calls (open + read) run in a thread-pool executor so
    they never stall the asyncio event loop.  This is critical for:
      - keeping WebSocket keepalive alive while a camera takes time to connect;
      - achieving full FPS because cap.read() can take >30 ms on RTSP streams.
    """

    def __init__(self, source: str, width: int, height: int, fps: int, buffersize: int):
        super().__init__()  # type: ignore[misc]
        self._source = source
        self._width = width
        self._height = height
        self._fps = fps
        self._buffersize = buffersize
        self._cap: Optional[cv2.VideoCapture] = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Synchronous helpers – called only from run_in_executor
    # ------------------------------------------------------------------

    def _open_sync(self) -> cv2.VideoCapture:
        src: Any = self._source
        if isinstance(self._source, str) and self._source.isdigit():
            src = int(self._source)
        if isinstance(src, str) and src.lower().startswith("rtsp://"):
            if OPENCV_FFMPEG_CAPTURE_OPTIONS:
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = OPENCV_FFMPEG_CAPTURE_OPTIONS
                logger.info("cam=%s ffmpeg_opts=%s", self._source, OPENCV_FFMPEG_CAPTURE_OPTIONS)
            cap = cv2.VideoCapture(src, cv2.CAP_FFMPEG)
        else:
            cap = cv2.VideoCapture(src)
        if self._width:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(self._width))
        if self._height:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self._height))
        if self._fps:
            cap.set(cv2.CAP_PROP_FPS, float(self._fps))
        if self._buffersize:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, float(self._buffersize))
        if not cap.isOpened():
            cap.release()
            logger.error("Failed to open camera source: %s", self._source)
            raise RuntimeError(f"Failed to open camera source: {self._source}")
        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        actual_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        logger.info("Opened camera source: %s", self._source)
        logger.info(
            "cam=%s requested=%sx%s@%s actual=%sx%s@%.2f",
            self._source,
            self._width,
            self._height,
            self._fps,
            actual_w,
            actual_h,
            actual_fps,
        )
        return cap

    def _read_sync(self):
        assert self._cap is not None
        return self._cap.read()

    def _release_sync(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    # ------------------------------------------------------------------
    # Async interface
    # ------------------------------------------------------------------

    async def _ensure_open(self, loop: asyncio.AbstractEventLoop) -> None:
        """Open the capture if not already open. Raises RuntimeError on failure."""
        if self._cap is None:
            self._cap = await loop.run_in_executor(None, self._open_sync)

    async def recv(self) -> VideoFrame:
        loop = asyncio.get_running_loop()

        async with self._lock:
            await self._ensure_open(loop)

            ok, frame = await loop.run_in_executor(None, self._read_sync)
            if not ok or frame is None:
                logger.warning("Camera read failed, reopening: %s", self._source)
                await loop.run_in_executor(None, self._release_sync)
                await asyncio.sleep(0.2)
                await self._ensure_open(loop)
                ok, frame = await loop.run_in_executor(None, self._read_sync)
                if not ok or frame is None:
                    raise asyncio.CancelledError(f"Camera read failed: {self._source}")

        # Some RTSP sources ignore CAP_PROP_FRAME_WIDTH/HEIGHT; enforce output size.
        if self._width and self._height:
            if frame.shape[1] != self._width or frame.shape[0] != self._height:
                frame = cv2.resize(frame, (self._width, self._height), interpolation=cv2.INTER_LINEAR)

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        vf = VideoFrame.from_ndarray(frame_rgb, format="rgb24")
        pts, time_base = await self.next_timestamp()
        vf.pts = pts
        vf.time_base = time_base
        return vf

    def stop(self) -> None:
        super().stop()
        self._release_sync()


class SignalingError(Exception):
    pass


def _json_dumps(msg: Dict[str, Any]) -> str:
    return json.dumps(msg, separators=(",", ":"))


async def _send(ws, msg: Dict[str, Any]) -> None:
    try:
        await ws.send(_json_dumps(msg))
    except websockets.exceptions.ConnectionClosed:
        pass


async def _expect(msg: Dict[str, Any], key: str, typ):
    val = msg.get(key)
    if not isinstance(val, typ):
        raise SignalingError(f"Expected {key} to be {typ.__name__}")
    return val


class App:
    def __init__(self, cfg: CameraConfig):
        self.cfg = cfg
        self.relay = MediaRelay()
        # Храним только исходные треки камер.
        # Подписки relay выдаем по запросу для каждого нового peer.
        self.base_tracks: list[OpenCVCameraTrack] = []

        for src in cfg.sources:
            base = OpenCVCameraTrack(src, cfg.width, cfg.height, cfg.fps, cfg.buffersize)
            self.base_tracks.append(base)

    def get_track(self, camera_index: int) -> MediaStreamTrack:
        if camera_index < 0 or camera_index >= len(self.base_tracks):
            raise SignalingError("cameraIndex out of range")
        # Каждый PeerConnection должен получить отдельную relay-подписку.
        return self.relay.subscribe(self.base_tracks[camera_index])

    async def shutdown(self):
        """Корректно освобождаем все ресурсы камер"""
        for track in self.base_tracks:
            try:
                track.stop()
            except Exception as e:
                logger.warning("Failed to stop track: %s", e)


async def handle_client(ws, app: App):
    client_id = str(uuid.uuid4())
    pcs: dict[str, RTCPeerConnection] = {}

    logger.info("client connected id=%s cameras=%d", client_id, len(app.cfg.sources))
    await _send(ws, {"type": "hello", "clientId": client_id, "cameras": len(app.cfg.sources)})

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
                mtype = await _expect(msg, "type", str)

                if mtype == "offer":
                    camera_index = int(msg.get("cameraIndex", -1))
                    sdp = await _expect(msg, "sdp", str)
                    offer_type = await _expect(msg, "sdpType", str)
                    logger.info("offer client=%s cam=%d", client_id, camera_index)

                    pc_key = f"cam{camera_index}"
                    if pc_key in pcs:
                        await pcs[pc_key].close()
                        del pcs[pc_key]

                    pc = RTCPeerConnection()
                    pcs[pc_key] = pc

                    @pc.on("iceconnectionstatechange")
                    async def on_ice_state_change():
                        if pc.iceConnectionState in ("failed", "closed", "disconnected"):
                            await pc.close()
                            pcs.pop(pc_key, None)

                    await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=offer_type))

                    track = app.get_track(camera_index)
                    pc.addTrack(track)

                    answer = await pc.createAnswer()
                    await pc.setLocalDescription(answer)

                    await _send(
                        ws,
                        {
                            "type": "answer",
                            "cameraIndex": camera_index,
                            "sdp": pc.localDescription.sdp,
                            "sdpType": pc.localDescription.type,
                        },
                    )

                elif mtype == "ice":
                    # For server-as-answerer, browsers will still send ICE candidates.
                    # aiortc can accept them via addIceCandidate, but we keep this minimal by relying on
                    # ICE gathering on both sides and trickle from browser; for many LAN setups it's ok.
                    # If you need full trickle ICE, extend this to pc.addIceCandidate().
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
    cfg = CameraConfig(
        sources=sources,
        width=_env_int("CAMERA_WIDTH", 1280),
        height=_env_int("CAMERA_HEIGHT", 720),
        fps=_env_int("CAMERA_FPS", 30),
        buffersize=_env_int("CAMERA_BUFFERSIZE", CAMERA_BUFFERSIZE),
    )
    app = App(cfg)

    logger.info("Signaling WS on ws://%s:%s", SIGNALING_HOST, SIGNALING_PORT)
    logger.info("Cameras: %s", cfg.sources)
    try:
        async with websockets.serve(lambda ws: handle_client(ws, app), SIGNALING_HOST, SIGNALING_PORT):
            await asyncio.Future()
    finally:
        # ← Гарантированно освобождаем камеры при выходе
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())


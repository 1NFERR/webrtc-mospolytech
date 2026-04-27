from __future__ import annotations

import asyncio
import logging
import platform
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from aiortc import MediaStreamTrack, VideoStreamTrack
from aiortc.contrib.media import MediaPlayer, MediaRelay
from aiortc.mediastreams import MediaStreamError
from av import VideoFrame
from PIL import Image

from config import MediaSourceConfig, Settings

FrameProcessor = Callable[[np.ndarray], np.ndarray]


class StaticImageStreamTrack(VideoStreamTrack):
    """Streams one image as a repeated video frame."""

    def __init__(self, image_path: str, fps: int = 15):
        super().__init__()
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {path}")

        image = Image.open(path).convert("RGB")
        self._frame = VideoFrame.from_ndarray(np.array(image), format="rgb24")
        self._frame_time = 1 / fps
        self._lock = asyncio.Lock()

    async def recv(self) -> VideoFrame:
        async with self._lock:
            await asyncio.sleep(self._frame_time)
            pts, time_base = await self.next_timestamp()
            frame = self._frame.reformat(format="yuv420p")
            frame.pts = pts
            frame.time_base = time_base
            return frame


class ProcessingVideoTrack(VideoStreamTrack):
    """Wrapper for future real-time OpenCV/NN frame processing."""

    def __init__(
        self,
        source_track: MediaStreamTrack,
        frame_processor: Optional[FrameProcessor] = None,
    ):
        super().__init__()
        self._source_track = source_track
        self._frame_processor = frame_processor

    async def recv(self) -> VideoFrame:
        frame = await self._source_track.recv()
        if not self._frame_processor:
            return frame

        rgb = frame.to_ndarray(format="rgb24")
        processed = self._frame_processor(rgb)
        result = VideoFrame.from_ndarray(processed, format="rgb24")
        result.pts = frame.pts
        result.time_base = frame.time_base
        return result


class FallbackVideoTrack(VideoStreamTrack):
    """Returns source frame, reconnects source on failures, falls back to placeholder."""

    def __init__(
        self,
        source_id: str,
        fallback_track: MediaStreamTrack,
        get_primary_track: Callable[[], Optional[MediaStreamTrack]],
        reconnect_source: Callable[[str], None],
    ):
        super().__init__()
        self._source_id = source_id
        self._fallback_track = fallback_track
        self._get_primary_track = get_primary_track
        self._reconnect_source = reconnect_source
        self._primary_track: Optional[MediaStreamTrack] = None
        self._next_reconnect_at = 0.0
        self._last_error_log_at = 0.0

    async def recv(self) -> VideoFrame:
        now = time.time()

        if self._primary_track is None:
            self._primary_track = self._get_primary_track()

        if self._primary_track is None and now >= self._next_reconnect_at:
            self._reconnect_source(self._source_id)
            self._primary_track = self._get_primary_track()
            self._next_reconnect_at = now + 2.0

        if self._primary_track is None:
            return await self._fallback_track.recv()

        try:
            return await self._primary_track.recv()
        except MediaStreamError:
            if now - self._last_error_log_at >= 2.0:
                logging.warning(
                    "Camera '%s' stream ended, reconnecting and using placeholder",
                    self._source_id,
                )
                self._last_error_log_at = now
            self._primary_track = None
            self._next_reconnect_at = now
            self._reconnect_source(self._source_id)
            return await self._fallback_track.recv()
        except Exception:
            if now - self._last_error_log_at >= 2.0:
                logging.exception(
                    "Camera '%s' frame read failed, reconnecting and using placeholder",
                    self._source_id,
                )
                self._last_error_log_at = now
            self._primary_track = None
            self._next_reconnect_at = now + 2.0
            return await self._fallback_track.recv()


class MediaManager:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._relay = MediaRelay()
        self._players: dict[str, MediaPlayer] = {}
        self._base_tracks: dict[str, Optional[VideoStreamTrack]] = {}
        self._source_configs = {source.id: source for source in settings.media_sources}
        self._placeholder_track = StaticImageStreamTrack(
            settings.placeholder_image_path, fps=settings.placeholder_fps
        )
        self._init_sources()

    def available_camera_ids(self) -> list[str]:
        return [source.id for source in self._settings.media_sources]

    def _init_sources(self) -> None:
        for source in self._settings.media_sources:
            self._init_source(source)

    def _init_source(self, source: MediaSourceConfig) -> None:
        old_player = self._players.pop(source.id, None)
        if old_player:
            self._stop_player(old_player, source.id)

        try:
            player = self._create_player(source)
        except Exception:
            logging.exception("Could not initialize media source '%s'", source.id)
            self._base_tracks[source.id] = None
            return

        if not player.video:
            logging.error("Media source '%s' has no video track", source.id)
            self._players[source.id] = player
            self._base_tracks[source.id] = None
            return

        self._players[source.id] = player
        self._base_tracks[source.id] = player.video
        logging.info("Camera '%s' initialized", source.id)

    def _create_player(self, source: MediaSourceConfig) -> MediaPlayer:
        if source.type == "rtsp":
            if not source.url:
                raise ValueError(f"Camera '{source.id}' is RTSP but has empty url")
            return MediaPlayer(source.url, options=source.rtsp_options)

        if source.type == "webcam":
            device, fmt = self._resolve_webcam_source(source)
            return MediaPlayer(device, format=fmt, options=source.options)

        raise ValueError(f"Unsupported source type '{source.type}' for '{source.id}'")

    def _resolve_webcam_source(self, source: MediaSourceConfig) -> tuple[str, str]:
        if source.url:
            return source.url, source.format

        system = platform.system().lower()
        if system == "windows":
            return "video=Integrated Camera", "dshow"
        if system == "darwin":
            return "default:none", "avfoundation"
        return "/dev/video0", "v4l2"

    def _build_primary_track(self, source_id: str) -> Optional[MediaStreamTrack]:
        source = self._source_configs.get(source_id)
        if not source:
            raise ValueError(f"Unknown cameraId '{source_id}'")

        base_track = self._base_tracks.get(source_id)
        if base_track is None:
            self._reconnect_source(source_id)
            base_track = self._base_tracks.get(source_id)

        if base_track is None:
            return None

        primary: MediaStreamTrack = self._relay.subscribe(base_track, buffered=False)
        if source.use_frame_processing:
            primary = ProcessingVideoTrack(primary)
        return primary

    def _reconnect_source(self, source_id: str) -> None:
        source = self._source_configs.get(source_id)
        if not source:
            return
        logging.info("Reinitializing camera '%s'", source_id)
        self._init_source(source)

    def get_track(self, source_id: str) -> VideoStreamTrack:
        if source_id not in self._source_configs:
            raise ValueError(f"Unknown cameraId '{source_id}'")

        return FallbackVideoTrack(
            source_id=source_id,
            fallback_track=self._relay.subscribe(self._placeholder_track, buffered=False),
            get_primary_track=lambda: self._build_primary_track(source_id),
            reconnect_source=self._reconnect_source,
        )

    def refresh_all_sources(self) -> None:
        """Re-open all inputs to drop stale buffered media before a new session."""
        logging.info("Refreshing all camera sources for a fresh live session")
        for source in self._settings.media_sources:
            self._init_source(source)

    async def shutdown(self) -> None:
        for source_id, player in list(self._players.items()):
            self._stop_player(player, source_id)
        self._players.clear()
        self._base_tracks.clear()

    def _stop_player(self, player: MediaPlayer, source_id: str) -> None:
        try:
            thread_quit = getattr(player, "_MediaPlayer__thread_quit", None)
            if thread_quit is not None:
                thread_quit.set()

            thread = getattr(player, "_MediaPlayer__thread", None)
            if thread is not None and thread.is_alive():
                thread.join(timeout=1.0)

            container = getattr(player, "_MediaPlayer__container", None)
            if container is not None:
                container.close()
        except Exception:
            logging.exception("Failed to stop MediaPlayer for '%s'", source_id)

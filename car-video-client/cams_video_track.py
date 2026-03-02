from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

import cv2
from aiortc import VideoStreamTrack
from av import VideoFrame


class CamsVideoStreamTrack(VideoStreamTrack):
    """
    Streams prerecorded footage from cams_videos as a WebRTC track.
    The video loops once the end of the file is reached.
    """

    def __init__(
        self,
        folder: str = "cams_videos",
        filename: str = "cam0_2021-11-25 11-45-19.avi",
        fps: Optional[int] = None,
        loop: bool = True,
    ):
        super().__init__()

        self._lock = asyncio.Lock()
        self._folder = Path(folder)
        if not self._folder.exists():
            raise FileNotFoundError(f"Folder for recorded videos not found: {self._folder}")

        self._video_path = self._folder / filename
        if not self._video_path.exists():
            raise FileNotFoundError(f"Video file not found: {self._video_path}")

        logging.info("Opening recorded video %s", self._video_path)
        self._cap = cv2.VideoCapture(str(self._video_path))
        if not self._cap.isOpened():
            raise RuntimeError(f"Failed to open video file: {self._video_path}")

        detected_fps = self._cap.get(cv2.CAP_PROP_FPS) or 0
        self._fps = fps or (detected_fps if detected_fps > 0 else 30)
        self._frame_time = 1 / self._fps
        self._loop = loop

    async def recv(self) -> VideoFrame:
        async with self._lock:
            await asyncio.sleep(self._frame_time)

            ok, frame = self._cap.read()
            if not ok:
                if not self._loop:
                    raise RuntimeError("End of recorded video reached")

                logging.info("Reached end of %s, restarting playback", self._video_path.name)
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self._cap.read()
                if not ok:
                    raise RuntimeError(f"Failed to read frame from {self._video_path}")

            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            video_frame = VideoFrame.from_ndarray(frame, format="rgb24")
            pts, time_base = await self.next_timestamp()
            video_frame.pts = pts
            video_frame.time_base = time_base
            return video_frame

    async def stop(self) -> None:
        logging.info("Releasing recorded video %s", self._video_path)
        if self._cap:
            self._cap.release()
        await super().stop()

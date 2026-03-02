from __future__ import annotations

import asyncio
import logging
from typing import Optional

import cv2
import numpy as np
from aiortc import VideoStreamTrack
from av import VideoFrame


class WebcamStreamTrack(VideoStreamTrack):
    """
    Захват видео с веб-камеры ноутбука и передача в WebRTC.
    """

    def __init__(
        self,
        camera_index: int = 0,
        fps: int = 30,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ):
        super().__init__()

        self._fps = fps
        self._frame_time = 1 / fps
        self._lock = asyncio.Lock()

        logging.info("Opening webcam (index=%s)", camera_index)
        self._cap = cv2.VideoCapture(camera_index)

        if not self._cap.isOpened():
            raise RuntimeError("Failed to open webcam")

        # Настройка разрешения (опционально)
        if width:
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        if height:
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

        # Попытка зафиксировать FPS (не все камеры поддерживают)
        self._cap.set(cv2.CAP_PROP_FPS, fps)

    async def recv(self) -> VideoFrame:
        async with self._lock:
            await asyncio.sleep(self._frame_time)

            ok, frame = self._cap.read()
            if not ok:
                logging.warning("Failed to read frame from webcam")
                await asyncio.sleep(0.1)
                return await self.recv()

            # OpenCV → RGB
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            video_frame = VideoFrame.from_ndarray(frame, format="rgb24")
            pts, time_base = await self.next_timestamp()
            video_frame.pts = pts
            video_frame.time_base = time_base

            return video_frame

    async def stop(self) -> None:
        logging.info("Releasing webcam")
        if self._cap:
            self._cap.release()
        await super().stop()

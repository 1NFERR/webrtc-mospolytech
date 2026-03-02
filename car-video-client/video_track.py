from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

import numpy as np
from aiortc import VideoStreamTrack
from av import VideoFrame
from PIL import Image


class StaticImageStreamTrack(VideoStreamTrack):
    """Loops over a static image to mimic a camera feed."""

    def __init__(self, image_path: str, fps: int = 15):
        super().__init__()
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")
        logging.info("Loading demo frame from %s", path.resolve())
        image = Image.open(path).convert("RGB")
        self._frame = VideoFrame.from_ndarray(np.array(image), format="rgb24")
        self._frame_time = 1 / fps
        self._lock = asyncio.Lock()

    async def recv(self) -> VideoFrame:
        async with self._lock:
            await asyncio.sleep(self._frame_time)
            pts, time_base = await self.next_timestamp()
            frame = self._frame
            frame.pts = pts
            frame.time_base = time_base
            return frame

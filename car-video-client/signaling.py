from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable, Dict, Optional

import websockets
from websockets.client import WebSocketClientProtocol

from auth import KeycloakTokenProvider
from config import Settings

MessageHandler = Callable[[dict], Awaitable[None]]


class SignalingClient:
    """WebSocket helper with auto-reconnect and event dispatch."""

    def __init__(self, settings: Settings, token_provider: KeycloakTokenProvider):
        self._settings = settings
        self._token_provider = token_provider
        self._handlers: Dict[str, MessageHandler] = {}
        self._ws: Optional[WebSocketClientProtocol] = None
        self._stop = asyncio.Event()

    def on(self, message_type: str, handler: MessageHandler) -> None:
        self._handlers[message_type] = handler

    async def send(self, payload: dict) -> None:
        if not self._ws:
            logging.warning("Unable to send, signaling socket not ready: %s", payload)
            return
        await self._ws.send(json.dumps(payload))

    async def start(self) -> None:
        logging.info("Connecting to signaling server at %s", self._settings.signaling_ws_url)
        while not self._stop.is_set():
            try:
                token = await self._token_provider.get_token()
                async with websockets.connect(self._settings.signaling_ws_url) as ws:
                    self._ws = ws
                    await self._register(ws, token)
                    await self._receive_loop(ws)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logging.exception("Signaling connection failed: %s", exc)
                await asyncio.sleep(5)
            finally:
                self._ws = None

    async def stop(self) -> None:
        self._stop.set()
        if self._ws:
            await self._ws.close()

    async def _register(self, ws: WebSocketClientProtocol, token: str) -> None:
        payload = {
            "type": "register",
            "role": "car",
            "clientId": self._settings.client_id,
            "token": token,
        }
        await ws.send(json.dumps(payload))

    async def _receive_loop(self, ws: WebSocketClientProtocol) -> None:
        async for raw in ws:
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                logging.warning("Ignoring malformed signaling payload: %s", raw)
                continue
            message_type = message.get("type")
            if message_type == "ping":
                await ws.send(json.dumps({"type": "pong"}))
                continue
            handler = self._handlers.get(message_type)
            if handler:
                await handler(message)
            else:
                logging.debug("Unhandled signaling message: %s", message)

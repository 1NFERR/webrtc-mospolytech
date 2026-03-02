from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import aiohttp

from config import Settings


class KeycloakTokenProvider:
    """Fetches and caches client-credential tokens from Keycloak."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._lock = asyncio.Lock()
        self._token: Optional[str] = None
        self._expires_at: float = 0.0

    async def get_token(self) -> str:
        async with self._lock:
            now = time.time()
            if (
                not self._token
                or now + self._settings.token_refresh_margin >= self._expires_at
            ):
                await self._refresh_token()
            return self._token  # type: ignore[return-value]

    async def _refresh_token(self) -> None:
        if not self._settings.keycloak_token_url:
            raise RuntimeError("KEYCLOAK_TOKEN_URL is not configured")

        # data = {
        #     "client_id": self._settings.keycloak_client_id,
        #     "client_secret": self._settings.keycloak_client_secret,
        #     "grant_type": "client_credentials",
        # }
        # logging.info("Requesting Keycloak token for %s", self._settings.client_id)
        # async with aiohttp.ClientSession() as session:
        #     async with session.post(self._settings.keycloak_token_url, data=data) as resp:
        #         if resp.status != 200:
        #             body = await resp.text()
        #             raise RuntimeError(
        #                 f"Keycloak token request failed: {resp.status} {body}"
        #             )
        #         payload = await resp.json()

        # access_token = payload["access_token"]
        # expires_in = payload.get("expires_in", 60)
        # self._token = access_token
        # self._expires_at = time.time() + int(expires_in)
        # logging.info(
        #     "Obtained Keycloak token (expires in %ss)", int(expires_in)
        # )

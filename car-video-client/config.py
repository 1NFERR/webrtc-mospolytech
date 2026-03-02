from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any, List

from dotenv import load_dotenv

DEFAULT_ICE_SERVERS = [{"urls": ["stun:stun.l.google.com:19302"]}]


@dataclass
class Settings:
    client_id: str
    image_path: str
    video_source: str
    cams_video_folder: str
    cams_video_filename: str
    signaling_ws_url: str
    keycloak_token_url: str
    keycloak_client_id: str
    keycloak_client_secret: str
    token_refresh_margin: int
    log_level: str
    ice_servers: List[dict[str, Any]]


def _parse_ice_servers(raw_value: str | None) -> List[dict[str, Any]]:
    if not raw_value:
        return DEFAULT_ICE_SERVERS
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        urls = [item.strip() for item in raw_value.split(",") if item.strip()]
        return [{"urls": urls}] if urls else DEFAULT_ICE_SERVERS

    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        return DEFAULT_ICE_SERVERS

    normalized: List[dict[str, Any]] = []
    for entry in parsed:
        if isinstance(entry, str):
            normalized.append({"urls": [entry]})
            continue
        if isinstance(entry, dict):
            urls = entry.get("urls")
            if isinstance(urls, str):
                entry = {**entry, "urls": [urls]}
            normalized.append(entry)
    return normalized or DEFAULT_ICE_SERVERS


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        client_id=os.getenv("CLIENT_ID", "car-001"),
        image_path=os.getenv("IMAGE_PATH", "assets/demo.jpg"),
        video_source=os.getenv("VIDEO_SOURCE", "cams_video"),
        cams_video_folder=os.getenv("CAMS_VIDEO_FOLDER", "cams_videos"),
        cams_video_filename=os.getenv(
            "CAMS_VIDEO_FILENAME", "cam0_2021-11-25 11-45-19.avi"
        ),
        signaling_ws_url=os.getenv("SIGNALING_WS_URL", "ws://localhost:4000/ws"),
        keycloak_token_url=os.getenv("KEYCLOAK_TOKEN_URL", ""),
        keycloak_client_id=os.getenv("KEYCLOAK_CLIENT_ID", ""),
        keycloak_client_secret=os.getenv("KEYCLOAK_CLIENT_SECRET", ""),
        token_refresh_margin=int(os.getenv("TOKEN_REFRESH_MARGIN", "30")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        ice_servers=_parse_ice_servers(os.getenv("ICE_SERVERS")),
    )

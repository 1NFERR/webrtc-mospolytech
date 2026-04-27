from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

DEFAULT_ICE_SERVERS = [{"urls": ["stun:stun.l.google.com:19302"]}]
DEFAULT_RTSP_OPTIONS = {
    "rtsp_transport": "tcp",
    "fflags": "nobuffer",
    "flags": "low_delay",
    "max_delay": "0",
    "reorder_queue_size": "0",
    "analyzeduration": "0",
    "probesize": "32768",
}
DEFAULT_WEBCAM_OPTIONS = {
    "framerate": "30",
    "video_size": "1280x720",
}
MODULE_DIR = Path(__file__).resolve().parent


@dataclass
class MediaSourceConfig:
    id: str
    type: str
    url: str
    format: str
    options: dict[str, str]
    rtsp_options: dict[str, str]
    use_frame_processing: bool


@dataclass
class Settings:
    client_id: str
    media_sources: list[MediaSourceConfig]
    default_camera_id: str
    placeholder_image_path: str
    placeholder_fps: int
    signaling_ws_url: str
    signaling_auth_token: str
    keycloak_token_url: str
    keycloak_client_id: str
    keycloak_client_secret: str
    token_refresh_margin: int
    log_level: str
    ice_servers: list[dict[str, Any]]


def _parse_ice_servers(raw_value: str | None) -> list[dict[str, Any]]:
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

    normalized: list[dict[str, Any]] = []
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


def _parse_json_object(raw_value: str | None, default: dict[str, str]) -> dict[str, str]:
    if not raw_value:
        return dict(default)
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return dict(default)
    if not isinstance(parsed, dict):
        return dict(default)
    return {str(k): str(v) for k, v in parsed.items()}


def _parse_bool(raw_value: str | None, default: bool) -> bool:
    if raw_value is None:
        return default
    return raw_value.strip().lower() in ("1", "true", "yes", "on")


def _resolve_path(raw_value: str | None, fallback_relative: str) -> str:
    if raw_value:
        candidate = Path(raw_value)
    else:
        candidate = MODULE_DIR / fallback_relative
    return str(candidate.resolve())


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _default_media_sources() -> list[MediaSourceConfig]:
    return [
        MediaSourceConfig(
            id="cam-front",
            type="rtsp",
            url="rtsp://user:pass@192.168.1.10:554/stream1",
            format="",
            options={},
            rtsp_options=dict(DEFAULT_RTSP_OPTIONS),
            use_frame_processing=False,
        )
    ]


def _normalize_media_source(
    entry: dict[str, Any],
    index: int,
    default_rtsp_options: dict[str, str],
    default_webcam_options: dict[str, str],
) -> MediaSourceConfig:
    source_type = str(entry.get("type", "rtsp")).strip().lower()
    if source_type not in ("rtsp", "webcam"):
        raise ValueError(f"Unsupported media source type: {source_type}")

    source_id = str(entry.get("id", f"cam-{index}")).strip() or f"cam-{index}"
    source_url = str(entry.get("url", "")).strip()
    source_format = str(entry.get("format", "")).strip()
    use_processing = _parse_bool(str(entry.get("use_frame_processing", "false")), False)

    options_raw = entry.get("options")
    if isinstance(options_raw, dict):
        options = {str(k): str(v) for k, v in options_raw.items()}
    else:
        options = (
            dict(default_webcam_options) if source_type == "webcam" else dict(default_rtsp_options)
        )

    rtsp_raw = entry.get("rtsp_options")
    if isinstance(rtsp_raw, dict):
        rtsp_options = {str(k): str(v) for k, v in rtsp_raw.items()}
    else:
        rtsp_options = dict(default_rtsp_options)

    return MediaSourceConfig(
        id=source_id,
        type=source_type,
        url=source_url,
        format=source_format,
        options=options,
        rtsp_options=rtsp_options,
        use_frame_processing=use_processing,
    )


def _load_media_sources(default_rtsp_options: dict[str, str]) -> list[MediaSourceConfig]:
    raw_json = os.getenv("MEDIA_SOURCES", "").strip()
    default_webcam_options = _parse_json_object(
        os.getenv("DEFAULT_WEBCAM_OPTIONS"), DEFAULT_WEBCAM_OPTIONS
    )

    if not raw_json:
        return _default_media_sources()

    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"MEDIA_SOURCES must be valid JSON: {exc}") from exc

    if not isinstance(parsed, list):
        raise ValueError("MEDIA_SOURCES must be a JSON array")

    sources: list[MediaSourceConfig] = []
    seen_ids: set[str] = set()
    for index, entry in enumerate(parsed):
        if not isinstance(entry, dict):
            raise ValueError("Each MEDIA_SOURCES item must be an object")
        source = _normalize_media_source(
            entry,
            index=index,
            default_rtsp_options=default_rtsp_options,
            default_webcam_options=default_webcam_options,
        )
        if source.id in seen_ids:
            raise ValueError(f"Duplicate camera id in MEDIA_SOURCES: {source.id}")
        seen_ids.add(source.id)
        sources.append(source)

    if not sources:
        raise ValueError("MEDIA_SOURCES must contain at least one camera")
    return sources


def load_settings() -> Settings:
    load_dotenv()

    rtsp_options = _parse_json_object(os.getenv("RTSP_OPTIONS"), DEFAULT_RTSP_OPTIONS)
    media_sources = _load_media_sources(rtsp_options)

    default_camera_id = os.getenv("DEFAULT_CAMERA_ID", "").strip() or media_sources[0].id
    if default_camera_id not in {source.id for source in media_sources}:
        raise ValueError(f"DEFAULT_CAMERA_ID '{default_camera_id}' is not in MEDIA_SOURCES")

    return Settings(
        client_id=os.getenv("CLIENT_ID", "car-001"),
        media_sources=media_sources,
        default_camera_id=default_camera_id,
        placeholder_image_path=_resolve_path(
            os.getenv("PLACEHOLDER_IMAGE_PATH"), "assets/no_signal.png"
        ),
        placeholder_fps=_env_int("PLACEHOLDER_FPS", 15),
        signaling_ws_url=os.getenv("SIGNALING_WS_URL", "ws://localhost:4000/ws"),
        signaling_auth_token=os.getenv("SIGNALING_AUTH_TOKEN", "demo"),
        keycloak_token_url=os.getenv("KEYCLOAK_TOKEN_URL", ""),
        keycloak_client_id=os.getenv("KEYCLOAK_CLIENT_ID", ""),
        keycloak_client_secret=os.getenv("KEYCLOAK_CLIENT_SECRET", ""),
        token_refresh_margin=_env_int("TOKEN_REFRESH_MARGIN", 30),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        ice_servers=_parse_ice_servers(os.getenv("ICE_SERVERS")),
    )

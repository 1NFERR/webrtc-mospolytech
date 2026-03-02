# Car Video Client

Python service that runs next to the car hardware. It authenticates with Keycloak via the client-credentials flow, keeps a persistent WebSocket connection to the signaling server, and answers incoming WebRTC offers by streaming a placeholder image.

The video pipeline is intentionally abstracted so a real camera capture component can replace the demo image track later.

## Setup

```bash
cd car-video-client
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env` with the values from your Keycloak realm and signaling server.

## Running

```bash
source .venv/bin/activate
python main.py
```

The client keeps reconnecting automatically if the signaling server is not reachable yet.

## Environment variables

| Name | Description |
| --- | --- |
| `CLIENT_ID` | Identifier used by the car; the operator references it from the frontend. |
| `IMAGE_PATH` | Path to the placeholder image that should be streamed. Defaults to `assets/demo.jpg`. |
| `SIGNALING_WS_URL` | WebSocket endpoint of the signaling server, e.g. `ws://localhost:4000/ws`. |
| `ICE_SERVERS` | JSON (or comma-separated list) describing the STUN/TURN servers for ICE, e.g. `[{"urls":["stun:stun.l.google.com:19302"]}]`. |
| `KEYCLOAK_TOKEN_URL` | Token endpoint used for client credentials, e.g. `https://keycloak.local/realms/cars/protocol/openid-connect/token`. |
| `KEYCLOAK_CLIENT_ID` | Keycloak service account client ID. |
| `KEYCLOAK_CLIENT_SECRET` | Secret for the service account. |
| `TOKEN_REFRESH_MARGIN` | Seconds before expiry to refresh the token (default 30). |
| `LOG_LEVEL` | python logging level (`INFO`, `DEBUG`, …). |

## Replacing the placeholder video

`StaticImageStreamTrack` (see `video_track.py`) is the only demo-specific part. Swap it with a class that pulls frames from a camera or GStreamer pipeline and yields `av.VideoFrame` objects. The rest of the signaling and authentication stack remains unchanged.

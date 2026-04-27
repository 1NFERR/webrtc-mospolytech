# WebRTC Car Video Prototype

Repository contains 3 services:
- `signaling-server` (Node.js): auth + signaling relay
- `frontend` (Vite/TS): operator UI
- `car-video-client` (Python): car-side WebRTC sender

## Unified start

```bash
python start.py
```

Optional:

```bash
python start.py --skip-update
```

Wrappers:
- Linux/macOS: `./start.sh`
- Windows: `start.bat`

`start.py` creates missing `.env` files from `.env.example`, installs dependencies (unless skipped), picks free ports, and runs all 3 services.

## Video source modes

`car-video-client` supports only:
- RTSP cameras (`MEDIA_SOURCES` list, multiple per car)
- local webcams (`MEDIA_SOURCES` with `type=webcam`)

After selecting a car, frontend shows all of its camera tracks (up to 4 tiles now).
On source failures it uses a placeholder image (`car-video-client/assets/no_signal.png`).

## Security baseline

- Set `signaling-server/.env`: `ALLOW_INSECURE_TOKENS=false`
- Use reachable Keycloak host/IP consistently in all services (for local: `http://127.0.0.1:8080`)
- Configure:
  - `KEYCLOAK_JWKS_URL` / `KEYCLOAK_ISSUER` in signaling
  - `KEYCLOAK_TOKEN_URL` + client credentials in car client
  - `VITE_KEYCLOAK_URL` in frontend

## Quick demo mode (no Keycloak)

- `signaling-server/.env`: `ALLOW_INSECURE_TOKENS=true`
- `frontend/.env`: `VITE_SKIP_KEYCLOAK=true`
- `car-video-client/.env`: `KEYCLOAK_TOKEN_URL=` and `SIGNALING_AUTH_TOKEN=demo`

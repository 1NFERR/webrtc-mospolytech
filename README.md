# WebRTC + WebSocket (4 Cameras)

Minimal project:
- **Backend (Python)**: OpenCV captures 4 camera sources and publishes them as WebRTC video tracks via `aiortc`.
- **Signaling**: a plain **WebSocket** server (no heavy API framework).
- **Frontend (TypeScript)**: 4 WebRTC peer connections, 4 `<video>` tiles.

## Folder structure

- `webrtc-4cams/backend/server.py`
- `webrtc-4cams/frontend/index.html`
- `webrtc-4cams/frontend/src/main.ts`

## Backend setup (Windows)

From `webrtc-4cams/backend`:

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python server.py
```

By default the signaling server listens on **`ws://0.0.0.0:8765`**.

### Backend config via `.env`

Copy `webrtc-4cams/backend/.env.example` to `webrtc-4cams/backend/.env` and edit.

Key variables:
- `CAMERA_0`..`CAMERA_3` (preferred, one RTSP URL per camera)
- `CAMERA_SOURCES` (optional alternative: JSON list of strings)
- `SIGNALING_HOST`, `SIGNALING_PORT`
- `CAMERA_WIDTH`, `CAMERA_HEIGHT`, `CAMERA_FPS`
- `CAMERA_BUFFERSIZE` (recommended `1` for RTSP)
- `OPENCV_FFMPEG_CAPTURE_OPTIONS` (recommended `rtsp_transport;tcp` for RTSP)

### Camera sources (examples)

Set `CAMERA_SOURCES` as JSON list of strings (in `backend/.env`).

Examples:

- 4 local webcams (indices):

```powershell
Copy-Item .env.example .env
# edit .env then:
python .\server.py
```

- RTSP cameras:

```powershell
Copy-Item .env.example .env
# set CAMERA_SOURCES=[...rtsp urls...] in .env then:
python .\server.py
```

Optional:
- `CAMERA_WIDTH` (default 1280)
- `CAMERA_HEIGHT` (default 720)
- `CAMERA_FPS` (default 30)
- `SIGNALING_HOST` (default `0.0.0.0`)
- `SIGNALING_PORT` (default `8765`)

## Frontend setup

From `webrtc-4cams/frontend`:

```bash
npm install
npm run build
```

Then open `webrtc-4cams/frontend/index.html` in your browser.

### Frontend config via `.env`

Copy `webrtc-4cams/frontend/.env.example` to `webrtc-4cams/frontend/.env` and edit `WS_URL`.

In the UI, the **input box wins**; if it’s empty, the app uses:
- `WS_URL` from `frontend/.env` (build-time), otherwise
- `ws://<current-host>:8765`

Then click **Connect**.

## Notes / limitations

- This is a **minimal** signaling implementation. If you need full trickle ICE (for tougher NAT scenarios), we can extend the `ice` message handling to call `pc.addIceCandidate(...)` on the server.
- For remote viewing across networks, you’ll typically want a TURN server.

## One-command start (Linux)

From `webrtc-4cams/`:

```bash
chmod +x start.sh
./start.sh
```

This starts:
- the backend WebSocket signaling server (Python)
- a static web server for the frontend (Python `http.server`)



# Car Video Client

Python service that registers as a car in signaling, receives WebRTC offers, and streams video from:
- RTSP IP camera via `aiortc.contrib.media.MediaPlayer`
- local webcam via `MediaPlayer` (FFmpeg backend)

One car can expose multiple cameras at once. Each incoming operator session receives all configured camera tracks in one WebRTC connection.

If camera initialization or frame read fails, the client streams a `no_signal` placeholder frame.

## Setup

```bash
cd car-video-client
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Run

```bash
source .venv/bin/activate
python main.py
```

## Main env variables

- `MEDIA_SOURCES`: JSON array with camera configs (`id`, `type`, `url`, optional `format`, `options`, `rtsp_options`, `use_frame_processing`)
- `DEFAULT_CAMERA_ID`: fallback/default camera ID from `MEDIA_SOURCES`
- `DEFAULT_WEBCAM_OPTIONS`: default ffmpeg options for webcam sources
- `RTSP_OPTIONS`: JSON object with RTSP tuning options
- `PLACEHOLDER_IMAGE_PATH`: fallback image path (`assets/no_signal.png` by default)
- `KEYCLOAK_TOKEN_URL`: service token endpoint (use reachable host/IP, e.g. `http://127.0.0.1:8080/...`)
- `SIGNALING_AUTH_TOKEN`: keep empty in secure mode (only for temporary insecure tests)

Quick demo (without Keycloak): set `KEYCLOAK_TOKEN_URL=` and `SIGNALING_AUTH_TOKEN=demo`.

The processing hook is implemented in `ProcessingVideoTrack` (`media_manager.py`) and can be extended with OpenCV/NN inference later.

For mixed camera vendors, set `rtsp_options` per camera directly inside `MEDIA_SOURCES` (for example Wisenet and Milesight may require different buffering/analysis values).

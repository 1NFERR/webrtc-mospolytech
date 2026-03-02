# Operator Frontend

Vite + TypeScript single-page app that lets an operator authenticate via Keycloak, see which cars are online, and establish a WebRTC session through the signaling server.

## Setup

```bash
cd frontend
npm install
cp .env.example .env
```

Edit `.env` so it matches your environment.

## Dev server

```bash
npm run dev
```

By default Vite serves on <http://localhost:5173>. The app automatically opens the Keycloak login screen (unless `VITE_SKIP_KEYCLOAK=true`) and then connects to the signaling server.

## Environment variables

| Name | Description |
| --- | --- |
| `VITE_SIGNALING_WS_URL` | WebSocket URL, e.g. `ws://localhost:4000/ws`. |
| `VITE_SIGNALING_HTTP_URL` | HTTP base URL of the signaling server, e.g. `http://localhost:4000`. |
| `VITE_KEYCLOAK_URL` | Keycloak base URL (without `/realms`). |
| `VITE_KEYCLOAK_REALM` | Realm name. |
| `VITE_KEYCLOAK_CLIENT_ID` | Public client used by the operator UI. |
| `VITE_SKIP_KEYCLOAK` | Set to `true` to skip login and manually enter a token for local testing. |
| `VITE_ICE_SERVERS` | JSON (or comma-separated URLs) describing the STUN/TURN servers pushed into `RTCPeerConnection`. |

When skipping Keycloak, the UI reveals a text area where you can paste any JWT (or the word `demo` when the signaling server runs with `ALLOW_INSECURE_TOKENS=true`).

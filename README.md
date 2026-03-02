# WebRTC Car Video Prototype

This repo contains three loosely coupled components that demonstrate how a remote operator can watch a car-mounted camera stream over WebRTC via Keycloak-protected signaling.

## Components

1. **car-video-client** – Python service that runs next to the car. It authenticates with Keycloak using the client-credentials flow, connects to the signaling server via WebSocket, and answers incoming WebRTC offers by streaming a placeholder image as video (the code is structured so a real camera feed can be plugged in later).
2. **signaling-server** – Node.js WebSocket + REST server that performs token validation, keeps track of which car clients are online, enforces the “one operator per car” rule, and relays SDP/ICE messages between peers.
3. **frontend** – Vite + vanilla TypeScript SPA that authenticates the operator through Keycloak (using `keycloak-js`), lists available cars, and establishes a WebRTC connection through the signaling server to display the remote video.

## High-level flow

1. The car client boots, grabs a Keycloak service token (client credentials), and opens a WebSocket to the signaling server with its `client_id`.
2. The signaling server validates the token, registers the car as available, and waits for an operator to request it.
3. The operator uses the frontend, which logs them into Keycloak. Their bearer token is attached when the UI connects to the signaling server.
4. When the operator selects a car, the frontend creates an SDP offer, which travels through the signaling server to the car client. The car answers and starts pushing video frames.
5. The signaling server relays ICE candidates both ways until the direct peer connection becomes established. Only one operator can be attached to a car at a time; additional operators see an error until the session ends.

Each folder contains its own README with setup instructions and environment variables.

## Quick start (local demo)

The default configuration lets you try the full flow without a real Keycloak server by enabling insecure tokens on the signaling server and pasting `demo` as the operator token in the UI.

1. **Signaling server**
   ```bash
   cd signaling-server
   npm install
   cp .env.example .env  # keep ALLOW_INSECURE_TOKENS=true for local tests
   npm run dev
   ```
2. **Car video client**
   ```bash
   cd car-video-client
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env  # edit SIGNALING_WS_URL if needed
   python main.py
   ```
3. **Frontend**
   ```bash
   cd frontend
   npm install
   cp .env.example .env
   npm run dev
   ```
   Browse to the Vite dev URL, enable manual token mode (`VITE_SKIP_KEYCLOAK=true`), paste `demo` as the token, select the `car-001` entry, and click **Connect**.

Replace the insecure shortcuts with real Keycloak URLs when you are ready to wire everything to an actual identity provider.

# Signaling Server

Node.js server that handles authentication, keeps track of online cars, enforces a single-operator-per-car rule, and relays WebRTC signaling messages between the car client and the frontend.

## Setup

```bash
cd signaling-server
npm install
cp .env.example .env
```

Fill in the Keycloak settings.

For local p2p deployments without a domain, use direct host/IP (for example `http://127.0.0.1:8080`) consistently in all services.

## Running

```bash
npm run dev
```

This starts both the HTTP API (for health checks and listing cars) and the WebSocket endpoint that the car client and frontend connect to.

## Environment variables

| Name | Description |
| --- | --- |
| `PORT` | HTTP/WebSocket port (default `4000`). |
| `PUBLIC_WS_PATH` | WebSocket path (default `/ws`). |
| `KEYCLOAK_JWKS_URL` | JWKS endpoint used to verify JWT signatures. |
| `KEYCLOAK_ISSUER` | Expected issuer within the JWT. |
| `CAR_AUDIENCE` | Expected `aud` claim for car service tokens. |
| `OPERATOR_AUDIENCE` | Expected `aud` claim for operator tokens. |
| `CAR_SERVICE_CLIENT_ID` | Only tokens with this client ID may register as cars. |
| `OPERATOR_REQUIRED_ROLE` | Realm/client role that an operator must have. |
| `ALLOW_INSECURE_TOKENS` | Must be `false` for real protection. `true` disables JWT verification entirely. |
| `PING_INTERVAL_MS` | How often to ping idle sockets (default `25000`). |

For quick local demo without Keycloak, set `ALLOW_INSECURE_TOKENS=true`.

## Secure local mode (no domain)

Use these values in `.env`:

- `KEYCLOAK_JWKS_URL=http://127.0.0.1:8080/realms/cars/protocol/openid-connect/certs`
- `KEYCLOAK_ISSUER=http://127.0.0.1:8080/realms/cars`
- `ALLOW_INSECURE_TOKENS=false`

Also ensure:

- car client uses `KEYCLOAK_TOKEN_URL=http://127.0.0.1:8080/realms/cars/protocol/openid-connect/token`
- frontend uses `VITE_KEYCLOAK_URL=http://127.0.0.1:8080`

`GET /health` returns `{ status: "ok" }`.

`GET /clients` returns an array of connected car metadata so the frontend can show which cars are available or already in a session.

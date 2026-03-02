import http from "http";
import crypto from "crypto";

import cors from "cors";
import dotenv from "dotenv";
import express from "express";
import { WebSocketServer, WebSocket } from "ws";

import { createTokenVerifier, hasRole } from "./token.js";

dotenv.config();

const PORT = Number(process.env.PORT || 4000);
const WS_PATH = process.env.PUBLIC_WS_PATH || "/ws";
const allowInsecure = process.env.ALLOW_INSECURE_TOKENS === "true";
const pingInterval = Number(process.env.PING_INTERVAL_MS || 25000);

const verifyToken = createTokenVerifier({
  jwksUrl: process.env.KEYCLOAK_JWKS_URL,
  issuer: process.env.KEYCLOAK_ISSUER,
  allowInsecure,
});

const app = express();
app.use(cors());
app.use(express.json());

const server = http.createServer(app);
const wss = new WebSocketServer({ server, path: WS_PATH });

const cars = new Map(); // clientId -> { socket, operatorId, connectedAt, tokenSub }
const operators = new Map(); // peerId -> { socket, username, attachedCarId }
const peerMeta = new Map(); // socket -> { id, role, clientId, username }

const send = (socket, payload) => {
  if (socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(payload));
  }
};

const broadcastCarSnapshot = () => {
  const snapshot = Array.from(cars.entries()).map(([clientId, car]) => ({
    clientId,
    status: car.operatorId ? "busy" : "idle",
    connectedAt: car.connectedAt,
    operatorId: car.operatorId,
  }));
  for (const [, operator] of operators) {
    send(operator.socket, { type: "clients", data: snapshot });
  }
};

const registerCar = async (socket, message) => {
  const clientId = message.clientId;
  if (!clientId) {
    throw new Error("clientId is required for car registration");
  }
  const tokenPayload = await verifyToken(
    message.token,
    process.env.CAR_AUDIENCE || process.env.KEYCLOAK_AUDIENCE
  );
  if (
    !allowInsecure &&
    process.env.CAR_SERVICE_CLIENT_ID &&
    tokenPayload.client_id !== process.env.CAR_SERVICE_CLIENT_ID
  ) {
    throw new Error("Token is not allowed to act as a car");
  }

  const existing = cars.get(clientId);
  if (existing) {
    send(existing.socket, {
      type: "error",
      message: "Duplicate car detected, closing previous connection",
    });
    existing.socket.close(4001, "duplicate-car");
  }

  const peerId = crypto.randomUUID();
  peerMeta.set(socket, { id: peerId, role: "car", clientId });
  cars.set(clientId, {
    socket,
    operatorId: null,
    connectedAt: Date.now(),
    tokenSub: tokenPayload.sub,
  });
  send(socket, { type: "registered", role: "car", clientId });
  console.log(`[car] registered ${clientId}`);
  broadcastCarSnapshot();
};

const registerOperator = async (socket, message) => {
  const tokenPayload = await verifyToken(
    message.token,
    process.env.OPERATOR_AUDIENCE || process.env.KEYCLOAK_AUDIENCE
  );
  const requiredRole = process.env.OPERATOR_REQUIRED_ROLE;
  if (!allowInsecure && requiredRole && !hasRole(tokenPayload, requiredRole)) {
    throw new Error("Operator token missing required role");
  }
  const peerId = crypto.randomUUID();
  const username =
    tokenPayload.preferred_username ||
    tokenPayload.email ||
    tokenPayload.sub ||
    "operator";

  peerMeta.set(socket, { id: peerId, role: "operator", username });
  operators.set(peerId, { socket, username, attachedCarId: null });
  send(socket, { type: "registered", role: "operator", username });
  send(socket, {
    type: "clients",
    data: Array.from(cars.entries()).map(([clientId, car]) => ({
      clientId,
      status: car.operatorId ? "busy" : "idle",
      connectedAt: car.connectedAt,
    })),
  });
  console.log(`[operator] ${username} connected`);
};

const ensureAttached = (operator, clientId) => {
  if (!operator) {
    throw new Error("Operator session missing");
  }
  if (!operator.attachedCarId || operator.attachedCarId !== clientId) {
    throw new Error("Operator is not attached to this car");
  }
};

const attachOperatorToCar = (socket, message) => {
  const meta = peerMeta.get(socket);
  if (!meta || meta.role !== "operator") {
    throw new Error("Only operators can request watch");
  }
  const operator = operators.get(meta.id);
  if (!operator) {
    throw new Error("Operator session not found");
  }
  const car = cars.get(message.clientId);
  if (!car) {
    throw new Error("Car not found or offline");
  }
  if (car.operatorId) {
    throw new Error("Car is already in use");
  }
  car.operatorId = meta.id;
  operator.attachedCarId = message.clientId;
  send(operator.socket, {
    type: "watch-accepted",
    clientId: message.clientId,
  });
  send(car.socket, {
    type: "operator-ready",
    clientId: message.clientId,
    operatorId: meta.id,
  });
  console.log(
    `[session] operator ${operator.username} -> car ${message.clientId}`
  );
  broadcastCarSnapshot();
};

const relayToPeer = (fromSocket, payload) => {
  const meta = peerMeta.get(fromSocket);
  if (!meta) {
    throw new Error("Peer not registered");
  }
  if (payload.type === "offer") {
    if (meta.role !== "operator") {
      throw new Error("Only operators can send offers");
    }
    const operator = operators.get(meta.id);
    ensureAttached(operator, payload.clientId);
    const car = cars.get(payload.clientId);
    send(car.socket, {
      type: "offer",
      sdp: payload.sdp,
      sdpType: payload.sdpType,
    });
  } else if (payload.type === "answer") {
    if (meta.role !== "car") {
      throw new Error("Only cars can send answers");
    }
    const car = cars.get(meta.clientId);
    if (!car?.operatorId) {
      throw new Error("No operator attached to this car");
    }
    const operator = operators.get(car.operatorId);
    send(operator.socket, {
      type: "answer",
      sdp: payload.sdp,
      sdpType: payload.sdpType,
    });
  } else if (payload.type === "candidate") {
    if (meta.role === "car") {
      const car = cars.get(meta.clientId);
      if (!car?.operatorId) {
        return;
      }
      const operator = operators.get(car.operatorId);
      send(operator.socket, {
        type: "candidate",
        clientId: meta.clientId,
        candidate: payload.candidate,
      });
    } else if (meta.role === "operator") {
      const operator = operators.get(meta.id);
      ensureAttached(operator, payload.clientId);
      const car = cars.get(payload.clientId);
      send(car.socket, {
        type: "candidate",
        candidate: payload.candidate,
      });
    }
  }
};

const releaseSession = (socket) => {
  const meta = peerMeta.get(socket);
  if (!meta) {
    return;
  }
  if (meta.role === "operator") {
    const operator = operators.get(meta.id);
    if (operator?.attachedCarId) {
      const car = cars.get(operator.attachedCarId);
      if (car) {
        car.operatorId = null;
        send(car.socket, { type: "operator-disconnected" });
      }
      operator.attachedCarId = null;
      send(socket, { type: "released" });
    }
  } else if (meta.role === "car") {
    const car = cars.get(meta.clientId);
    if (car?.operatorId) {
      const operator = operators.get(car.operatorId);
      if (operator) {
        operator.attachedCarId = null;
        send(operator.socket, {
          type: "car-disconnected",
          clientId: meta.clientId,
        });
      }
      car.operatorId = null;
    }
  }
  broadcastCarSnapshot();
};

const cleanupPeer = (socket) => {
  const meta = peerMeta.get(socket);
  if (!meta) {
    return;
  }
  if (meta.role === "car") {
    console.log(`[car] disconnected ${meta.clientId}`);
    releaseSession(socket);
    cars.delete(meta.clientId);
  } else if (meta.role === "operator") {
    console.log(`[operator] disconnected ${meta.id}`);
    releaseSession(socket);
    operators.delete(meta.id);
  }
  peerMeta.delete(socket);
  broadcastCarSnapshot();
};

wss.on("connection", (socket) => {
  socket.isAlive = true;
  socket.on("pong", () => {
    socket.isAlive = true;
  });

  socket.on("message", async (data) => {
    try {
      const message = JSON.parse(data.toString());
      switch (message.type) {
        case "register":
          if (message.role === "car") {
            await registerCar(socket, message);
          } else if (message.role === "operator") {
            await registerOperator(socket, message);
          } else {
            throw new Error("Unknown role");
          }
          break;
        case "watch":
          attachOperatorToCar(socket, message);
          break;
        case "offer":
        case "answer":
        case "candidate":
          relayToPeer(socket, message);
          break;
        case "release":
          releaseSession(socket);
          break;
        case "ping":
          send(socket, { type: "pong" });
          break;
        default:
          throw new Error(`Unsupported message type: ${message.type}`);
      }
    } catch (err) {
      console.error("[ws] error:", err.message);
      send(socket, { type: "error", message: err.message });
    }
  });

  socket.on("close", () => cleanupPeer(socket));
  socket.on("error", (err) => {
    console.error("[ws] socket error", err);
  });
});

const interval = setInterval(() => {
  wss.clients.forEach((socket) => {
    if (socket.isAlive === false) {
      return socket.terminate();
    }
    socket.isAlive = false;
    socket.ping();
  });
}, pingInterval);

wss.on("close", () => {
  clearInterval(interval);
});

app.get("/health", (_req, res) => {
  res.json({ status: "ok" });
});

app.get("/clients", (_req, res) => {
  const payload = Array.from(cars.entries()).map(([clientId, car]) => ({
    clientId,
    status: car.operatorId ? "busy" : "idle",
    connectedAt: car.connectedAt,
  }));
  res.json(payload);
});

server.listen(PORT, () => {
  console.log(
    `[signaling] HTTP on :${PORT}, WS path ${WS_PATH}, insecure=${allowInsecure}`
  );
});

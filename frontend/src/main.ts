import Keycloak, { KeycloakInitOptions } from "keycloak-js";
import "./style.css";

type ClientInfo = {
  clientId: string;
  status: "idle" | "busy";
  connectedAt: number;
};

type AppConfig = {
  signalingWsUrl: string;
  signalingHttpUrl: string;
  keycloakUrl: string;
  keycloakRealm: string;
  keycloakClientId: string;
  skipKeycloak: boolean;
  iceServers: RTCIceServer[];
};

const defaultIceServers: RTCIceServer[] = [
  { urls: ["stun:stun.l.google.com:19302"] },
];

const normalizeIceServers = (raw: unknown): RTCIceServer[] => {
  if (Array.isArray(raw)) {
    return raw
      .map((entry) => {
        if (typeof entry === "string") {
          return { urls: [entry] };
        }
        if (entry && typeof entry === "object") {
          const candidate = entry as RTCIceServer;
          const urls = candidate.urls;
          if (typeof urls === "string") {
            return { ...candidate, urls: [urls] };
          }
          if (Array.isArray(urls) && urls.length) {
            return candidate;
          }
        }
        return null;
      })
      .filter((entry): entry is RTCIceServer => Boolean(entry));
  }
  if (typeof raw === "string" && raw.trim().length) {
    const urls = raw.split(",").map((url) => url.trim()).filter(Boolean);
    return urls.length ? [{ urls }] : defaultIceServers;
  }
  if (raw && typeof raw === "object") {
    const candidate = raw as RTCIceServer;
    if (typeof candidate.urls === "string") {
      return [{ ...candidate, urls: [candidate.urls] }];
    }
    if (Array.isArray(candidate.urls)) {
      return [candidate];
    }
  }
  return defaultIceServers;
};

const loadIceServersFromEnv = (value: string | undefined): RTCIceServer[] => {
  if (!value) {
    return defaultIceServers;
  }
  try {
    const parsed = JSON.parse(value);
    const normalized = normalizeIceServers(parsed);
    if (normalized.length) {
      return normalized;
    }
  } catch {
    // Not JSON, fall through to treat it as plain text.
  }
  const normalized = normalizeIceServers(value);
  return normalized.length ? normalized : defaultIceServers;
};

const config: AppConfig = {
  signalingWsUrl:
    import.meta.env.VITE_SIGNALING_WS_URL || "ws://localhost:4000/ws",
  signalingHttpUrl:
    import.meta.env.VITE_SIGNALING_HTTP_URL || "http://localhost:4000",
  keycloakUrl: import.meta.env.VITE_KEYCLOAK_URL || "http://localhost:8080",
  keycloakRealm: import.meta.env.VITE_KEYCLOAK_REALM || "cars",
  keycloakClientId:
    import.meta.env.VITE_KEYCLOAK_CLIENT_ID || "car-operator-ui",
  skipKeycloak: import.meta.env.VITE_SKIP_KEYCLOAK === "true",
  iceServers: loadIceServersFromEnv(import.meta.env.VITE_ICE_SERVERS),
};

const app = document.querySelector<HTMLDivElement>("#app");
if (!app) {
  throw new Error("Missing #app container");
}

app.innerHTML = `
  <div class="card">
    <h1>Remote Car Viewer</h1>
    <p class="status" id="authStatus">Authenticating…</p>
    <div id="manualToken" style="display: none;">
      <p>Keycloak skipped. Paste a token (or enter <code>demo</code> when insecure mode is enabled on the server).</p>
      <textarea id="tokenInput" class="token-input"></textarea>
      <button id="useTokenBtn">Use token</button>
    </div>
    <div class="controls">
      <label for="carSelect">Target car:</label>
      <select id="carSelect">
        <option value="">-- unavailable --</option>
      </select>
      <button id="connectBtn" disabled>Connect</button>
      <button id="releaseBtn" class="secondary" disabled>Release</button>
      <span id="sessionStatus">Idle</span>
    </div>
    <div class="row" style="margin-top: 1rem;">
      <video id="remoteVideo" autoplay playsinline></video>
    </div>
    <div class="log" id="log"></div>
  </div>
`;

const carSelect = document.getElementById("carSelect") as HTMLSelectElement;
const connectBtn = document.getElementById("connectBtn") as HTMLButtonElement;
const releaseBtn = document.getElementById("releaseBtn") as HTMLButtonElement;
const statusLabel = document.getElementById("sessionStatus") as HTMLElement;
const authStatus = document.getElementById("authStatus") as HTMLElement;
const logBox = document.getElementById("log") as HTMLElement;
const manualTokenContainer = document.getElementById(
  "manualToken"
) as HTMLDivElement;
const tokenInput = document.getElementById("tokenInput") as HTMLTextAreaElement;
const useTokenBtn = document.getElementById("useTokenBtn") as HTMLButtonElement;
const videoElement = document.getElementById("remoteVideo") as HTMLVideoElement;

let keycloak: Keycloak | null = null;
let token: string | null = null;
let ws: WebSocket | null = null;
let pc: RTCPeerConnection | null = null;
let currentClientId: string | null = null;
let refreshInterval: number | undefined;

const log = (line: string) => {
  const time = new Date().toLocaleTimeString();
  logBox.textContent = `[${time}] ${line}\n${logBox.textContent ?? ""}`.slice(
    0,
    2000
  );
};

const setSessionState = (state: string) => {
  statusLabel.textContent = state;
};

const populateCars = (cars: ClientInfo[]) => {
  const selected = carSelect.value;
  carSelect.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = cars.length ? "Select a car" : "No cars online";
  carSelect.appendChild(placeholder);
  cars.forEach((car) => {
    const option = document.createElement("option");
    option.value = car.clientId;
    const state = car.status === "busy" ? "busy" : "idle";
    option.textContent = `${car.clientId} (${state})`;
    option.disabled = car.status === "busy";
    carSelect.appendChild(option);
  });
  if (
    selected &&
    Array.from(carSelect.options).some((opt) => opt.value === selected)
  ) {
    carSelect.value = selected;
  }
  connectBtn.disabled = !carSelect.value;
};

carSelect.addEventListener("change", () => {
  connectBtn.disabled = !carSelect.value;
});

const buildPeerConnection = () => {
  if (pc) {
    pc.close();
  }
  pc = new RTCPeerConnection({
    iceServers: config.iceServers.length ? config.iceServers : defaultIceServers,
  });
  pc.addTransceiver("video", { direction: "recvonly" }); // ensure offer includes a video m-line
  pc.ontrack = (event) => {
    const [stream] = event.streams;
    videoElement.srcObject = stream;
  };
  pc.onicecandidate = (event) => {
    if (event.candidate && ws && currentClientId) {
      ws.send(
        JSON.stringify({
          type: "candidate",
          clientId: currentClientId,
          candidate: event.candidate.toJSON(),
        })
      );
    }
  };
  pc.onconnectionstatechange = () => {
    log(`Peer connection state: ${pc?.connectionState}`);
    if (pc?.connectionState === "disconnected") {
      releaseSession();
    }
  };
  return pc;
};

const releaseSession = () => {
  if (pc) {
    pc.close();
    pc = null;
  }
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "release" }));
  }
  currentClientId = null;
  releaseBtn.disabled = true;
  connectBtn.disabled = !carSelect.value;
  setSessionState("Idle");
  videoElement.srcObject = null;
};

releaseBtn.addEventListener("click", () => {
  releaseSession();
});

connectBtn.addEventListener("click", () => {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    log("WebSocket is not connected");
    return;
  }
  const target = carSelect.value;
  if (!target) {
    return;
  }
  ws.send(JSON.stringify({ type: "watch", clientId: target }));
  setSessionState("Requesting session…");
});

const handleWatchAccepted = async (message: any) => {
  if (!ws) {
    return;
  }
  currentClientId = message.clientId;
  releaseBtn.disabled = false;
  connectBtn.disabled = true;
  setSessionState(`Connecting to ${currentClientId}`);
  const peer = buildPeerConnection();
  const offer = await peer.createOffer();
  await peer.setLocalDescription(offer);
  ws.send(
    JSON.stringify({
      type: "offer",
      clientId: currentClientId,
      sdp: offer.sdp,
      sdpType: offer.type,
    })
  );
  log(`Sent offer to ${currentClientId}`);
};

const ensureSocket = () => {
  if (!token) {
    log("Token missing, cannot open socket");
    return;
  }
  ws?.close();
  ws = new WebSocket(config.signalingWsUrl);
  ws.onopen = () => {
    log("Connected to signaling server");
    ws?.send(
      JSON.stringify({
        type: "register",
        role: "operator",
        token,
      })
    );
  };
  ws.onmessage = async (event) => {
    const message = JSON.parse(event.data);
    switch (message.type) {
      case "registered":
        authStatus.textContent = `Authenticated as ${message.username || "operator"}`;
        break;
      case "clients":
        populateCars(message.data);
        break;
      case "watch-accepted":
        await handleWatchAccepted(message);
        break;
      case "answer":
        if (pc) {
          await pc.setRemoteDescription({
            type: message.sdpType,
            sdp: message.sdp,
          });
          setSessionState("Streaming");
          log("Received answer");
        }
        break;
      case "candidate":
        if (pc && message.candidate) {
          await pc.addIceCandidate(message.candidate);
        }
        break;
      case "car-disconnected":
        log(`Car ${message.clientId} disconnected`);
        releaseSession();
        break;
      case "operator-disconnected":
        log("Operator detached");
        releaseSession();
        break;
      case "error":
        log(`Error: ${message.message}`);
        setSessionState("Error");
        break;
      default:
        break;
    }
  };
  ws.onclose = () => {
    log("Signaling socket closed");
    releaseSession();
    setTimeout(() => ensureSocket(), 3000);
  };
};

let keycloakInitialized = false;

const hasOauthParams =
  typeof window !== "undefined" &&
  new URLSearchParams(window.location.search).has("code");

const logOauthDebugInfo = () => {
  if (!hasOauthParams) {
    return;
  }
  const params = new URLSearchParams(window.location.search);
  const state = params.get("state");
  const code = params.get("code");
  const storageEntry = state
    ? localStorage.getItem(`kc-callback-${state}`)
    : null;
  console.info(
    "[Keycloak] detected OAuth params",
    JSON.stringify(
      {
        state,
        codePresent: Boolean(code),
        storedStatePresent: Boolean(storageEntry),
      },
      null,
      2
    )
  );
};

const startWithKeycloak = async () => {
  if (keycloakInitialized) return;
  keycloakInitialized = true;
  logOauthDebugInfo();
  authStatus.textContent = "Redirecting to Keycloak…";
  keycloak = new Keycloak({
    url: config.keycloakUrl,
    realm: config.keycloakRealm,
    clientId: config.keycloakClientId,
  });
  keycloak.onAuthError = (error) => {
    console.error("Keycloak auth error", error);
  };
  keycloak.onAuthSuccess = () => {
    console.info("Keycloak auth success");
  };
  const redirectUri = window.location.origin + window.location.pathname;
  const initOptions: KeycloakInitOptions = {
    checkLoginIframe: false,
    pkceMethod: "S256",
    responseMode: "query",
    silentCheckSsoFallback: false,
    redirectUri,
    enableLogging: true,
    useNonce: false, // Keycloak server does not echo nonce back for this client, so disable verification to avoid spurious loops
  };
  if (!hasOauthParams) {
    initOptions.onLoad = "login-required";
  }
  const authenticated = await keycloak.init(initOptions);
  if (!authenticated) {
    if (hasOauthParams) {
      throw new Error("Keycloak returned without authentication despite code");
    }
    await keycloak.login();
    return;
  }
  token = keycloak.token ?? null;
  authStatus.textContent = `Hello, ${keycloak.tokenParsed?.preferred_username || "operator"}`;
  ensureSocket();
  refreshInterval = window.setInterval(async () => {
    if (!keycloak) {
      return;
    }
    try {
      const refreshed = await keycloak.updateToken(30);
      if (refreshed) {
        token = keycloak.token ?? token;
      }
    } catch (err) {
      console.error("Failed to refresh token", err);
      authStatus.textContent = "Session expired";
    }
  }, 10000);
};

const startWithManualToken = () => {
  manualTokenContainer.style.display = "block";
  authStatus.textContent = "Waiting for manual token…";
  useTokenBtn.addEventListener("click", () => {
    token = tokenInput.value.trim();
    if (!token) {
      log("Token is empty");
      return;
    }
    authStatus.textContent = "Using static token";
    ensureSocket();
  });
};

if (config.skipKeycloak) {
  startWithManualToken();
} else {
  startWithKeycloak().catch((err) => {
    console.error(err);
    authStatus.textContent = "Failed to init Keycloak";
  });
}

window.addEventListener("beforeunload", () => {
  if (refreshInterval) {
    clearInterval(refreshInterval);
  }
  ws?.close();
  pc?.close();
});

type HelloMsg = { type: "hello"; clientId: string; cameras: number };
type AnswerMsg = { type: "answer"; cameraIndex: number; sdp: string; sdpType: RTCSdpType };
type ErrorMsg = { type: "error"; message: string };

type ServerMsg = HelloMsg | AnswerMsg | ErrorMsg | { type: string; [k: string]: unknown };

const $ = (sel: string) => document.querySelector(sel);

declare const __WS_URL__: string;

function getWsUrl(): string {
  const input = $("#wsUrl") as HTMLInputElement | null;
  const v = input?.value?.trim();
  if (v) return v;
  if (typeof __WS_URL__ === "string" && __WS_URL__.trim()) return __WS_URL__.trim();
  const host = window.location.hostname || "127.0.0.1";
  return `ws://${host}:8765`;
}

function logLine(msg: string) {
  const el = $("#log");
  if (!el) return;
  el.textContent += `${msg}\n`;
  el.scrollTop = el.scrollHeight;
}

function setStatus(msg: string) {
  const el = $("#status");
  if (el) el.textContent = msg;
}

function createVideoTile(idx: number): HTMLVideoElement {
  const grid = $("#grid");
  if (!grid) throw new Error("Missing grid");
  const wrap = document.createElement("div");
  wrap.className = "tile";

  const label = document.createElement("div");
  label.className = "label";
  label.textContent = `Camera ${idx}`;

  const v = document.createElement("video");
  v.autoplay = true;
  v.playsInline = true;
  v.muted = true;
  v.controls = false;

  wrap.appendChild(label);
  wrap.appendChild(v);
  grid.appendChild(wrap);
  return v;
}

async function negotiateCamera(ws: WebSocket, cameraIndex: number, videoEl: HTMLVideoElement) {
  const pc = new RTCPeerConnection({
    iceServers: [{ urls: ["stun:stun.l.google.com:19302"] }]
  });

  pc.ontrack = (ev) => {
    const [stream] = ev.streams;
    if (stream) {
      videoEl.srcObject = stream;
      logLine(`cam${cameraIndex}: track received`);
    }
  };

  pc.oniceconnectionstatechange = () => {
    logLine(`cam${cameraIndex}: ice=${pc.iceConnectionState}`);
  };

  pc.onconnectionstatechange = () => {
    logLine(`cam${cameraIndex}: conn=${pc.connectionState}`);
  };

  // Server is sending only video; we don't add local tracks.
  pc.addTransceiver("video", { direction: "recvonly" });

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);

  ws.send(
    JSON.stringify({
      type: "offer",
      cameraIndex,
      sdp: offer.sdp,
      sdpType: offer.type
    })
  );

  const answer: AnswerMsg = await new Promise((resolve, reject) => {
    const onMsg = (ev: MessageEvent) => {
      try {
        const msg = JSON.parse(String(ev.data)) as ServerMsg;
        if (msg.type === "answer" && (msg as AnswerMsg).cameraIndex === cameraIndex) {
          ws.removeEventListener("message", onMsg);
          resolve(msg as AnswerMsg);
        } else if (msg.type === "error") {
          ws.removeEventListener("message", onMsg);
          reject(new Error((msg as ErrorMsg).message));
        }
      } catch {
        // ignore parse errors here
      }
    };
    ws.addEventListener("message", onMsg);
    setTimeout(() => {
      ws.removeEventListener("message", onMsg);
      reject(new Error("Timed out waiting for answer"));
    }, 15000);
  });

  await pc.setRemoteDescription({ type: answer.sdpType, sdp: answer.sdp });
  return pc;
}

async function connect() {
  const connectBtn = $("#connect") as HTMLButtonElement | null;
  if (connectBtn) connectBtn.disabled = true;

  setStatus("connecting…");
  const wsUrl = getWsUrl();
  logLine(`ws: ${wsUrl}`);

  const ws = new WebSocket(wsUrl);
  const pcs: RTCPeerConnection[] = [];

  const cleanup = async () => {
    for (const pc of pcs) pc.close();
    pcs.length = 0;
    if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "close" }));
    ws.close();
    
    const grid = $("#grid");
    if (grid) grid.innerHTML = "";
    
    if (connectBtn) connectBtn.disabled = false;
  };

  const hello: HelloMsg = await new Promise((resolve, reject) => {
    ws.onerror = () => reject(new Error("WebSocket error"));
    ws.onclose = () => reject(new Error("WebSocket closed before hello"));
    ws.onmessage = (ev) => {
      const msg = JSON.parse(String(ev.data)) as ServerMsg;
      if (msg.type === "hello") resolve(msg as HelloMsg);
      if (msg.type === "error") reject(new Error((msg as ErrorMsg).message));
    };
    ws.onopen = () => {
      // wait for hello
    };
  });

  setStatus(`connected (clientId=${hello.clientId})`);
  logLine(`server says cameras=${hello.cameras}`);

  const grid = $("#grid");
  if (grid) grid.innerHTML = "";

  for (let i = 0; i < hello.cameras; i++) {
    const v = createVideoTile(i);
    try {
      const pc = await negotiateCamera(ws, i, v);
      pcs.push(pc);
    } catch (e) {
      logLine(`cam${i}: failed: ${(e as Error).message}`);
    }
  }

  const disconnectBtn = $("#disconnect") as HTMLButtonElement | null;
  if (disconnectBtn) {
    disconnectBtn.onclick = () => {
      setStatus("disconnecting…");
      cleanup().then(() => setStatus("disconnected"));
    };
  }

  ws.addEventListener("close", () => {
    setStatus("disconnected");
    if (connectBtn) connectBtn.disabled = false;
  });
}

window.addEventListener("DOMContentLoaded", () => {
  const btn = $("#connect") as HTMLButtonElement | null;
  if (btn) btn.onclick = () => connect().catch((e) => setStatus(`error: ${(e as Error).message}`));
});


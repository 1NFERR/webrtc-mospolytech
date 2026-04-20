// src/main.ts
var $ = (sel) => document.querySelector(sel);
function getWsUrl() {
  const input = $("#wsUrl");
  const v = input?.value?.trim();
  if (v) return v;
  if ("".trim()) return "".trim();
  const host = window.location.hostname || "127.0.0.1";
  return `ws://${host}:8765`;
}
function logLine(msg) {
  const el = $("#log");
  if (!el) return;
  el.textContent += `${msg}
`;
  el.scrollTop = el.scrollHeight;
}
function setStatus(msg) {
  const el = $("#status");
  if (el) el.textContent = msg;
}
function createVideoTile(idx) {
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
async function negotiateCamera(ws, cameraIndex, videoEl) {
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
  const answer = await new Promise((resolve, reject) => {
    const onMsg = (ev) => {
      try {
        const msg = JSON.parse(String(ev.data));
        if (msg.type === "answer" && msg.cameraIndex === cameraIndex) {
          ws.removeEventListener("message", onMsg);
          resolve(msg);
        } else if (msg.type === "error") {
          ws.removeEventListener("message", onMsg);
          reject(new Error(msg.message));
        }
      } catch {
      }
    };
    ws.addEventListener("message", onMsg);
    setTimeout(() => {
      ws.removeEventListener("message", onMsg);
      reject(new Error("Timed out waiting for answer"));
    }, 15e3);
  });
  await pc.setRemoteDescription({ type: answer.sdpType, sdp: answer.sdp });
  return pc;
}
async function connect() {
  const connectBtn = $("#connect");
  if (connectBtn) connectBtn.disabled = true;
  setStatus("connecting\u2026");
  const wsUrl = getWsUrl();
  logLine(`ws: ${wsUrl}`);
  const ws = new WebSocket(wsUrl);
  const pcs = [];
  const cleanup = async () => {
    for (const pc of pcs) pc.close();
    pcs.length = 0;
    if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "close" }));
    ws.close();
    const grid2 = $("#grid");
    if (grid2) grid2.innerHTML = "";
    if (connectBtn) connectBtn.disabled = false;
  };
  const hello = await new Promise((resolve, reject) => {
    ws.onerror = () => reject(new Error("WebSocket error"));
    ws.onclose = () => reject(new Error("WebSocket closed before hello"));
    ws.onmessage = (ev) => {
      const msg = JSON.parse(String(ev.data));
      if (msg.type === "hello") resolve(msg);
      if (msg.type === "error") reject(new Error(msg.message));
    };
    ws.onopen = () => {
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
      logLine(`cam${i}: failed: ${e.message}`);
    }
  }
  const disconnectBtn = $("#disconnect");
  if (disconnectBtn) {
    disconnectBtn.onclick = () => {
      setStatus("disconnecting\u2026");
      cleanup().then(() => setStatus("disconnected"));
    };
  }
  ws.addEventListener("close", () => {
    setStatus("disconnected");
    if (connectBtn) connectBtn.disabled = false;
  });
}
window.addEventListener("DOMContentLoaded", () => {
  const btn = $("#connect");
  if (btn) btn.onclick = () => connect().catch((e) => setStatus(`error: ${e.message}`));
});

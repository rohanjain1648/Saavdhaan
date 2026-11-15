// Saavdhaan live call screen. Talks to /ws/call on the host that served this page, using the
// messages in backend/contract.py, so the same files work against mock/ and the real backend.
"use strict";

// ---- Contract (mirrors backend/contract.py) ---------------------------------------------------
const SAMPLE_RATE = 16000;
const FRAME_BYTES = 1024;
const CAUTION_AT = 40;
const DANGER_AT = 70;
const START_MESSAGE = { type: "start", language: "hi-IN", warn_language: "hi-IN" };

const TACTIC_NAMES = {
  authority_impersonation: "Pretends to be police",
  digital_arrest: "Claims “digital arrest”",
  urgency_threat: "Threatens arrest",
  isolation_secrecy: "Demands secrecy",
  money_transfer: "Asks to transfer money",
  credential_request: "Asks for OTP",
  remote_access_app: "Asks to install an app",
};

// While the spoken warning plays, send silence instead of the microphone, so the guardian's own
// voice (from the laptop speaker) is not transcribed and scored as part of the call.
const MUTE_MIC_DURING_WARNING = true;
const STOP_TIMEOUT_MS = 20000;
const LISTEN_TIMEOUT_MS = 30000; // the real backend may synthesize the warning audio before it listens
const FRAMES_PER_SECOND = SAMPLE_RATE * 2 / FRAME_BYTES; // 31.25
const SLOW_AUDIO_RATIO = 0.9;
const TICKS = 48;

// ---- Elements --------------------------------------------------------------------------------
const $ = (id) => document.getElementById(id);
const ui = {
  body: document.body,
  headline: $("headline"),
  statusText: $("status-text"),
  clock: $("clock"),
  bars: Array.from(document.querySelectorAll("#bars i")),
  start: $("start"),
  stop: $("stop"),
  errors: $("errors"),
  gauge: $("gauge"),
  score: $("score"),
  level: $("level"),
  tactics: $("tactics"),
  transcript: $("transcript"),
  warning: $("warning"),
  warningTime: $("warning-time"),
  warningText: $("warning-text"),
  warningAudio: $("warning-audio"),
  alert: $("alert"),
  alertTitle: $("alert-title"),
  alertText: $("alert-text"),
  alertTag: $("alert-tag"),
  alertFo: $("alert-fo"),
  summary: $("summary"),
  summaryClose: $("summary-close"),
  sumPeak: $("sum-peak"),
  sumFirst: $("sum-first"),
  sumLength: $("sum-length"),
  sumTactics: $("sum-tactics"),
  sumEvidence: $("sum-evidence"),
  sumAdvice: $("sum-advice"),
};

// Frame counters, readable from the console as saavdhaanStats.
const stats = { framesSent: 0, bytesSent: 0, silentFrames: 0, wrongSizeFrames: 0 };
window.saavdhaanStats = stats;

// ---- Helpers ---------------------------------------------------------------------------------
const levelFor = (score) => (score >= DANGER_AT ? "danger" : score >= CAUTION_AT ? "caution" : "safe");
const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));
const LEVEL_WORD = { safe: "Safe", caution: "Caution", danger: "Danger" };
const DEVANAGARI = /[ऀ-ॿ]/;

function fmt(ms) {
  if (typeof ms !== "number" || !isFinite(ms) || ms < 0) return "";
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function checkIcon() {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  const path = document.createElementNS(ns, "path");
  path.setAttribute("d", "M5 12.5l4.5 4.5L19 7.5");
  svg.append(path);
  return svg;
}

// ---- Errors: never silent --------------------------------------------------------------------
function showError(message, { title = "Problem", key } = {}) {
  if (key) {
    const old = ui.errors.querySelector(`[data-key="${key}"]`);
    if (old) old.remove();
  }
  const box = el("div", "err");
  if (key) box.dataset.key = key;
  const p = el("p");
  p.append(el("strong", "", title), document.createTextNode(String(message)));
  const close = el("button", "", "Dismiss");
  close.type = "button";
  close.addEventListener("click", () => box.remove());
  box.append(p, close);
  ui.errors.append(box);
}

function clearErrors() {
  ui.errors.replaceChildren();
}

window.addEventListener("error", (e) => showError(e.message || "Unknown script error.", { title: "Screen error" }));
window.addEventListener("unhandledrejection", (e) =>
  showError((e.reason && e.reason.message) || String(e.reason), { title: "Screen error" }));

// ---- Gauge -----------------------------------------------------------------------------------
const gauge = { ticks: [], shown: 0, target: 0, lastFrame: 0 };

function buildGauge() {
  const ns = "http://www.w3.org/2000/svg";
  const cx = 200, cy = 200, r1 = 156, r2 = 190, sweep = 240;
  const zoneColor = { safe: "var(--teal)", caution: "var(--saffron)", danger: "var(--sindoor)" };
  const polar = (deg, r) => {
    const a = (deg * Math.PI) / 180;
    return [cx + r * Math.sin(a), cy - r * Math.cos(a)];
  };
  for (let i = 0; i < TICKS; i++) {
    const deg = -sweep / 2 + (sweep * (i + 0.5)) / TICKS;
    const [x1, y1] = polar(deg, r1);
    const [x2, y2] = polar(deg, r2);
    const line = document.createElementNS(ns, "line");
    line.setAttribute("class", "tick");
    line.setAttribute("x1", x1.toFixed(2));
    line.setAttribute("y1", y1.toFixed(2));
    line.setAttribute("x2", x2.toFixed(2));
    line.setAttribute("y2", y2.toFixed(2));
    line.style.stroke = zoneColor[levelFor(((i + 0.5) / TICKS) * 100)];
    line.style.opacity = "0.16";
    ui.gauge.append(line);
    gauge.ticks.push(line);
  }
  for (const value of [CAUTION_AT, DANGER_AT]) {
    const [x, y] = polar(-sweep / 2 + (sweep * value) / 100, r2 + 22);
    const text = document.createElementNS(ns, "text");
    text.setAttribute("class", "mark");
    text.setAttribute("x", x.toFixed(1));
    text.setAttribute("y", (y + 5).toFixed(1));
    text.textContent = String(value);
    ui.gauge.append(text);
  }
}

function drawGauge() {
  const per = 100 / TICKS;
  gauge.ticks.forEach((tick, i) => {
    const lit = clamp((gauge.shown - i * per) / per, 0, 1);
    tick.style.opacity = (0.16 + 0.84 * lit).toFixed(3);
  });
  ui.score.textContent = String(Math.round(gauge.shown));
}

// ---- Tactics ---------------------------------------------------------------------------------
const tacticItems = {};

function buildTactics() {
  for (const [id, name] of Object.entries(TACTIC_NAMES)) {
    const li = el("li");
    li.dataset.tactic = id;
    const ind = el("span", "ind");
    ind.append(checkIcon());
    li.append(ind, el("span", "", name));
    ui.tactics.append(li);
    tacticItems[id] = li;
  }
}

// ---- Per-call state --------------------------------------------------------------------------
let call = null;

function newCall() {
  return {
    ws: null,
    url: "",
    mic: null,
    phase: "connecting", // connecting | listening | stopping | ended | dropped
    opened: false,
    streaming: false,
    startedAt: 0,
    endedAt: 0,
    level: "safe",
    peakLevel: "safe",
    tactics: new Set(),
    evidence: [],
    lines: [],
    warned: false,
    muted: false,
    muteTimer: null,
    audio: null,
    audioUrl: "",
    gotSummary: false,
    gotEnded: false,
    stopTimer: null,
    timedOut: false,
    stalled: false,
    connectTimer: null,
    streamStart: 0,
    streamFrames: 0,
    ctxStart: 0,
    paceWarned: false,
  };
}

function setPhase(phase) {
  if (call) call.phase = phase;
  render();
}

function headlineText() {
  if (!call) return "Ready to listen to a call";
  const { phase, level, warned, peakLevel } = call;
  if (phase === "dropped") return call.opened ? "Connection lost. Not listening." : "Could not connect";
  if (warned) return "Scam call. Saavdhaan stepped in.";
  if (phase === "connecting") return call.stalled ? "Not listening to the call" : "Connecting to the call…";
  if (phase === "ended") {
    if (!call.lines.length) return "Call ended. No speech was transcribed.";
    if (peakLevel === "danger") return "Call ended. It looked like a scam.";
    if (peakLevel === "caution") return "Call ended. Some warning signs heard.";
    return "Call ended. Nothing suspicious heard.";
  }
  if (phase === "stopping") return "Ending the call…";
  if (level === "danger") return "This call looks like a scam";
  if (level === "caution") return "This call sounds suspicious";
  return "Listening to the call";
}

function statusText() {
  if (!call) return "Microphone off";
  switch (call.phase) {
    case "connecting": return call.stalled ? "Not listening" : "Connecting";
    case "listening": return call.muted ? "Warning playing, microphone paused" : "Listening";
    case "stopping": return "Ending call";
    case "ended": return "Call ended";
    case "dropped": return "Disconnected";
    default: return "";
  }
}

function render() {
  const phase = call ? call.phase : "idle";
  ui.body.dataset.phase = phase;
  ui.body.dataset.level = call ? call.level : "safe";
  ui.body.classList.toggle("stalled", Boolean(call && call.stalled && phase === "connecting"));
  ui.headline.textContent = headlineText();
  ui.statusText.textContent = statusText();
  ui.level.textContent = LEVEL_WORD[call ? call.level : "safe"];
  const active = phase === "connecting" || phase === "listening";
  ui.start.hidden = active || phase === "stopping";
  ui.stop.hidden = !active;
  ui.start.textContent = call ? "Start a new call" : "Start listening";
  updateClock();
}

function updateClock() {
  if (!call || !call.startedAt) {
    ui.clock.textContent = "";
    return;
  }
  const end = call.endedAt || performance.now();
  ui.clock.textContent = fmt(end - call.startedAt);
}

// ---- Microphone ------------------------------------------------------------------------------
async function openMic() {
  if (!window.isSecureContext || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    throw new Error("The microphone only works on a secure page. Open http://localhost:8000 in Chrome.");
  }
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    video: false,
  });
  let ctx;
  try {
    ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
  } catch {
    ctx = new AudioContext();
  }
  let source;
  try {
    source = ctx.createMediaStreamSource(stream);
  } catch {
    // Some browsers refuse to connect a microphone to a context at a different rate.
    await ctx.close();
    ctx = new AudioContext();
    source = ctx.createMediaStreamSource(stream);
  }
  await ctx.audioWorklet.addModule("pcm-worklet.js");
  const node = new AudioWorkletNode(ctx, "pcm16-framer", {
    numberOfInputs: 1,
    numberOfOutputs: 1,
    outputChannelCount: [1],
    channelCount: 1,
    channelCountMode: "explicit",
    channelInterpretation: "speakers",
    processorOptions: { targetRate: SAMPLE_RATE, frameBytes: FRAME_BYTES },
  });
  const sink = ctx.createGain();
  sink.gain.value = 0; // the worklet must be pulled by the graph, but nothing should be heard
  source.connect(node).connect(sink).connect(ctx.destination);
  if (ctx.state === "suspended") await ctx.resume();
  const mic = { stream, ctx, node, source };
  node.port.onmessage = (e) => onFrame(mic, e.data);
  return mic;
}

function closeMic(c) {
  const mic = c && c.mic;
  if (!mic) return;
  c.mic = null;
  try { mic.node.port.postMessage("stop"); } catch { /* already gone */ }
  mic.stream.getTracks().forEach((t) => t.stop());
  mic.ctx.close().catch(() => {});
  level.target = 0;
}

function micErrorMessage(err) {
  const name = err && err.name;
  if (name === "NotAllowedError" || name === "SecurityError") {
    return "Microphone access was blocked. Allow the microphone for this page (the icon at the left of the address bar), then press Start again.";
  }
  if (name === "NotFoundError" || name === "OverconstrainedError") {
    return "No microphone was found. Connect one, then press Start again.";
  }
  if (name === "NotReadableError") {
    return "The microphone is in use by another app. Close it, then press Start again.";
  }
  return `The microphone could not start: ${(err && err.message) || err}`;
}

// Level bars: a short history of frame loudness, newest in the middle.
const level = { history: new Array(7).fill(0), target: 0 };

function onFrame(mic, data) {
  const c = call;
  if (!c || c.mic !== mic) return;
  const rms = data.rms || 0;
  level.history.push(clamp((20 * Math.log10(rms + 1e-6) + 58) / 46, 0, 1));
  level.history.shift();
  if (!c.streaming || !c.ws || c.ws.readyState !== WebSocket.OPEN) return;
  let pcm = data.pcm;
  if (!(pcm instanceof ArrayBuffer) || pcm.byteLength !== FRAME_BYTES) {
    stats.wrongSizeFrames += 1;
    return;
  }
  if (c.muted) {
    pcm = new ArrayBuffer(FRAME_BYTES);
    stats.silentFrames += 1;
  }
  c.ws.send(pcm);
  stats.framesSent += 1;
  stats.bytesSent += pcm.byteLength;
  checkPace(c, mic);
}

// Frames come from the audio clock. If it runs slow, the server gets less than real time and the
// transcript falls behind the call, so say so instead of lagging quietly.
function checkPace(c, mic) {
  const now = performance.now();
  if (!c.streamFrames) {
    c.streamStart = now;
    c.ctxStart = mic.ctx.currentTime;
  }
  c.streamFrames += 1;
  if (c.streamFrames % 32 !== 0) return;
  const wall = (now - c.streamStart) / 1000;
  stats.framesPerSecond = Math.round((c.streamFrames / wall) * 100) / 100;
  stats.audioClockRatio = Math.round(((mic.ctx.currentTime - c.ctxStart) / wall) * 1000) / 1000;
  if (!c.paceWarned && wall >= 10 && stats.framesPerSecond < SLOW_AUDIO_RATIO * FRAMES_PER_SECOND) {
    c.paceWarned = true;
    const pct = Math.floor((100 * stats.framesPerSecond) / FRAMES_PER_SECOND);
    showError(`Audio is reaching the server at ${pct}% of real time, so the transcript will fall behind the call. Close other heavy apps, then start again.`,
      { title: "Audio running slow" });
  }
}

// ---- Call lifecycle --------------------------------------------------------------------------
async function startCall() {
  if (call && (call.phase === "connecting" || call.phase === "listening" || call.phase === "stopping")) return;
  if (call) closeMic(call);
  resetScreen();
  const c = (call = newCall());
  render();

  if (!location.host) {
    showError("Open this page from the server (http://localhost:8000), not as a file.", { key: "conn" });
    setPhase("dropped");
    return;
  }

  try {
    c.mic = await openMic();
  } catch (err) {
    if (call !== c) return;
    showError(micErrorMessage(err), { title: "Microphone", key: "mic" });
    call = null;
    render();
    return;
  }
  if (call !== c) {
    closeMic(c);
    return;
  }

  c.url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/call${location.search}`;
  let ws;
  try {
    ws = new WebSocket(c.url);
  } catch (err) {
    closeMic(c);
    showError(`Could not open ${c.url}: ${err.message}`, { title: "Connection", key: "conn" });
    setPhase("dropped");
    return;
  }
  c.ws = ws;
  ws.binaryType = "arraybuffer";
  ws.onopen = () => {
    if (call !== c) return;
    c.opened = true;
    ws.send(JSON.stringify(START_MESSAGE));
    c.streaming = true;
    c.startedAt = performance.now();
    c.connectTimer = setTimeout(() => stall(c, `The server has not started listening after ${LISTEN_TIMEOUT_MS / 1000} seconds.`),
      LISTEN_TIMEOUT_MS);
    render();
  };
  ws.onmessage = (e) => {
    if (call === c) onMessage(e.data);
  };
  ws.onclose = (e) => onClose(c, e);
}

function stall(c, message) {
  if (call !== c || c.phase !== "connecting" || c.stalled) return;
  c.stalled = true;
  if (message) showError(message, { title: "Not listening" });
  render();
}

function stopCall() {
  const c = call;
  if (!c || (c.phase !== "connecting" && c.phase !== "listening")) return;
  clearTimeout(c.connectTimer);
  c.streaming = false;
  closeMic(c);
  c.endedAt = performance.now();
  if (c.ws && c.ws.readyState === WebSocket.OPEN) {
    c.ws.send(JSON.stringify({ type: "stop" }));
    setPhase("stopping");
    c.stopTimer = setTimeout(() => {
      if (c.gotEnded) return;
      c.timedOut = true;
      showError(`The server did not finish the call within ${STOP_TIMEOUT_MS / 1000} seconds, so there is no summary.`,
        { title: "No summary", key: "conn" });
      c.ws.close();
    }, STOP_TIMEOUT_MS);
  } else {
    if (c.ws) c.ws.close();
    setPhase("ended");
  }
}

function onClose(c, e) {
  clearTimeout(c.stopTimer);
  clearTimeout(c.connectTimer);
  c.streaming = false;
  closeMic(c);
  if (call !== c) return;
  if (!c.endedAt) c.endedAt = performance.now();
  if (c.gotEnded || c.timedOut || (c.phase === "stopping" && c.gotSummary)) {
    setPhase("ended");
    return;
  }
  if (!c.opened) {
    showError(`Could not connect to ${c.url}. Check that the server is running, then press Start again.`,
      { title: "Not connected", key: "conn" });
  } else {
    const code = e && e.code && e.code !== 1005 ? ` (code ${e.code}${e.reason ? `: ${e.reason}` : ""})` : "";
    showError(`The connection to the server was lost${code}. Saavdhaan is not listening any more. Press Start to try again.`,
      { title: "Connection lost", key: "conn" });
  }
  setPhase("dropped");
}

function resetScreen() {
  clearErrors();
  ui.transcript.replaceChildren(el("p", "empty", "The call appears here as it is spoken, one sentence at a time."));
  for (const li of Object.values(tacticItems)) li.classList.remove("lit");
  ui.warning.hidden = true;
  ui.warning.dataset.audio = "none";
  ui.alert.hidden = true;
  ui.alertFo.hidden = true;
  ui.summary.hidden = true;
  ui.body.classList.remove("flash-on", "has-alert");
  gauge.target = 0;
}

// ---- Server events ---------------------------------------------------------------------------
function onMessage(data) {
  if (typeof data !== "string") return;
  let msg;
  try {
    msg = JSON.parse(data);
  } catch {
    showError("The server sent a message that is not JSON.", { title: "Server" });
    return;
  }
  if (!msg || typeof msg !== "object") return;
  switch (msg.type) {
    case "status": return onStatus(msg);
    case "transcript": return onTranscript(msg);
    case "risk": return onRisk(msg);
    case "warning": return onWarning(msg);
    case "alert": return onAlert(msg);
    case "fo": return onFo(msg);
    case "summary": return onSummary(msg);
    case "error": return onServerError(msg);
    default: return undefined; // newer message types are ignored
  }
}

function onServerError(msg) {
  const c = call;
  showError(msg.message || "The server reported an error without a message.", { title: "Server error" });
  // An error before "listening" usually means the speech service did not connect.
  if (c.phase === "connecting") setTimeout(() => stall(c), 3000);
}

function onStatus(msg) {
  const c = call;
  if (msg.state === "listening" && c.phase === "connecting") {
    clearTimeout(c.connectTimer);
    c.stalled = false;
    setPhase("listening");
  }
  else if (msg.state === "ended") {
    c.gotEnded = true;
    clearTimeout(c.stopTimer);
    if (!c.endedAt) c.endedAt = performance.now();
    setPhase("ended");
    if (c.ws && c.ws.readyState === WebSocket.OPEN) c.ws.close(1000);
  } else render();
}

function onTranscript(msg) {
  const c = call;
  const text = String(msg.text || "").trim();
  if (!text) return;
  const empty = ui.transcript.querySelector(".empty");
  if (empty) empty.remove();
  const row = el("p", "line latest");
  const time = el("time", "", fmt(msg.t_ms));
  const span = el("span", "text");
  if (DEVANAGARI.test(text)) span.lang = "hi";
  row.append(time, span);
  const line = { text, span, sig: "" };
  c.lines.push(line);
  renderLine(line);
  const prev = ui.transcript.querySelector(".line.latest");
  if (prev) prev.classList.remove("latest");
  ui.transcript.append(row);
  requestAnimationFrame(() => ui.transcript.scrollTo({ top: ui.transcript.scrollHeight, behavior: "smooth" }));
}

// The newest sentence must stay in view when the warning or the alert takes space from the transcript.
new ResizeObserver(() => { ui.transcript.scrollTop = ui.transcript.scrollHeight; }).observe(ui.transcript);

function onRisk(msg) {
  const c = call;
  const score = clamp(Number(msg.score) || 0, 0, 100);
  const lvl = ["safe", "caution", "danger"].includes(msg.level) ? msg.level : levelFor(score);
  gauge.target = score;
  const was = c.level;
  c.level = lvl;
  if (lvl === "danger" || (lvl === "caution" && c.peakLevel === "safe")) c.peakLevel = lvl;
  if (lvl === "danger" && was !== "danger") {
    ui.body.classList.remove("flash-on");
    void ui.body.offsetWidth; // restart the one-shot flash
    ui.body.classList.add("flash-on");
  }
  for (const t of Array.isArray(msg.tactics) ? msg.tactics : []) {
    if (tacticItems[t] && !c.tactics.has(t)) {
      c.tactics.add(t);
      tacticItems[t].classList.add("lit");
    }
  }
  let added = false;
  for (const raw of Array.isArray(msg.evidence) ? msg.evidence : []) {
    const phrase = cleanEvidence(raw);
    if (phrase.length >= 2 && !c.evidence.includes(phrase)) {
      c.evidence.push(phrase);
      added = true;
    }
  }
  if (added) c.lines.forEach(renderLine);
  render();
}

function onWarning(msg) {
  const c = call;
  c.warned = true;
  ui.warningTime.textContent = typeof msg.t_ms === "number" ? `at ${fmt(msg.t_ms)} into the call` : "";
  ui.warningText.textContent = String(msg.text || "");
  ui.warning.hidden = false;
  render();
  playWarning(c, msg.audio_b64);
}

function onAlert(msg) {
  const to = String(msg.to || "family");
  const n = Number(msg.delivered);
  const known = Number.isFinite(n);
  ui.alertTitle.textContent = !known ? `Alert for ${to}` : n > 0 ? `Alert sent to ${to}` : `Alert not delivered`;
  ui.alertTag.textContent = !known ? "" : n > 0 ? `Delivered to ${n} device${n === 1 ? "" : "s"}` : "No family device connected";
  ui.alertTag.hidden = !known;
  ui.alertText.textContent = String(msg.text || "");
  ui.alert.hidden = false;
  ui.body.classList.add("has-alert");
}

// Wajo Fo: SMS, email and phone call to the family, requested by the server when it warns.
function onFo(msg) {
  ui.alertFo.textContent = String(msg.text || "");
  ui.alertFo.dataset.state = String(msg.state || "");
  ui.alertFo.hidden = !msg.text;
  if (msg.state === "failed") showError(String(msg.text || "Fo request failed."), { title: "Fo", key: "fo" });
}

function onSummary(msg) {
  const c = call;
  c.gotSummary = true;
  const peak = clamp(Number(msg.peak_score) || 0, 0, 100);
  if (levelFor(peak) === "danger") c.peakLevel = "danger";
  else if (levelFor(peak) === "caution" && c.peakLevel === "safe") c.peakLevel = "caution";
  ui.sumPeak.textContent = String(peak);
  ui.sumFirst.textContent = typeof msg.first_warning_ms === "number" ? fmt(msg.first_warning_ms) : "None";
  ui.sumLength.textContent = c.startedAt ? fmt((c.endedAt || performance.now()) - c.startedAt) : "";

  const tactics = (Array.isArray(msg.tactics) ? msg.tactics : []).filter((t) => TACTIC_NAMES[t]);
  ui.sumTactics.replaceChildren(...(tactics.length
    ? tactics.map((t) => el("li", "", TACTIC_NAMES[t]))
    : [el("li", "none", "None heard")]));

  const evidence = (Array.isArray(msg.evidence) ? msg.evidence : []).map(cleanEvidence).filter(Boolean).slice(0, 4);
  ui.sumEvidence.replaceChildren(...(evidence.length
    ? evidence.map((q) => {
      const li = el("li", "", `“${q}”`);
      if (DEVANAGARI.test(q)) li.lang = "hi";
      return li;
    })
    : [el("li", "none", "Nothing suspicious was quoted.")]));

  if (msg.advice) ui.sumAdvice.textContent = String(msg.advice);
  if (msg.error) showError(`The summary is incomplete: ${msg.error}`, { title: "Server error" });
  ui.alert.hidden = true;
  ui.alertFo.hidden = true;
  ui.body.classList.remove("has-alert");
  ui.summary.hidden = false;
  render();
  ui.summaryClose.focus({ preventScroll: true });
}

// ---- Evidence highlighting -------------------------------------------------------------------
function cleanEvidence(raw) {
  return String(raw || "")
    .replace(/\s+/g, " ")
    .replace(/^[\s"'“”‘’«».,…-]+|[\s"'“”‘’«».,…-]+$/g, "");
}

function findRanges(text, phrases) {
  const lower = text.toLowerCase();
  const hay = lower.length === text.length ? lower : text;
  const whole = cleanEvidence(hay);
  const ranges = [];
  for (const p of phrases) {
    const needle = hay === lower ? p.toLowerCase() : p;
    let from = 0;
    let i;
    while ((i = hay.indexOf(needle, from)) !== -1) {
      ranges.push([i, i + needle.length]);
      from = i + needle.length;
    }
    // Evidence quoted across sentence boundaries: highlight this sentence if it is inside the quote.
    if (whole.length >= 8 && needle.length > whole.length && needle.includes(whole)) {
      ranges.push([0, text.length]);
    }
  }
  ranges.sort((a, b) => a[0] - b[0]);
  const merged = [];
  for (const r of ranges) {
    const last = merged[merged.length - 1];
    if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1]);
    else merged.push([r[0], r[1]]);
  }
  return merged;
}

function renderLine(line) {
  const ranges = findRanges(line.text, call ? call.evidence : []);
  const sig = JSON.stringify(ranges);
  if (sig === line.sig) return;
  line.sig = sig;
  const parts = [];
  let at = 0;
  for (const [s, e] of ranges) {
    if (s > at) parts.push(document.createTextNode(line.text.slice(at, s)));
    parts.push(el("mark", "", line.text.slice(s, e)));
    at = e;
  }
  if (at < line.text.length) parts.push(document.createTextNode(line.text.slice(at)));
  line.span.replaceChildren(...parts);
}

// ---- Spoken warning --------------------------------------------------------------------------
function setAudioState(state, note) {
  ui.warning.dataset.audio = state;
  ui.warningAudio.textContent = note;
}

function muteMic(c, on) {
  clearTimeout(c.muteTimer);
  c.muted = MUTE_MIC_DURING_WARNING && on;
  if (c.muted) c.muteTimer = setTimeout(() => muteMic(c, false), 30000);
  render();
}

function playWarning(c, b64) {
  if (!b64) {
    setAudioState("none", "Shown as text only: the server sent no warning audio.");
    return;
  }
  let bytes;
  try {
    const bin = atob(b64);
    bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  } catch {
    setAudioState("failed", "The warning audio could not be decoded.");
    showError("The warning audio from the server could not be decoded, so it was shown as text only.", { title: "Warning audio" });
    return;
  }
  const url = URL.createObjectURL(new Blob([bytes], { type: "audio/wav" }));
  const audio = new Audio(url);
  c.audio = audio;
  c.audioUrl = url;
  audio.addEventListener("playing", () => {
    setAudioState("playing", "Playing aloud");
    muteMic(c, true);
  });
  audio.addEventListener("ended", () => {
    setAudioState("played", "Played aloud");
    muteMic(c, false);
    URL.revokeObjectURL(url);
  });
  audio.addEventListener("error", () => {
    setAudioState("failed", "The warning audio could not be played.");
    muteMic(c, false);
    showError("The browser could not play the warning audio, so it was shown as text only.", { title: "Warning audio" });
  });
  setAudioState("loading", "Starting audio");
  // Chrome holds media in a window it considers hidden (minimised or covered), with no error, so the
  // warning would stay silent. Say so instead of waiting quietly.
  setTimeout(() => {
    if (c.audio === audio && ui.warning.dataset.audio === "loading") {
      setAudioState("blocked", "Waiting: bring this window to the front to hear the warning.");
      showError("The spoken warning has not started. The browser holds sound while this window is hidden or covered. Bring the Saavdhaan window to the front.",
        { title: "Warning audio", key: "audio-hidden" });
    }
  }, 2500);
  audio.addEventListener("playing", () => {
    const box = ui.errors.querySelector('[data-key="audio-hidden"]');
    if (box) box.remove();
  }, { once: true });
  audio.play().catch((err) => {
    if (err && err.name === "AbortError") return;
    setAudioState("blocked", "Sound was blocked by the browser.");
    muteMic(c, false);
    showError(`The browser blocked the warning audio (${(err && err.message) || err}). Click the page once to allow sound.`,
      { title: "Warning audio" });
  });
}

// ---- Animation loop: meter and level bars ------------------------------------------------------
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

function tick(now) {
  const dt = gauge.lastFrame ? Math.min(100, now - gauge.lastFrame) : 16;
  gauge.lastFrame = now;
  const diff = gauge.target - gauge.shown;
  if (Math.abs(diff) > 0.02) {
    gauge.shown = reduceMotion.matches ? gauge.target : gauge.shown + diff * (1 - Math.exp(-dt / 320));
    if (Math.abs(gauge.target - gauge.shown) < 0.05) gauge.shown = gauge.target;
    drawGauge();
  }
  if (call && call.phase === "listening") {
    const order = [5, 3, 1, 0, 2, 4, 6];
    ui.bars.forEach((bar, i) => {
      const v = call.muted ? 0 : level.history[level.history.length - 1 - order[i]];
      bar.style.transform = `scaleY(${(0.12 + 0.88 * v).toFixed(3)})`;
    });
    updateClock();
  }
  requestAnimationFrame(tick);
}

// ---- Wiring ----------------------------------------------------------------------------------
buildGauge();
buildTactics();
drawGauge();
render();
requestAnimationFrame(tick);

ui.start.addEventListener("click", () => { startCall(); });
ui.stop.addEventListener("click", stopCall);
ui.summaryClose.addEventListener("click", () => { ui.summary.hidden = true; });

// Press S to start or stop without the pointer in the recording; Escape closes the summary.
document.addEventListener("keydown", (e) => {
  if (e.ctrlKey || e.metaKey || e.altKey || e.repeat) return;
  if (e.key === "Escape" && !ui.summary.hidden) ui.summary.hidden = true;
  if (e.key === "s" || e.key === "S") {
    if (call && (call.phase === "connecting" || call.phase === "listening")) stopCall();
    else if (!call || call.phase === "ended" || call.phase === "dropped") startCall();
  }
});

window.addEventListener("beforeunload", () => {
  if (call && call.ws && call.ws.readyState === WebSocket.OPEN) call.ws.close(1000);
});

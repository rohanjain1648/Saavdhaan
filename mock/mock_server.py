"""Mock Saavdhaan backend: replays a scripted scam call so the screen can be built without Gnani.

Run from the project root:
    .\\.venv\\Scripts\\python.exe -m uvicorn mock.mock_server:app --port 8000
then open http://localhost:8000. Same path and port as the real backend (ws://localhost:8000/ws/call)
and the same messages as backend/contract.py. Audio frames are counted and size-checked, then ignored.

Options, as a query string on the page URL (the page forwards it to the WebSocket):
    ?scenario=scam     default: fake CBI "digital arrest" call, warning at about 0:28
    ?scenario=normal   a harmless bank call that stays safe
    ?scenario=error    the scam call plus a server error event at 0:06
    ?scenario=drop     the scam call, but the server drops the connection at 0:12
    ?speed=2           replay twice as fast (0.25 to 10)
GET /mock/stats reports the audio frames received in the most recent call.
"""
from __future__ import annotations

import array
import asyncio
import base64
import io
import json
import math
import time
import wave
from collections import Counter
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from backend.contract import FRAME_BYTES, SAMPLE_RATE, TACTICS, RiskUpdate, level_for

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT / "frontend"

ADVICE = "Call 1930 (National Cyber Crime Helpline) or report at cybercrime.gov.in."
WARNING_TEXT = (  # same text the real backend speaks
    "Saavdhaan. Yeh call ek scam ho sakta hai. Koi bhi police ya bank phone par paise ya OTP nahi "
    "maangta. Call kaat dijiye aur unnees sau tees par sampark kijiye."
)
TACTIC_NAMES = {  # same wording as the real backend's alert
    "authority_impersonation": "pretending to be police or an official",
    "digital_arrest": "claiming a 'digital arrest'",
    "urgency_threat": "threatening arrest or account freeze",
    "isolation_secrecy": "telling them not to tell anyone",
    "money_transfer": "asking for a money transfer",
    "credential_request": "asking for OTP or bank details",
    "remote_access_app": "asking to install a screen-sharing app",
}


# ---- Generated warning audio: a short three-note chime, 16 kHz mono PCM16 WAV ------------------
def tone_wav() -> bytes:
    notes = [(0.00, 0.34, 988.0), (0.40, 0.34, 784.0), (0.80, 0.70, 988.0)]  # (start s, length s, Hz)
    total = int(SAMPLE_RATE * 1.6)
    samples = array.array("h", bytes(2 * total))
    for start, length, freq in notes:
        first, n = int(start * SAMPLE_RATE), int(length * SAMPLE_RATE)
        for i in range(n):
            t = i / SAMPLE_RATE
            env = min(1.0, i / 160) * math.exp(-4.0 * t / length)  # 10 ms attack, smooth decay
            value = 0.45 * env * (math.sin(2 * math.pi * freq * t) + 0.25 * math.sin(4 * math.pi * freq * t))
            samples[first + i] = max(-32767, min(32767, samples[first + i] + int(value * 32767)))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(samples.tobytes())  # little-endian on every platform this runs on
    return buf.getvalue()


WARNING_WAV_B64 = base64.b64encode(tone_wav()).decode("ascii")


# ---- Scripts. Each step: (call time in ms, kind, data) ------------------------------------------
# "say": one transcript sentence, then the keyword risk update for it.
# "llm": a later risk update from the LLM judge.
def say(text, score, tactics=(), evidence=None, warn=False):
    return {"text": text, "score": score, "tactics": list(tactics), "evidence": evidence, "warn": warn}


def llm(score, tactics=(), evidence=None):
    return {"score": score, "tactics": list(tactics), "evidence": evidence}


SCAM = [
    (1800, "say", say("नमस्ते, क्या मेरी बात सुनीता शर्मा जी से हो रही है?", 4)),
    (4800, "say", say("हाँ जी, मैं सुनीता बोल रही हूँ। आप कौन?", 4)),
    (8200, "say", say("मैं CBI Mumbai office से Inspector Vikram Rathore बोल रहा हूँ।", 30,
                      ["authority_impersonation"], "CBI Mumbai office से Inspector")),
    (12400, "say", say("आपके Aadhaar card से एक parcel बुक हुआ है, उसमें drugs मिले हैं।", 36)),
    (13600, "llm", llm(46, evidence="उसमें drugs मिले हैं")),
    (16200, "say", say("क्या? मैंने तो कोई parcel नहीं भेजा...", 46)),
    (19600, "say", say("आपके नाम पर arrest warrant निकल चुका है, दो घंटे में police आपके घर आएगी।", 60,
                       ["urgency_threat"], "arrest warrant निकल चुका है")),
    (24200, "say", say("अब से आप digital arrest में हैं, video call से हटिए मत।", 76,
                       ["digital_arrest"], "digital arrest में हैं")),
    (27800, "say", say("यह बात किसी को मत बताइए, अपने बेटे को भी नहीं।", 84,
                       ["isolation_secrecy"], "किसी को मत बताइए", warn=True)),
    (28200, "warning", {}),
    (29400, "alert", {}),
    (33400, "say", say("Verification के लिए अपना सारा पैसा RBI के safe account में transfer कीजिए।", 90,
                       ["money_transfer"], "safe account में transfer")),
    (34800, "llm", llm(92, evidence="RBI के safe account")),
    (38400, "say", say("आपके phone पर जो OTP आया है, वो अभी बताइए।", 96,
                       ["credential_request"], "OTP आया है")),
    (43000, "say", say("मुझे बहुत डर लग रहा है... मैं पहले अपने बेटे से बात करूँगी।", 96)),
]

NORMAL = [
    (1500, "say", say("नमस्ते सर, मैं Hometown Bank से आपकी relationship manager प्रिया बोल रही हूँ।", 8)),
    (5200, "say", say("हाँ प्रिया जी, बताइए।", 6)),
    (8400, "say", say("आपकी fixed deposit अगले हफ्ते mature हो रही है, बस यही बताने के लिए call किया।", 10)),
    (9600, "llm", llm(5)),
    (13000, "say", say("ठीक है, renew करने के लिए क्या करना होगा?", 6)),
    (16500, "say", say("आप जब चाहें branch आ जाइए, कोई जल्दी नहीं है।", 5)),
    (20500, "say", say("और याद रखिए, bank कभी phone पर OTP नहीं माँगता।", 14)),
    (21700, "llm", llm(4)),
    (24500, "say", say("ठीक है, धन्यवाद। मैं शनिवार को branch आता हूँ।", 4)),
]

SCRIPTS = {
    "scam": SCAM,
    "normal": NORMAL,
    "error": sorted(SCAM + [(6000, "error", {"message": "Mock: speech-to-text returned 429 RATE_LIMITED, "
                                                         "retrying (simulated error)."})], key=lambda s: s[0]),
    "drop": [s for s in SCAM if s[0] < 12000] + [(12000, "drop", {})],
}

# Frame statistics for the most recent call, served at /mock/stats.
LAST_STATS: dict = {"calls": 0}


class MockCall:
    def __init__(self, ws: WebSocket, scenario: str, speed: float):
        self.ws = ws
        self.script = SCRIPTS[scenario]
        self.speed = speed
        self.send_lock = asyncio.Lock()
        self.closed = self.started = self.finished = False
        self.replay_task: asyncio.Task | None = None
        # risk state
        self.index = 0
        self.tactics: list[str] = []
        self.evidence: list[str] = []
        self.peak = 0
        self.first_warning_ms: int | None = None
        self.last_t_ms = 0
        # audio frame checks
        self.sizes: Counter = Counter()
        self.frames = 0
        self.size_error_sent = False
        self.first_frame_at: float | None = None
        self.last_frame_at: float | None = None
        LAST_STATS.clear()
        LAST_STATS.update({"calls": LAST_STATS.get("calls", 0) + 1, "scenario": scenario, "speed": speed})
        self._publish_stats()

    def _publish_stats(self) -> None:
        span = (self.last_frame_at or 0) - (self.first_frame_at or 0)
        LAST_STATS.update({
            "frames": self.frames,
            "sizes": {str(k): v for k, v in sorted(self.sizes.items())},
            "bad_frames": sum(v for k, v in self.sizes.items() if k != FRAME_BYTES),
            "frames_per_second": round((self.frames - 1) / span, 2) if self.frames > 1 and span > 0 else None,
            "expected_frames_per_second": SAMPLE_RATE * 2 / FRAME_BYTES,
            "seconds_of_audio": round(self.frames * FRAME_BYTES / (SAMPLE_RATE * 2), 2),
        })

    async def send(self, event: dict) -> None:
        if self.closed:
            return
        async with self.send_lock:
            try:
                await self.ws.send_text(json.dumps(event, ensure_ascii=False))
            except Exception:
                self.closed = True

    async def on_audio(self, data: bytes) -> None:
        now = time.monotonic()
        self.frames += 1
        self.sizes[len(data)] += 1
        self.first_frame_at = self.first_frame_at or now
        self.last_frame_at = now
        if self.frames % 32 == 0 or len(data) != FRAME_BYTES:
            self._publish_stats()
        if len(data) != FRAME_BYTES and not self.size_error_sent:
            self.size_error_sent = True
            await self.send({"type": "error",
                             "message": f"Mock: got a {len(data)}-byte audio frame; frames must be exactly "
                                        f"{FRAME_BYTES} bytes."})

    async def start(self) -> None:
        self.started = True
        await self.send({"type": "status", "state": "connecting"})
        self.replay_task = asyncio.create_task(self.replay())

    async def replay(self) -> None:
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await asyncio.sleep(0.5 / self.speed)
        await self.send({"type": "status", "state": "listening"})
        for at, kind, data in self.script:
            delay = t0 + at / 1000 / self.speed - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            if self.closed:
                return
            await self.step(at, kind, data)

    def _risk(self, data: dict, source: str, warn: bool) -> dict:
        for tactic in data["tactics"]:
            if tactic in TACTICS and tactic not in self.tactics:
                self.tactics.append(tactic)
        if data["evidence"] and data["evidence"] not in self.evidence:
            self.evidence.append(data["evidence"])
        score = data["score"]
        self.peak = max(self.peak, score)
        return RiskUpdate(score, level_for(score), list(self.tactics), self.evidence[-4:], source, warn).to_event()

    async def step(self, at: int, kind: str, data: dict) -> None:
        self.last_t_ms = at
        if kind == "say":
            self.index += 1
            await self.send({"type": "transcript", "index": self.index, "text": data["text"], "t_ms": at,
                             "latency_ms": 340 + (self.index * 97) % 260})
            await self.send(self._risk(data, "keywords", data["warn"]))
            if data["warn"] and self.first_warning_ms is None:
                self.first_warning_ms = at
        elif kind == "llm":
            await self.send(self._risk(data, "llm", False))
        elif kind == "warning":
            await self.send({"type": "warning", "text": WARNING_TEXT, "audio_b64": WARNING_WAV_B64,
                             "t_ms": self.first_warning_ms or at})
        elif kind == "alert":
            named = [TACTIC_NAMES[t] for t in self.tactics if t in TACTIC_NAMES][:3]
            how = f" The caller is {', '.join(named)}." if named else ""
            await self.send({"type": "alert", "to": "family",
                             "text": f"Saavdhaan: your family member may be on a scam call right now.{how} "
                                     f"Please call them. (Simulated alert)"})
        elif kind == "error":
            await self.send({"type": "error", "message": data["message"]})
        elif kind == "drop":
            self.closed = True
            try:
                await self.ws.close(code=1011, reason="mock: simulated dropped connection")
            except Exception:
                pass

    async def finish(self) -> None:
        if self.finished:
            return
        self.finished = True
        if self.replay_task is not None:
            self.replay_task.cancel()
            try:
                await self.replay_task
            except (asyncio.CancelledError, Exception):
                pass
        self._publish_stats()
        if self.closed:
            return
        if self.started:
            await self.send({"type": "summary", "peak_score": self.peak, "tactics": list(self.tactics),
                             "evidence": self.evidence[:4], "first_warning_ms": self.first_warning_ms,
                             "advice": ADVICE})
        await self.send({"type": "status", "state": "ended"})
        self.closed = True
        try:
            await self.ws.close()
        except Exception:
            pass


app = FastAPI(title="Saavdhaan mock")


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "mock": True, "scenarios": sorted(SCRIPTS)}


@app.get("/mock/stats")
async def mock_stats() -> dict:
    return LAST_STATS


@app.websocket("/ws/call")
async def ws_call(ws: WebSocket) -> None:
    await ws.accept()
    scenario = ws.query_params.get("scenario", "scam")
    try:
        speed = min(10.0, max(0.25, float(ws.query_params.get("speed", "1"))))
    except ValueError:
        speed = 1.0
    call = MockCall(ws, scenario if scenario in SCRIPTS else "scam", speed)
    if scenario not in SCRIPTS:
        await call.send({"type": "error", "message": f"Mock: unknown scenario {scenario!r}; playing 'scam'."})
    try:
        while not call.closed:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                call.closed = True
                break
            data = msg.get("bytes")
            if data is not None:
                await call.on_audio(data)
                continue
            try:
                control = json.loads(msg.get("text") or "")
            except ValueError:
                await call.send({"type": "error", "message": "Text messages must be JSON."})
                continue
            kind = control.get("type") if isinstance(control, dict) else None
            if kind == "start":
                if call.started:
                    await call.send({"type": "error", "message": "Call already started."})
                else:
                    await call.start()
            elif kind == "stop":
                break
            else:
                await call.send({"type": "error", "message": f"Unknown message type: {kind!r}"})
    except (WebSocketDisconnect, RuntimeError):
        call.closed = True
    finally:
        await call.finish()


if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

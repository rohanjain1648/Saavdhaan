"""Saavdhaan backend: browser microphone -> Gnani Prisma STT -> RiskEngine -> Timbre warning.

Run:  .\\.venv\\Scripts\\python.exe -m uvicorn backend.server:app --port 8000
WebSocket protocol on /ws/call is defined in backend/contract.py.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from backend.contract import FRAME_BYTES, SAMPLE_RATE, RiskUpdate, level_for
from backend.gnani_stt import GnaniSTT, GnaniSTTError, single_locale
from backend.gnani_tts import GnaniTTSError, synthesize
from backend import fo_client

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

log = logging.getLogger("saavdhaan")
if not log.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# ---- Risk engine: Session B's, or a stub until it lands ---------------------
try:
    from backend.risk import RiskEngine  # type: ignore

    ENGINE_SOURCE = "backend.risk"
except Exception as _exc:  # B's package missing or broken: never block the audio path on it
    ENGINE_SOURCE = f"stub ({type(_exc).__name__}: {_exc})"
    log.warning("Using stub RiskEngine because backend.risk failed to import: %r", _exc)

    class RiskEngine:  # type: ignore[no-redef]
        """Minimal keyword stub with the same three methods as Session B's engine."""

        _WORDS = {
            "authority_impersonation": ("cbi", "police", "inspector", "customs", "rbi", "trai", "सीबीआई", "पुलिस", "इंस्पेक्टर", "क्राइम"),
            "digital_arrest": ("digital arrest", "डिजिटल अरेस्ट"),
            "urgency_threat": ("warrant", "arrest", "freeze", "turant", "वारंट", "तुरंत", "अरेस्ट"),
            "isolation_secrecy": ("kisi ko mat", "call mat kaat", "किसी को मत", "मत काटिए"),
            "money_transfer": ("transfer", "safe account", "upi", "rtgs", "ट्रांसफर", "सेफ अकाउंट"),
            "credential_request": ("otp", "pin", "cvv", "aadhaar", "ओटीपी", "आधार"),
            "remote_access_app": ("anydesk", "teamviewer", "screen share", "एनीडेस्क"),
        }

        def __init__(self):
            self.tactics: list[str] = []
            self.evidence: list[str] = []
            self.peak = 0
            self.last_level = "safe"
            self.warned = False

        def _update(self, source: str) -> RiskUpdate:
            score = min(100, 25 * len(self.tactics))
            level = level_for(score)
            warn = level == "danger" and self.last_level == "danger" and not self.warned
            self.warned |= warn
            self.last_level, self.peak = level, max(self.peak, score)
            return RiskUpdate(score, level, list(self.tactics), self.evidence[-3:], source, warn)

        def add_sentence(self, text: str) -> RiskUpdate:
            low = text.lower()
            for tactic, words in self._WORDS.items():
                if tactic not in self.tactics and any(w in low for w in words):
                    self.tactics.append(tactic)
                    self.evidence.append(text[:80])
            return self._update("keywords")

        async def judge(self) -> RiskUpdate:
            return self._update("keywords")

        def summary(self) -> dict:
            return {"peak_score": self.peak, "tactics": list(self.tactics), "evidence": self.evidence[:3],
                    "first_warning_ms": None, "advice": "Call 1930 (National Cyber Crime Helpline) or report at cybercrime.gov.in."}


# ---- Warning text and audio --------------------------------------------------
# One warning per call language. The call's language picks it; for indic-auto, the language
# Gnani detected most often in the transcripts so far. Anything else falls back to Hindi.
WARNINGS = {
    "hi-IN": (
        "Saavdhaan. Yeh call ek scam ho sakta hai. Koi bhi police ya bank phone par paise ya OTP nahi "
        "maangta. Call kaat dijiye aur unnees sau tees par sampark kijiye."
    ),
    # Needs review by a native Tamil speaker before wider use.
    "ta-IN": (
        "கவனம்! இந்த அழைப்பு ஒரு மோசடியாக இருக்கலாம். எந்த போலீஸும் வங்கியும் ஃபோனில் பணமோ "
        "OTP-யோ கேட்க மாட்டார்கள். அழைப்பைத் துண்டித்து, ஒன்று ஒன்பது மூன்று பூஜ்ஜியம் என்ற எண்ணை அழையுங்கள்."
    ),
}
WARNING_LANGUAGE = "hi-IN"              # the default and the fallback
WARNING_TEXT = WARNINGS[WARNING_LANGUAGE]
WARNING_VOICE = os.environ.get("WARNING_VOICE", "Avinash")
CACHE_DIR = Path(__file__).resolve().parent / "tests_audio" / "cache"


def warning_language(lang: str | None) -> str:
    return lang if lang in WARNINGS else WARNING_LANGUAGE

TACTIC_NAMES = {
    "authority_impersonation": "pretending to be police or an official",
    "digital_arrest": "claiming a 'digital arrest'",
    "urgency_threat": "threatening arrest or account freeze",
    "isolation_secrecy": "telling them not to tell anyone",
    "money_transfer": "asking for a money transfer",
    "credential_request": "asking for OTP or bank details",
    "remote_access_app": "asking to install a screen-sharing app",
}

_warning_wav: dict[str, bytes] = {}       # language -> WAV, synthesized once per process
_warning_lock: tuple[asyncio.AbstractEventLoop, asyncio.Lock] | None = None

# ---- Family devices: real delivery of the alert ----------------------------------
# Every page open at /family.html (for example on a relative's phone on the same Wi-Fi) holds a
# WebSocket on /ws/family. Alerts are pushed to all of them; the call screen is told how many
# devices actually received it.
FAMILY: set[WebSocket] = set()

# Fo requests outlive the call that triggered them (Fo can take a minute to answer), so they are
# held here rather than on the CallSession, and never cancelled when the call ends.
_BACKGROUND: set[asyncio.Task] = set()


async def notify_family(event: dict) -> int:
    """Send one event to every connected family device. Returns how many received it."""
    payload = json.dumps(event, ensure_ascii=False)

    async def one(ws: WebSocket) -> bool:
        try:
            await asyncio.wait_for(ws.send_text(payload), timeout=3)
            return True
        except Exception:
            FAMILY.discard(ws)
            return False

    targets = list(FAMILY)
    if not targets:
        return 0
    results = await asyncio.gather(*(one(ws) for ws in targets))
    return sum(results)


def _warning_cache_path(lang: str = WARNING_LANGUAGE) -> Path:
    # The language is part of the digest, so each language gets its own file; the Hindi name is
    # unchanged from the single-language version.
    text = WARNINGS[lang]
    digest = hashlib.sha1(f"{text}|{WARNING_VOICE}|{lang}|{SAMPLE_RATE}".encode()).hexdigest()[:12]
    return CACHE_DIR / f"warning_{digest}.wav"


async def get_warning_audio(lang: str = WARNING_LANGUAGE) -> bytes | None:
    """Warning WAV for one language, synthesized once per process (and cached on disk).
    None if TTS fails."""
    global _warning_lock
    lang = warning_language(lang)
    if lang in _warning_wav:
        return _warning_wav[lang]
    loop = asyncio.get_running_loop()
    if _warning_lock is None or _warning_lock[0] is not loop:
        _warning_lock = (loop, asyncio.Lock())
    async with _warning_lock[1]:
        if lang in _warning_wav:
            return _warning_wav[lang]
        path = _warning_cache_path(lang)
        if path.exists() and os.environ.get("GNANI_TTS_URL") is None:
            _warning_wav[lang] = path.read_bytes()
            log.info("Warning audio (%s) loaded from cache %s (%d bytes)", lang, path.name, len(_warning_wav[lang]))
            return _warning_wav[lang]
        try:
            wav = await asyncio.wait_for(synthesize(WARNINGS[lang], lang, WARNING_VOICE), timeout=25)
        except (GnaniTTSError, asyncio.TimeoutError) as e:
            log.error("Warning audio (%s) synthesis failed: %s", lang, e or "timeout")
            return None
        _warning_wav[lang] = wav
        if os.environ.get("GNANI_TTS_URL") is None:  # don't cache fake-server audio
            try:
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                path.write_bytes(wav)
            except OSError as e:
                log.warning("Could not cache warning audio: %s", e)
        log.info("Warning audio (%s) synthesized (%d bytes)", lang, len(wav))
        return wav


# ---- One call over /ws/call --------------------------------------------------
BYTES_PER_MS = SAMPLE_RATE * 2 // 1000  # 32
JUDGE_TIMEOUT_S = 10.0
DRAIN_MIN_S, DRAIN_MAX_S = 1.2, 6.0


class CallSession:
    def __init__(self, ws: WebSocket, lang_override: str | None = None):
        self.ws = ws
        self.out: asyncio.Queue = asyncio.Queue()
        self.audio: asyncio.Queue = asyncio.Queue()
        self.bytes_in = 0
        self.index = 0
        self.language = "hi-IN"
        self.lang_override = single_locale(lang_override or "") or None   # from /ws/call?lang=
        self.detected: Counter = Counter()      # detected_language_code per transcript
        self.engine: RiskEngine | None = None
        self.stt: GnaniSTT | None = None
        self.first_warning_ms: int | None = None
        self.started = self.finished = self.client_gone = False
        self.lifecycle: asyncio.Task | None = None
        self.judge_task: asyncio.Task | None = None
        self.judge_again = False
        self.alert_task: asyncio.Task | None = None

    # ---- output: a single sender task, so nothing else ever awaits the browser socket
    def emit(self, event: dict) -> None:
        if not self.client_gone:
            self.out.put_nowait(event)

    def error(self, message: str) -> None:
        log.error("call error: %s", message)
        self.emit({"type": "error", "message": message})

    async def sender(self) -> None:
        while True:
            event = await self.out.get()
            if event is None:
                return
            try:
                await self.ws.send_text(json.dumps(event, ensure_ascii=False))
            except Exception:
                self.client_gone = True
                return

    def t_ms(self) -> int:
        return self.bytes_in // BYTES_PER_MS

    # ---- input
    def on_audio(self, chunk: bytes) -> None:
        self.bytes_in += len(chunk)
        self.audio.put_nowait(chunk)

    def start(self, msg: dict) -> None:
        self.started = True
        # ?lang= on the WebSocket URL wins over the start message, so the call screen can be
        # opened as http://localhost:8000/?lang=ta-IN with no change to the page.
        self.language = self.lang_override or single_locale(msg.get("language") or "") or self.language
        # The warning follows the call's language; the start message's warn_language is ignored.
        self.engine = RiskEngine()
        self.emit({"type": "status", "state": "connecting"})
        self.lifecycle = asyncio.create_task(self._lifecycle())

    def warn_lang(self) -> str:
        """The warning's language: the call's, or for indic-auto the most detected one so far."""
        if self.language == "indic-auto" and self.detected:
            return warning_language(self.detected.most_common(1)[0][0])
        return warning_language(self.language)

    # ---- the STT side of the call
    async def _lifecycle(self) -> None:
        # Warning audio first: it is cached after the first call, and fetching it before the
        # STT stream opens avoids a 429 on accounts that allow one request at a time.
        # For indic-auto every language is fetched, since the warning language is decided later.
        langs = list(WARNINGS) if self.language == "indic-auto" else [self.warn_lang()]
        for lang in langs:
            if await get_warning_audio(lang) is None:
                self.error(f"Warning audio ({lang}) could not be synthesized; the warning will be text only.")

        stt = GnaniSTT(language=self.language)
        try:
            await stt.connect()
        except GnaniSTTError as e:
            self.error(str(e))
            await self._discard_audio()
            return
        self.stt = stt
        log.info("STT connected: %s", stt.connected_info.get("config"))
        self.emit({"type": "status", "state": "listening"})

        reader = asyncio.create_task(self._read_transcripts())
        try:
            await self._forward_audio()
            if not self.client_gone and not reader.done():
                await stt.commit()
                await self._drain(reader)
        finally:
            await stt.close()
            try:
                await asyncio.wait_for(reader, timeout=2)
            except (asyncio.TimeoutError, Exception):
                reader.cancel()

    async def _discard_audio(self) -> None:
        while await self.audio.get() is not None:
            pass

    async def _forward_audio(self) -> None:
        """Re-chunk whatever the client sends into exact FRAME_BYTES frames. Never drops audio."""
        buf = bytearray()
        stt_dead = False
        while True:
            chunk = await self.audio.get()
            if chunk is None:
                break
            if stt_dead:
                continue
            buf += chunk
            try:
                while len(buf) >= FRAME_BYTES:
                    await self.stt.send(bytes(buf[:FRAME_BYTES]))
                    del buf[:FRAME_BYTES]
            except GnaniSTTError as e:
                self.error(str(e))
                stt_dead = True
        if buf and not stt_dead and not self.client_gone:
            try:  # pad the tail to a full frame with silence
                await self.stt.send(bytes(buf) + b"\x00" * (FRAME_BYTES - len(buf)))
            except GnaniSTTError:
                pass

    async def _drain(self, reader: asyncio.Task) -> None:
        """After commit, wait for the last sentence to come back."""
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        while not reader.done():
            elapsed = loop.time() - t0
            if elapsed >= DRAIN_MAX_S or (elapsed >= DRAIN_MIN_S and self.stt.pending == 0):
                return
            await asyncio.sleep(0.05)

    async def _read_transcripts(self) -> None:
        while True:
            try:
                async for msg in self.stt.transcripts():
                    self._on_sentence(msg)
                return
            except GnaniSTTError as e:
                self.error(str(e))
                if e.fatal:
                    return

    # ---- per sentence
    def _on_sentence(self, msg: dict) -> None:
        text = str(msg.get("text") or "").strip()
        if not text:
            return
        self.index += 1
        if msg.get("detected_language_code"):
            self.detected[str(msg["detected_language_code"])] += 1
        latency = msg.get("latency")
        self.emit({
            "type": "transcript",
            "index": self.index,
            "text": text,
            "t_ms": self.t_ms(),
            "latency_ms": int(latency) if isinstance(latency, (int, float)) else None,
        })
        try:
            update = self.engine.add_sentence(text)
        except Exception as e:
            log.exception("engine.add_sentence failed")
            self.error(f"Risk engine failed on a sentence: {e!r}")
            return
        self._on_update(update)
        self._schedule_judge()

    def _on_update(self, update: RiskUpdate) -> None:
        self.emit(update.to_event())
        if update.should_warn and self.first_warning_ms is None:
            self._warn(update)

    def _warn(self, update: RiskUpdate) -> None:
        self.first_warning_ms = self.t_ms()
        lang = self.warn_lang()
        wav = _warning_wav.get(lang)
        if wav is None and lang != WARNING_LANGUAGE and _warning_wav.get(WARNING_LANGUAGE):
            log.warning("No %s warning audio; falling back to %s", lang, WARNING_LANGUAGE)
            lang, wav = WARNING_LANGUAGE, _warning_wav[WARNING_LANGUAGE]
        audio_b64 = base64.b64encode(wav).decode("ascii") if wav else ""
        self.emit({"type": "warning", "text": WARNINGS[lang], "audio_b64": audio_b64, "t_ms": self.first_warning_ms})
        named = [TACTIC_NAMES[t] for t in update.tactics if t in TACTIC_NAMES][:3]
        how = f" The caller is {', '.join(named)}." if named else ""
        text = f"Saavdhaan: your family member may be on a scam call right now.{how} Please call them."
        self.alert_task = asyncio.create_task(self._send_alert(update, text))
        log.info("WARNING sent at t_ms=%s (score %s)", self.first_warning_ms, update.score)

    async def _send_alert(self, update: RiskUpdate, text: str) -> None:
        delivered = await notify_family({
            "type": "alert",
            "text": text,
            "score": update.score,
            "tactics": [TACTIC_NAMES[t] for t in update.tactics if t in TACTIC_NAMES],
            "evidence": update.evidence[:3],
            "t_ms": self.first_warning_ms,
        })
        log.info("Family alert delivered to %d device(s)", delivered)
        self.emit({"type": "alert", "to": "family", "text": text, "delivered": delivered})
        if fo_client.configured():
            self.emit({"type": "fo", "state": "requesting",
                       "text": "Asking Fo to text, email and call the family…"})
            task = asyncio.create_task(self._ask_fo(update))
            _BACKGROUND.add(task)
            task.add_done_callback(_BACKGROUND.discard)

    async def _ask_fo(self, update: RiskUpdate) -> None:
        tactics = [TACTIC_NAMES[t] for t in update.tactics if t in TACTIC_NAMES]
        res = await fo_client.alert_family(tactics, update.evidence[:3], self.first_warning_ms, self.warn_lang())
        if res.get("ok"):
            text = "Fo is texting, emailing and calling the family" + \
                   (" (working on it)" if res.get("status") == "working" else "")
        else:
            text = f"Fo request failed: {res.get('reply') or res.get('status')}"
        event = {"type": "fo", "state": "sent" if res.get("ok") else "failed",
                 "status": res.get("status"), "text": text}
        log.info("Fo: %s", text)
        self.emit(event)               # no-op if the call screen has gone
        await notify_family(event)

    # ---- LLM judge: background only, at most one in flight, re-run once if sentences arrived meanwhile
    def _schedule_judge(self) -> None:
        if self.judge_task is not None and not self.judge_task.done():
            self.judge_again = True
            return
        self.judge_task = asyncio.create_task(self._judge_loop())

    async def _judge_loop(self) -> None:
        while True:
            self.judge_again = False
            try:
                update = await asyncio.wait_for(self.engine.judge(), timeout=JUDGE_TIMEOUT_S)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("engine.judge failed (keyword result stands): %r", e)
                update = None
            if update is not None and not self.client_gone:
                self._on_update(update)
            if not self.judge_again or self.client_gone:
                return

    # ---- end of call
    async def finish(self) -> None:
        if self.finished:
            return
        self.finished = True
        self.audio.put_nowait(None)
        if self.lifecycle is not None:
            try:
                await asyncio.wait_for(self.lifecycle, timeout=15)
            except asyncio.TimeoutError:
                self.lifecycle.cancel()
                self.error("Timed out closing the speech-to-text stream.")
            except Exception as e:
                log.exception("call lifecycle crashed")
                self.error(f"Internal error: {e!r}")
        if self.judge_task is not None and not self.judge_task.done():
            if self.client_gone:
                self.judge_task.cancel()
            else:
                try:
                    await asyncio.wait_for(asyncio.shield(self.judge_task), timeout=4)
                except Exception:
                    self.judge_task.cancel()
        if self.alert_task is not None:
            try:
                await asyncio.wait_for(self.alert_task, timeout=4)
            except Exception:
                pass
        if self.engine is not None:
            try:
                summary = dict(self.engine.summary())
            except Exception as e:
                log.exception("engine.summary failed")
                summary = {"peak_score": 0, "tactics": [], "evidence": [], "advice": "Call 1930.",
                           "error": repr(e)}
            summary["first_warning_ms"] = self.first_warning_ms
            self.emit({"type": "summary", **summary})
            if self.first_warning_ms is not None:  # tell family devices how the call ended
                await notify_family({"type": "call_ended", "peak_score": summary.get("peak_score"),
                                     "tactics": [TACTIC_NAMES[t] for t in summary.get("tactics", []) if t in TACTIC_NAMES]})
        self.emit({"type": "status", "state": "ended"})


# ---- App ---------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("RiskEngine: %s | GNANI_API_KEY set: %s", ENGINE_SOURCE, bool(os.environ.get("GNANI_API_KEY")))
    async def warm_all() -> None:  # Hindi first, then the other languages, one at a time
        for lang in [WARNING_LANGUAGE] + [l for l in WARNINGS if l != WARNING_LANGUAGE]:
            await get_warning_audio(lang)

    warm = asyncio.create_task(warm_all()) if os.environ.get("GNANI_API_KEY") else None
    yield
    if warm is not None and not warm.done():
        warm.cancel()


app = FastAPI(title="Saavdhaan", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "engine": ENGINE_SOURCE,
        "gnani_key_set": bool(os.environ.get("GNANI_API_KEY")),
        "warning_audio_ready": WARNING_LANGUAGE in _warning_wav,
        "warning_audio_languages": {lang: lang in _warning_wav for lang in WARNINGS},
        "family_devices": len(FAMILY),
        "fo": {"configured": fo_client.configured(), **fo_client.LAST_STATUS},
        "llm_judge": _llm_status(),
    }


def _llm_status() -> dict:
    try:
        from backend.risk.llm_judge import LAST_STATUS
        return dict(LAST_STATUS)
    except Exception as e:  # stub engine in use
        return {"state": "unavailable", "detail": repr(e)}


@app.websocket("/ws/family")
async def ws_family(ws: WebSocket) -> None:
    await ws.accept()
    FAMILY.add(ws)
    log.info("Family device connected (%d now)", len(FAMILY))
    try:
        await ws.send_text(json.dumps({"type": "hello", "devices": len(FAMILY)}))
        while True:  # the page only listens; this just notices when it goes away
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    finally:
        FAMILY.discard(ws)
        log.info("Family device disconnected (%d now)", len(FAMILY))


@app.websocket("/ws/call")
async def ws_call(ws: WebSocket) -> None:
    await ws.accept()
    call = CallSession(ws, lang_override=ws.query_params.get("lang"))
    sender = asyncio.create_task(call.sender())
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                call.client_gone = True
                break
            data = msg.get("bytes")
            if data is not None:
                if call.started and not call.finished:
                    call.on_audio(data)
                continue
            try:
                control = json.loads(msg.get("text") or "")
            except ValueError:
                call.error("Text messages must be JSON.")
                continue
            kind = control.get("type") if isinstance(control, dict) else None
            if kind == "start":
                if call.started:
                    call.error("Call already started.")
                else:
                    call.start(control)
            elif kind == "stop":
                break
            else:
                call.error(f"Unknown message type: {kind!r}")
    except WebSocketDisconnect:
        call.client_gone = True
    finally:
        await call.finish()
        call.out.put_nowait(None)
        try:
            await asyncio.wait_for(sender, timeout=5)
        except Exception:
            sender.cancel()
        if not call.client_gone:
            try:
                await ws.close()
            except Exception:
                pass


FRONTEND_DIR = ROOT / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

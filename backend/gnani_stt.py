"""Async client for Gnani Prisma streaming speech-to-text (wss://api.vachana.ai/stt/v3/stream).

Usage:
    stt = GnaniSTT(language="hi-IN")
    await stt.connect()                 # raises GnaniSTTError on 401/402/403/429 or a server error
    await stt.send(frame)               # exactly FRAME_BYTES of PCM16 LE mono, at real-time pace
    async for msg in stt.transcripts(): # each "transcript" message as a dict
        ...
    await stt.commit()                  # force the open sentence to close
    await stt.close()

An `error` message from Gnani raises GnaniSTTError(fatal=False) out of transcripts(); the socket
may still be open, so call transcripts() again to keep reading. A dropped socket raises
GnaniSTTError(fatal=True).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import AsyncIterator, Iterable

import websockets
from websockets.exceptions import ConnectionClosed, ConnectionClosedError, InvalidHandshake, InvalidStatus

from backend.contract import FRAME_BYTES, SAMPLE_RATE

log = logging.getLogger("saavdhaan.stt")

DEFAULT_URL = "wss://api.vachana.ai/stt/v3/stream"
BACKOFF = (0.5, 1.0, 2.0)  # retries on 429 / concurrency cap, per PLAN.md rule 7

_STATUS_MEANING = {
    401: "bad or missing API key",
    402: "out of credit",
    403: "key lacks access to speech-to-text",
    429: "rate limited",
}

# Words the scam detector cares about; biasing STT towards them helps on noisy phone audio.
DEFAULT_KEYTERMS = (
    "CBI", "digital arrest", "OTP", "AnyDesk", "TeamViewer", "TRAI", "RBI", "Aadhaar", "PAN",
    "UPI", "RTGS", "customs", "narcotics", "money laundering", "warrant", "KYC", "FedEx",
)


class GnaniSTTError(Exception):
    def __init__(self, message: str, *, status: int | None = None, fatal: bool = True):
        super().__init__(message)
        self.status = status
        self.fatal = fatal


def _api_key(explicit: str | None) -> str:
    key = (explicit or os.environ.get("GNANI_API_KEY", "")).strip()
    if not key:
        raise GnaniSTTError("GNANI_API_KEY is not set (put it in .env)")
    return key


def single_locale(language: str) -> str:
    """The live stream accepts exactly one locale (verified against the API on Nov 15:
    "hi-IN,en-IN" is refused, "hi-IN" and "indic-auto" connect). format=codemix keeps the
    English words of a Hinglish call in Latin script, so hi-IN covers Hindi, English and mixed."""
    return (language or "").split(",")[0].strip()


def _is_capacity_error(message: str) -> bool:
    m = message.lower()
    return "limit" in m or "concurren" in m or "rate" in m


class GnaniSTT:
    def __init__(
        self,
        language: str = "hi-IN",
        *,
        model: str = "prisma-v3.0",
        fmt: str = "codemix",
        sample_rate: int = SAMPLE_RATE,
        min_silence_ms: int = 300,
        idle_timeout_s: int = 300,
        keyterms: Iterable[str] | None = DEFAULT_KEYTERMS,
        url: str | None = None,
        api_key: str | None = None,
    ):
        self.url = url or os.environ.get("GNANI_STT_URL", DEFAULT_URL)
        self._key = api_key
        self.headers = {
            "model": model,
            "language_code": single_locale(language),
            "format": fmt,
            "x-sample-rate": str(sample_rate),
            "x-min-silence-ms": str(min_silence_ms),
            "x-idle-timeout-sec": str(idle_timeout_s),
        }
        if keyterms:
            self.headers["keyterms"] = ",".join(keyterms)
        self._ws = None
        self._closing = False
        self.connected_info: dict = {}
        self.bytes_sent = 0
        # Counters used to know whether a sentence is still being transcribed.
        self.processing_seen = 0
        self.transcripts_seen = 0
        self.errors_seen = 0

    # ---- connection ---------------------------------------------------------
    async def connect(self, open_timeout: float = 10.0) -> dict:
        headers = {"x-api-key-id": _api_key(self._key), **self.headers}
        for attempt in range(len(BACKOFF) + 1):
            last_try = attempt == len(BACKOFF)
            try:
                ws = await websockets.connect(
                    self.url,
                    additional_headers=headers,
                    open_timeout=open_timeout,
                    max_size=2**22,
                    ping_interval=20,
                    ping_timeout=20,
                )
            except InvalidStatus as e:
                status = e.response.status_code
                body = (e.response.body or b"").decode("utf-8", "replace").strip()[:300]
                if status == 429 and not last_try:
                    log.warning("STT handshake 429, retrying in %.1fs", BACKOFF[attempt])
                    await asyncio.sleep(BACKOFF[attempt])
                    continue
                meaning = _STATUS_MEANING.get(status, "refused")
                raise GnaniSTTError(
                    f"Gnani STT refused the connection: HTTP {status} ({meaning}): {body or 'no body'}",
                    status=status,
                ) from None
            except (OSError, asyncio.TimeoutError, InvalidHandshake) as e:
                raise GnaniSTTError(f"Could not connect to Gnani STT at {self.url}: {e!r}") from None

            # The handshake succeeded; the first message is `connected` or an `error`
            # (bad header, concurrency cap reached).
            try:
                first = await asyncio.wait_for(self._recv_json(ws), timeout=open_timeout)
            except (asyncio.TimeoutError, ConnectionClosed) as e:
                await ws.close()
                raise GnaniSTTError(f"Gnani STT opened but sent no 'connected' message: {e!r}") from None
            if first.get("type") == "error":
                message = str(first.get("message", "unknown error"))
                await ws.close()
                if _is_capacity_error(message) and not last_try:
                    log.warning("STT busy (%s), retrying in %.1fs", message, BACKOFF[attempt])
                    await asyncio.sleep(BACKOFF[attempt])
                    continue
                raise GnaniSTTError(f"Gnani STT error on connect: {message}")
            self._ws = ws
            self.connected_info = first
            return first
        raise GnaniSTTError("Gnani STT: retries exhausted")  # not reached

    @staticmethod
    async def _recv_json(ws) -> dict:
        while True:
            raw = await ws.recv()
            if isinstance(raw, (bytes, bytearray)):
                continue
            return json.loads(raw)

    # ---- sending ------------------------------------------------------------
    async def send(self, frame: bytes) -> None:
        if len(frame) != FRAME_BYTES:
            raise ValueError(f"Gnani STT needs frames of exactly {FRAME_BYTES} bytes, got {len(frame)}")
        if self._ws is None:
            raise GnaniSTTError("send() before connect()")
        try:
            await self._ws.send(frame)
        except ConnectionClosed as e:
            raise GnaniSTTError(f"Gnani STT connection closed while sending audio: {e}") from None
        self.bytes_sent += len(frame)

    async def commit(self) -> None:
        """Ask Gnani to close the open sentence now."""
        if self._ws is not None:
            try:
                await self._ws.send(json.dumps({"type": "commit"}))
            except ConnectionClosed:
                pass

    # ---- receiving ----------------------------------------------------------
    @property
    def pending(self) -> int:
        """Sentences Gnani has started transcribing but not yet returned."""
        return max(0, self.processing_seen - self.transcripts_seen - self.errors_seen)

    async def transcripts(self) -> AsyncIterator[dict]:
        if self._ws is None:
            raise GnaniSTTError("transcripts() before connect()")
        try:
            async for raw in self._ws:
                if isinstance(raw, (bytes, bytearray)):
                    continue
                try:
                    msg = json.loads(raw)
                except ValueError:
                    log.warning("STT sent non-JSON text: %.200s", raw)
                    continue
                kind = msg.get("type")
                if kind == "transcript":
                    self.transcripts_seen += 1
                    yield msg
                elif kind == "processing":
                    self.processing_seen += 1
                elif kind == "error":
                    self.errors_seen += 1
                    raise GnaniSTTError(f"Gnani STT error: {msg.get('message', msg)}", fatal=False)
                # connected / speech_start / settings_updated: nothing to do
        except ConnectionClosedError as e:
            if not self._closing:
                raise GnaniSTTError(f"Gnani STT connection dropped: code {e.code} {e.reason!r}") from None
            return
        # Clean close (1000/1001). 1001 is what Gnani sends after the 15-minute limit.
        code = self._ws.close_code
        if not self._closing and code not in (1000, None):
            raise GnaniSTTError(f"Gnani STT closed the session: code {code} {self._ws.close_reason!r}")

    # ---- closing ------------------------------------------------------------
    async def close(self) -> None:
        self._closing = True
        if self._ws is not None:
            try:
                await asyncio.wait_for(self._ws.close(), timeout=3)
            except Exception:  # already gone
                pass

    async def __aenter__(self) -> "GnaniSTT":
        await self.connect()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

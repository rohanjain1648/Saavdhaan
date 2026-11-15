"""Gnani Timbre text-to-speech over REST (POST /api/v1/tts/inference). Returns WAV bytes."""
from __future__ import annotations

import asyncio
import logging
import os

import httpx

from backend.risk.llm_judge import SSL_CONTEXT  # shared, built once; see the note there

from backend.contract import SAMPLE_RATE

log = logging.getLogger("saavdhaan.tts")

DEFAULT_URL = "https://api.vachana.ai/api/v1/tts/inference"
BACKOFF = (0.5, 1.0, 2.0)

_STATUS_MEANING = {
    400: "bad request",
    401: "bad or missing API key",
    402: "out of credit",
    403: "key lacks access to text-to-speech",
    429: "rate limited",
}


class GnaniTTSError(Exception):
    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


def _server_message(r: httpx.Response) -> str:
    try:
        data = r.json()
    except ValueError:
        return r.text.strip()[:300] or "no body"
    if isinstance(data, dict):
        detail = data.get("detail")
        if isinstance(detail, dict):
            code = detail.get("error_code")
            msg = detail.get("message", detail)
            return f"{code}: {msg}" if code else str(msg)
        if detail:
            return str(detail)[:300]
        if "message" in data:
            return str(data["message"])[:300]
    return str(data)[:300]


async def synthesize(
    text: str,
    language: str = "hi-IN",
    voice: str = "Avinash",
    *,
    model: str = "timbre-v3.0",
    sample_rate: int = SAMPLE_RATE,
    client: httpx.AsyncClient | None = None,
    timeout: float = 30.0,
) -> bytes:
    """Speak `text` with Timbre and return WAV bytes. Retries 429 and 5xx after 0.5, 1, 2 s."""
    key = os.environ.get("GNANI_API_KEY", "").strip()
    if not key:
        raise GnaniTTSError("GNANI_API_KEY is not set (put it in .env)")
    url = os.environ.get("GNANI_TTS_URL", DEFAULT_URL)
    body = {
        "text": text,
        "model": model,
        "voice": voice,
        "language": language,
        "audio_config": {"sample_rate": sample_rate, "container": "wav"},
    }
    headers = {"X-API-Key-ID": key, "Content-Type": "application/json"}

    own_client = client is None
    client = client or httpx.AsyncClient(timeout=timeout, verify=SSL_CONTEXT)
    try:
        for attempt in range(len(BACKOFF) + 1):
            can_retry = attempt < len(BACKOFF)
            try:
                r = await client.post(url, json=body, headers=headers)
            except httpx.TransportError as e:
                if can_retry:
                    log.warning("TTS network error %r, retrying in %.1fs", e, BACKOFF[attempt])
                    await asyncio.sleep(BACKOFF[attempt])
                    continue
                raise GnaniTTSError(f"Gnani TTS network error: {e!r}") from None

            if r.status_code == 200:
                data = r.content
                if not data.startswith(b"RIFF"):
                    raise GnaniTTSError(
                        f"Gnani TTS returned 200 but not WAV ({r.headers.get('content-type')}, {len(data)} bytes)",
                        status=200,
                    )
                return data
            if (r.status_code == 429 or r.status_code >= 500) and can_retry:
                log.warning("TTS HTTP %s, retrying in %.1fs", r.status_code, BACKOFF[attempt])
                await asyncio.sleep(BACKOFF[attempt])
                continue
            meaning = _STATUS_MEANING.get(r.status_code, "server error" if r.status_code >= 500 else "error")
            raise GnaniTTSError(
                f"Gnani TTS failed: HTTP {r.status_code} ({meaning}): {_server_message(r)}",
                status=r.status_code,
            )
        raise GnaniTTSError("Gnani TTS: retries exhausted")  # not reached
    finally:
        if own_client:
            await client.aclose()

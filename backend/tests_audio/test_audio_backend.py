"""Offline tests for the audio backend, against backend/tests_audio/fake_gnani.py.

Run:  .\\.venv\\Scripts\\python.exe -m pytest backend/tests_audio -q
"""
from __future__ import annotations

import asyncio
import base64
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from backend.contract import FRAME_BYTES, RiskUpdate
from backend.tests_audio import fake_gnani


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def fake_port():
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(fake_gnani.app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started:
        assert time.time() < deadline, "fake Gnani server did not start"
        time.sleep(0.05)
    yield port
    server.should_exit = True
    thread.join(5)


@pytest.fixture
def fake_env(fake_port, monkeypatch):
    monkeypatch.setenv("GNANI_API_KEY", fake_gnani.FAKE_KEY)
    monkeypatch.setenv("GNANI_STT_URL", f"ws://127.0.0.1:{fake_port}/stt/v3/stream")
    monkeypatch.setenv("GNANI_TTS_URL", f"http://127.0.0.1:{fake_port}/api/v1/tts/inference")
    for k in list(fake_gnani.stats):
        fake_gnani.stats[k] = 0
    from backend import server
    monkeypatch.setattr(server, "_warning_wav", {})
    return fake_port


def run_call(audio: bytes, chunk_sizes=(700, 1500, 1024, 333, 4096)) -> list[dict]:
    """Drive /ws/call with odd-sized chunks and return every event up to status: ended."""
    from backend.server import app

    events = []
    with TestClient(app) as client, client.websocket_connect("/ws/call") as ws:
        ws.send_json({"type": "start", "language": "hi-IN,en-IN", "warn_language": "hi-IN"})
        pos, i = 0, 0
        while pos < len(audio):
            n = chunk_sizes[i % len(chunk_sizes)]
            ws.send_bytes(audio[pos:pos + n])
            pos += n
            i += 1
        ws.send_json({"type": "stop"})
        while True:
            ev = ws.receive_json()
            events.append(ev)
            if ev["type"] == "status" and ev["state"] == "ended":
                break
    return events


# ---- end to end through the server ------------------------------------------------
def test_call_end_to_end(fake_env):
    seconds = 9.5
    audio = b"\x01\x00" * int(16000 * seconds)  # 304,000 bytes, not a multiple of 1,024
    events = run_call(audio)
    types = [e["type"] for e in events]
    print("\n".join(str({k: (v[:30] + "..." if k == "audio_b64" else v) for k, v in e.items()}) for e in events))

    assert types[0:2] == ["status", "status"]
    assert events[0]["state"] == "connecting" and events[1]["state"] == "listening"
    assert types[-2:] == ["summary", "status"] and events[-1]["state"] == "ended"
    assert "error" not in types, [e for e in events if e["type"] == "error"]

    # Re-chunking: every frame Gnani saw was exactly 1,024 bytes, and no audio was dropped.
    assert fake_gnani.stats["bad_frames"] == 0
    assert fake_gnani.stats["frames"] == -(-len(audio) // FRAME_BYTES)

    transcripts = [e for e in events if e["type"] == "transcript"]
    assert [t["index"] for t in transcripts] == list(range(1, len(transcripts) + 1))
    assert len(transcripts) == 5  # four full 2 s segments + the tail closed by commit
    assert all(t["latency_ms"] == 250 for t in transcripts)
    t_ms = [t["t_ms"] for t in transcripts]
    assert t_ms == sorted(t_ms) and 0 < t_ms[-1] <= int(seconds * 1000)

    # Each transcript is followed (directly) by its keyword risk event.
    for idx, e in enumerate(events):
        if e["type"] == "transcript":
            assert events[idx + 1]["type"] == "risk"
    assert {e["source"] for e in events if e["type"] == "risk"} >= {"keywords"}

    # Warning exactly once, with WAV audio, followed by the family alert.
    warnings = [i for i, e in enumerate(events) if e["type"] == "warning"]
    assert len(warnings) == 1
    w = events[warnings[0]]
    assert base64.b64decode(w["audio_b64"]).startswith(b"RIFF")
    assert "unnees sau tees" in w["text"]
    alerts = [e for e in events[warnings[0] + 1:] if e["type"] == "alert"]
    assert len(alerts) == 1 and alerts[0]["to"] == "family"
    assert alerts[0]["delivered"] == 0  # no family device connected in this test
    assert "Simulated" not in alerts[0]["text"]
    assert sum(1 for e in events if e["type"] == "risk" and e["should_warn"]) >= 1

    summary = events[-2]
    assert summary["first_warning_ms"] == w["t_ms"]
    assert "1930" in summary["advice"]


def test_family_device_receives_the_alert(fake_env):
    """A page on /ws/family gets the alert and the call-ended note; the call screen gets the real count."""
    from backend.server import FAMILY, app

    audio = b"\x01\x00" * int(16000 * 9.5)
    with TestClient(app) as client, client.websocket_connect("/ws/family") as fam:
        assert fam.receive_json() == {"type": "hello", "devices": 1}
        events = []
        with client.websocket_connect("/ws/call") as ws:
            ws.send_json({"type": "start", "language": "hi-IN"})
            for pos in range(0, len(audio), 1024):
                ws.send_bytes(audio[pos:pos + 1024])
            ws.send_json({"type": "stop"})
            while True:
                ev = ws.receive_json()
                events.append(ev)
                if ev["type"] == "status" and ev["state"] == "ended":
                    break
        alert = fam.receive_json()
        ended = fam.receive_json()
    assert alert["type"] == "alert" and alert["score"] >= 70 and alert["tactics"]
    assert ended["type"] == "call_ended"
    call_alert = next(e for e in events if e["type"] == "alert")
    assert call_alert["delivered"] == 1 and call_alert["text"] == alert["text"]
    assert not FAMILY  # the device was removed when its socket closed


class _SlowFailingEngine:
    """judge() hangs or raises; the audio path must not care."""

    calls = 0

    def __init__(self):
        self.n = 0

    def add_sentence(self, text):
        self.n += 1
        return RiskUpdate(score=10 * self.n, level="safe", tactics=[], evidence=[], source="keywords")

    async def judge(self):
        type(self).calls += 1
        if type(self).calls % 2:
            await asyncio.sleep(60)
        raise RuntimeError("LLM down")

    def summary(self):
        return {"peak_score": 10 * self.n, "tactics": [], "evidence": [], "first_warning_ms": None, "advice": "Call 1930."}


def test_slow_or_failing_judge_does_not_block(fake_env, monkeypatch):
    from backend import server
    monkeypatch.setattr(server, "RiskEngine", _SlowFailingEngine)
    t0 = time.time()
    events = run_call(b"\x01\x00" * 16000 * 9)
    elapsed = time.time() - t0
    types = [e["type"] for e in events]
    assert types.count("transcript") >= 4
    assert "warning" not in types
    assert events[-2]["type"] == "summary" and events[-2]["first_warning_ms"] is None
    assert elapsed < 15, f"call took {elapsed:.1f}s; a hanging judge blocked it"


def test_stt_refused_handshake_becomes_error_event(fake_env, monkeypatch):
    monkeypatch.setenv("GNANI_API_KEY", "wrong-key")
    events = run_call(b"\x00\x00" * 16000)
    errors = [e for e in events if e["type"] == "error"]
    assert any("HTTP 401" in e["message"] and "Invalid API key" in e["message"] for e in errors), errors
    assert events[-1] == {"type": "status", "state": "ended"}


# ---- STT client ------------------------------------------------------------------
def test_stt_client_errors(fake_env, monkeypatch):
    from backend.gnani_stt import GnaniSTT, GnaniSTTError

    async def go():
        for key, status, text in (("wrong-key", 401, "Invalid API key"), ("fake-broke", 402, "Insufficient credit")):
            with pytest.raises(GnaniSTTError) as ei:
                await GnaniSTT(api_key=key).connect()
            assert ei.value.status == status and text in str(ei.value) and f"HTTP {status}" in str(ei.value)

        stt = GnaniSTT()
        info = await stt.connect()
        assert info["type"] == "connected"
        with pytest.raises(ValueError):
            await stt.send(b"\x00" * 1000)
        await stt.close()

        # A server `error` message surfaces as an exception carrying the server's text.
        stt = GnaniSTT(language="")
        with pytest.raises(GnaniSTTError) as ei:
            await stt.connect()
        assert "language_code header is required" in str(ei.value)

    asyncio.run(go())


def test_stt_missing_key(monkeypatch):
    from backend.gnani_stt import GnaniSTT, GnaniSTTError
    monkeypatch.delenv("GNANI_API_KEY", raising=False)
    with pytest.raises(GnaniSTTError, match="GNANI_API_KEY"):
        asyncio.run(GnaniSTT().connect())


# ---- TTS client ------------------------------------------------------------------
def _tts_with(responses, monkeypatch):
    from backend import gnani_tts
    monkeypatch.setenv("GNANI_API_KEY", "k")
    monkeypatch.delenv("GNANI_TTS_URL", raising=False)
    sleeps, seen = [], []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(gnani_tts.asyncio, "sleep", fake_sleep)
    it = iter(responses)

    def handler(request: httpx.Request):
        seen.append(request)
        return next(it)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return gnani_tts, client, sleeps, seen


def test_tts_retries_429_and_5xx(monkeypatch):
    wav = b"RIFF" + b"\x00" * 40
    gnani_tts, client, sleeps, seen = _tts_with(
        [httpx.Response(429, json={"detail": {"error_code": "RATE_LIMITED", "message": "slow down"}}),
         httpx.Response(503, text="busy"),
         httpx.Response(200, content=wav, headers={"content-type": "audio/wav"})], monkeypatch)
    out = asyncio.run(gnani_tts.synthesize("namaste", client=client))
    assert out == wav and sleeps == [0.5, 1.0] and len(seen) == 3
    body = seen[0].read()
    assert b'"timbre-v3.0"' in body and b'"Avinash"' in body and b'"container":"wav"' in body.replace(b" ", b"")
    assert seen[0].headers["X-API-Key-ID"] == "k"


def test_tts_gives_up_after_three_retries(monkeypatch):
    gnani_tts, client, sleeps, seen = _tts_with([httpx.Response(429, json={"detail": {"error_code": "RATE_LIMITED", "message": "slow"}})] * 4, monkeypatch)
    with pytest.raises(gnani_tts.GnaniTTSError, match="HTTP 429.*RATE_LIMITED"):
        asyncio.run(gnani_tts.synthesize("namaste", client=client))
    assert sleeps == [0.5, 1.0, 2.0] and len(seen) == 4


def test_tts_does_not_retry_auth_errors(monkeypatch):
    gnani_tts, client, sleeps, seen = _tts_with(
        [httpx.Response(402, json={"detail": {"message": "Insufficient credit"}})], monkeypatch)
    with pytest.raises(gnani_tts.GnaniTTSError, match="HTTP 402 .*Insufficient credit"):
        asyncio.run(gnani_tts.synthesize("namaste", client=client))
    assert sleeps == [] and len(seen) == 1

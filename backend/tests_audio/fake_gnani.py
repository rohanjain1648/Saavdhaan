"""A local stand-in for Gnani's STT stream and TTS REST endpoint, for testing without a key.

Run:  .\\.venv\\Scripts\\python.exe -m uvicorn backend.tests_audio.fake_gnani:app --port 8765
Then point the backend at it:
    GNANI_API_KEY=fake-key
    GNANI_STT_URL=ws://127.0.0.1:8765/stt/v3/stream
    GNANI_TTS_URL=http://127.0.0.1:8765/api/v1/tts/inference

STT behaviour, mirroring the docs: rejects a bad key, requires exactly 1,024-byte frames (sends an
`error` and closes 1008 otherwise), and emits `processing` + `transcript` with the next scripted
sentence for every SEGMENT_BYTES of audio, or on `commit`.
"""
from __future__ import annotations

import io
import json
import math
import struct
import wave
from datetime import datetime, timezone

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response

FAKE_KEY = "fake-key"
FRAME_BYTES = 1024
SEGMENT_BYTES = 32000 * 2  # one "sentence" per 2 s of audio

SCRIPT = [
    "नमस्ते, मैं मुंबई साइबर क्राइम ब्रांच से इंस्पेक्टर वर्मा बोल रहा हूँ।",
    "आपके आधार कार्ड से जुड़े एक पार्सल में ड्रग्स मिले हैं, आपके नाम पर अरेस्ट वारंट जारी हुआ है।",
    "आप अभी डिजिटल अरेस्ट में हैं, यह कॉल मत काटिए और किसी को मत बताइए।",
    "वेरिफिकेशन के लिए दो लाख रुपये इस सेफ अकाउंट में तुरंत ट्रांसफर कीजिए, और ओटीपी बताइए।",
    "Aapka case number ek do teen hai, jaldi kijiye.",
]

app = FastAPI(title="fake-gnani")
stats = {"frames": 0, "bad_frames": 0, "sessions": 0, "tts_calls": 0}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def tone_wav(seconds: float = 1.0, rate: int = 16000, freq: float = 660.0) -> bytes:
    n = int(seconds * rate)
    samples = b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * i / rate))) for i in range(n))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples)
    return buf.getvalue()


@app.post("/api/v1/tts/inference")
async def tts(request: Request):
    stats["tts_calls"] += 1
    if request.headers.get("x-api-key-id") != FAKE_KEY:
        return JSONResponse({"detail": {"error_code": "INVALID_API_KEY", "message": "Invalid API key", "status_code": 401}}, 401)
    body = await request.json()
    if not body.get("text"):
        return JSONResponse({"success": False, "message": "text is required", "status_code": 400}, 400)
    return Response(tone_wav(), media_type="audio/wav")


@app.websocket("/stt/v3/stream")
async def stt(ws: WebSocket):
    key = ws.headers.get("x-api-key-id")
    if key != FAKE_KEY:
        status = 402 if key == "fake-broke" else 401
        await ws.send_denial_response(JSONResponse({"detail": {"message": "Invalid API key" if status == 401 else "Insufficient credit"}}, status))
        return
    await ws.accept()
    stats["sessions"] += 1
    stats["last_language"] = ws.headers.get("language_code")
    if not ws.headers.get("language_code"):
        await ws.send_text(json.dumps({"type": "error", "timestamp": _now(), "message": "language_code header is required"}))
        await ws.close(1008)
        return
    await ws.send_text(json.dumps({"type": "connected", "message": "ok", "timestamp": _now(),
                                   "request_id": "fake-req",
                                   "config": {"sample_rate": int(ws.headers.get("x-sample-rate", 16000)), "chunk_size": 512,
                                              "language_code": ws.headers.get("language_code"),
                                              "format": ws.headers.get("format", "verbatim")}}))
    since_last = 0
    seg = 0

    async def emit_segment():
        nonlocal since_last, seg
        seg += 1
        await ws.send_text(json.dumps({"type": "processing", "timestamp": _now()}))
        await ws.send_text(json.dumps({
            "type": "transcript", "timestamp": _now(), "text": SCRIPT[(seg - 1) % len(SCRIPT)],
            "audio_duration_ms": since_last // 32, "segment_id": f"fake-req-seg-{seg}",
            "segment_index": seg, "latency": 250, "is_final": True, "detected_language_code": "hi-IN",
        }))
        since_last = 0

    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                return
            if msg.get("bytes") is not None:
                frame = msg["bytes"]
                if len(frame) != FRAME_BYTES:
                    stats["bad_frames"] += 1
                    await ws.send_text(json.dumps({"type": "error", "timestamp": _now(),
                                                   "message": f"invalid frame size {len(frame)}, expected 1024"}))
                    await ws.close(1008)
                    return
                stats["frames"] += 1
                if since_last == 0:
                    await ws.send_text(json.dumps({"type": "speech_start", "utterance_id": seg + 1}))
                since_last += len(frame)
                if since_last >= SEGMENT_BYTES:
                    await emit_segment()
            else:
                data = json.loads(msg.get("text") or "{}")
                if data.get("type") == "commit" and since_last >= FRAME_BYTES * 5:
                    await emit_segment()
    except WebSocketDisconnect:
        return

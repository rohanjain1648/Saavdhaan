"""Smoke test of our own backend: stream a WAV into /ws/call in real time, print every event.

Run the server first, then:
    .\\.venv\\Scripts\\python.exe -m backend.tests_audio.smoke_ws [--wav path] [--url ws://...]
Saves the received warning audio to backend/tests_audio/cache/received_warning.wav.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import time
from pathlib import Path

import websockets
from dotenv import load_dotenv

from backend.contract import FRAME_BYTES, SAMPLE_RATE
from backend.tests_audio.sample import CACHE, ensure_sample_wav
from backend.tests_audio.wavutil import frames, load_pcm16, silence

ROOT = Path(__file__).resolve().parents[2]
FRAME_S = FRAME_BYTES / 2 / SAMPLE_RATE


def show(event: dict, t: float) -> None:
    shown = dict(event)
    if "audio_b64" in shown:
        shown["audio_b64"] = f"<{len(base64.b64decode(shown['audio_b64'] or ''))} bytes WAV>"
    print(f"[{t:6.2f}s] {json.dumps(shown, ensure_ascii=False)}", flush=True)


async def main(url: str, wav: str | None, speed: float) -> int:
    load_dotenv(ROOT / ".env")
    path = Path(wav) if wav else await ensure_sample_wav()
    pcm = load_pcm16(path) + silence(800)
    chunks = frames(pcm)
    print(f"streaming {path.name}: {len(pcm) / 32000:.1f} s, {len(chunks)} frames -> {url}")

    events: list[dict] = []
    async with websockets.connect(url, max_size=2**24) as ws:
        t0 = time.perf_counter()

        async def reader():
            async for raw in ws:
                ev = json.loads(raw)
                events.append(ev)
                show(ev, time.perf_counter() - t0)
                if ev.get("type") == "warning" and ev.get("audio_b64"):
                    out = CACHE / "received_warning.wav"
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(base64.b64decode(ev["audio_b64"]))
                if ev.get("type") == "status" and ev.get("state") == "ended":
                    return

        task = asyncio.create_task(reader())
        await ws.send(json.dumps({"type": "start", "language": "hi-IN,en-IN", "warn_language": "hi-IN"}))
        start = time.perf_counter()
        for i, frame in enumerate(chunks):
            await ws.send(frame)
            delay = start + (i + 1) * FRAME_S / speed - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
        await ws.send(json.dumps({"type": "stop"}))
        try:
            await asyncio.wait_for(task, timeout=30)
        except asyncio.TimeoutError:
            print("!! no 'status: ended' within 30 s of stop")
            return 1

    counts: dict[str, int] = {}
    for ev in events:
        counts[ev["type"]] = counts.get(ev["type"], 0) + 1
    print(f"\nevent counts: {counts}")
    return 0 if counts.get("transcript") else 2


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="ws://127.0.0.1:8000/ws/call")
    p.add_argument("--wav")
    p.add_argument("--speed", type=float, default=1.0, help="1.0 = real time")
    a = p.parse_args()
    sys.exit(asyncio.run(main(a.url, a.wav, a.speed)))

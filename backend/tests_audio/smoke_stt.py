"""Smoke test: Timbre-synthesized Hindi call -> Gnani Prisma streaming STT, paced in real time.

Run:  .\\.venv\\Scripts\\python.exe -m backend.tests_audio.smoke_stt [--wav path/to/16k.wav]
Prints each transcript, Gnani's reported latency, and the wall-clock delay from the end of
that sentence's audio to the transcript arriving.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from backend.contract import FRAME_BYTES, SAMPLE_RATE
from backend.gnani_stt import GnaniSTT, GnaniSTTError
from backend.gnani_tts import GnaniTTSError
from backend.tests_audio.sample import ensure_sample_wav
from backend.tests_audio.wavutil import frames, load_pcm16, silence

ROOT = Path(__file__).resolve().parents[2]
FRAME_S = FRAME_BYTES / 2 / SAMPLE_RATE  # 0.032


async def main(wav: str | None) -> int:
    load_dotenv(ROOT / ".env")
    try:
        path = Path(wav) if wav else await ensure_sample_wav()
    except GnaniTTSError as e:
        print(f"TTS failed: {e}")
        return 1
    pcm = load_pcm16(path) + silence(1000)
    chunks = frames(pcm)
    print(f"audio: {path} ({len(pcm) / 32000:.1f} s, {len(chunks)} frames of {FRAME_BYTES} bytes)")

    stt = GnaniSTT(language="hi-IN")
    t0 = time.perf_counter()
    try:
        info = await stt.connect()
    except GnaniSTTError as e:
        print(f"STT connect failed: {e}")
        return 1
    print(f"connected in {(time.perf_counter() - t0) * 1000:.0f} ms: {info.get('config')}")

    start = time.perf_counter()
    got: list[dict] = []

    async def reader():
        while True:
            try:
                async for msg in stt.transcripts():
                    audio_ms = (time.perf_counter() - start) * 1000
                    got.append(msg)
                    print(f"[{audio_ms / 1000:6.2f}s] #{msg.get('segment_index')} "
                          f"latency={msg.get('latency')} ms  dur={msg.get('audio_duration_ms')} ms  "
                          f"lang={msg.get('detected_language_code')}\n          {msg.get('text')!r}", flush=True)
                return
            except GnaniSTTError as e:
                print(f"STT error: {e}")
                if e.fatal:
                    return

    task = asyncio.create_task(reader())
    for i, frame in enumerate(chunks):  # absolute schedule, so pacing does not drift
        await stt.send(frame)
        delay = start + (i + 1) * FRAME_S - time.perf_counter()
        if delay > 0:
            await asyncio.sleep(delay)
    sent_end = time.perf_counter()
    await stt.commit()
    while time.perf_counter() - sent_end < 6 and not task.done():
        if time.perf_counter() - sent_end > 1.5 and stt.pending == 0:
            break
        await asyncio.sleep(0.05)
    await stt.close()
    await asyncio.wait_for(task, 3)

    print(f"\n{len(got)} transcripts, streamed {stt.bytes_sent} bytes in {sent_end - start:.1f} s")
    lat = [m["latency"] for m in got if isinstance(m.get("latency"), (int, float))]
    if lat:
        print(f"Gnani-reported latency: min {min(lat)} ms, max {max(lat)} ms")
    return 0 if got else 2


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--wav", help="16-bit WAV to stream (default: synthesize the sample call)")
    sys.exit(asyncio.run(main(p.parse_args().wav)))

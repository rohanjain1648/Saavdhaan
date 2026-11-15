"""Voice a short synthetic Tamil/Tanglish scam call with Gnani Timbre, for live smoke tests.

Run:  .\\.venv\\Scripts\\python.exe -m backend.tests_audio.make_tamil_sample
Writes backend/tests_audio/cache/smoke_scam_ta.wav (16 kHz mono PCM16). Invented names, no real numbers.
Then stream it:  .\\.venv\\Scripts\\python.exe -m backend.tests_audio.smoke_ws --wav backend\\tests_audio\\cache\\smoke_scam_ta.wav --url "ws://127.0.0.1:8000/ws/call?lang=ta-IN"
"""
from __future__ import annotations

import asyncio
import io
from pathlib import Path

import numpy as np
import soundfile as sf
from dotenv import load_dotenv

from backend.gnani_tts import synthesize

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "cache" / "smoke_scam_ta.wav"

# Caller lines from backend/risk/tests/test_tamil.py, with numbers written as words.
LINES = [
    "வணக்கம், நான் மும்பை CBI cyber crime branch-ல இருந்து inspector ராஜேஷ் பேசறேன்.",
    "உங்க Aadhaar card-ல ஒரு money laundering case பதிவாகியிருக்கு.",
    "உங்க பேர்ல arrest warrant வந்திருக்கு.",
    "இப்போ நீங்க digital arrest-ல இருக்கீங்க, video call-ஐ cut பண்ணக்கூடாது.",
    "இதை யார்கிட்டயும் சொல்லாதீங்க, உங்க பையன்கிட்ட கூட.",
    "உங்க பணம் எல்லாத்தையும் RBI safe account-க்கு உடனே transfer பண்ணுங்க.",
]
VOICE = "Prakash"


async def main() -> None:
    load_dotenv(ROOT / ".env")
    parts = [np.zeros(8000, dtype=np.float32)]
    for i, line in enumerate(LINES, 1):
        print(f"  Timbre {i}/{len(LINES)} ...", flush=True)
        for attempt in range(4):
            wav = await synthesize(line, language="ta-IN", voice=VOICE)
            if len(wav) > 100:
                break
            print("    empty WAV, retrying", flush=True)
            await asyncio.sleep(0.5 * (attempt + 1))
        data, rate = sf.read(io.BytesIO(wav), dtype="float32", always_2d=True)
        data = data.mean(axis=1)
        if rate != 16000:
            raise SystemExit(f"expected 16 kHz from Timbre, got {rate}")
        parts += [data, np.zeros(int(16000 * 0.7), dtype=np.float32)]
    audio = np.concatenate(parts)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(OUT), audio, 16000, subtype="PCM_16")
    print(f"wrote {OUT} ({len(audio) / 16000:.1f} s)")


if __name__ == "__main__":
    asyncio.run(main())

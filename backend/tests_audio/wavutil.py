"""Small WAV helpers for the smoke tests: load as 16 kHz mono PCM16, write, join with pauses."""
from __future__ import annotations

import io
import wave
from pathlib import Path

import numpy as np

from backend.contract import FRAME_BYTES, SAMPLE_RATE


def pcm16_from_wav_bytes(data: bytes) -> bytes:
    """Decode WAV bytes to 16 kHz mono PCM16 LE (downmixes and resamples if needed)."""
    with wave.open(io.BytesIO(data), "rb") as w:
        channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError(f"expected 16-bit WAV, got {8 * width}-bit")
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE:
        n_out = int(round(len(samples) * SAMPLE_RATE / rate))
        samples = np.interp(np.linspace(0, len(samples) - 1, n_out), np.arange(len(samples)), samples)
    return np.clip(samples, -32768, 32767).astype("<i2").tobytes()


def load_pcm16(path: str | Path) -> bytes:
    return pcm16_from_wav_bytes(Path(path).read_bytes())


def write_wav(path: str | Path, pcm: bytes, rate: int = SAMPLE_RATE) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def silence(ms: int) -> bytes:
    return b"\x00\x00" * (SAMPLE_RATE * ms // 1000)


def frames(pcm: bytes) -> list[bytes]:
    """Split into FRAME_BYTES frames, zero-padding the last one."""
    out = [pcm[i:i + FRAME_BYTES] for i in range(0, len(pcm), FRAME_BYTES)]
    if out and len(out[-1]) < FRAME_BYTES:
        out[-1] = out[-1] + b"\x00" * (FRAME_BYTES - len(out[-1]))
    return out

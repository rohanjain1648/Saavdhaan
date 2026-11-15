"""Voice the synthetic call scripts with Gnani Timbre and build clean and phone-line WAVs.

Run from the project root:
    .\\.venv\\Scripts\\python.exe -m eval.make_audio --dry-run      # what would be synthesized, no API calls
    .\\.venv\\Scripts\\python.exe -m eval.make_audio                # all 8 calls, CBI scam first
    .\\.venv\\Scripts\\python.exe -m eval.make_audio --only scam_cbi_digital_arrest
    .\\.venv\\Scripts\\python.exe -m eval.make_audio --offline      # rebuild from the clip cache only

Every Timbre clip is cached in eval/audio/cache/ (key = model, voice, language, rate, text), so a rerun
costs no credits. Requests go one at a time; 429, 5xx and network errors back off 0.5, 1, 2, 4, 8, 15 s
(Session A shares the key). Output: eval/audio/clean/*.wav, eval/audio/phone/*.wav (16 kHz mono PCM16),
eval/audio/manifest.json, and eval/audio/tts_usage.json (requests and characters per run).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from backend.contract import SAMPLE_RATE  # noqa: E402  (16000)

SCRIPTS = HERE / "scripts"
AUDIO = HERE / "audio"
CLEAN, PHONE, CACHE = AUDIO / "clean", AUDIO / "phone", AUDIO / "cache"
MANIFEST = AUDIO / "manifest.json"
USAGE_LOG = AUDIO / "tts_usage.json"

TTS_URL = "https://api.vachana.ai/api/v1/tts/inference"
MODEL = "timbre-v3.0"
BACKOFF = (0.5, 1.0, 2.0, 4.0, 8.0, 15.0)
RETRY_STATUS = {429, 500, 502, 503, 504}
STATUS_MEANING = {400: "bad request", 401: "bad or missing API key", 402: "out of credit",
                  403: "key lacks text-to-speech access", 429: "rate limited"}

FIRST = "scam_cbi_digital_arrest"  # Session A needs this one early
LEAD_MS, TAIL_MS = 600, 2000       # silence before the first turn and after the last
GAP_MS = (550, 900)                # pause between turns, varied per turn
SPEECH_RMS = 10 ** (-20 / 20)      # every clip levelled to -20 dBFS (active speech)
PEAK_MAX = 0.89

# Phone line: street noise at 15 dB below speech, mains hum at 32 dB below, 300-3400 Hz, G.711 mu-law 8 kHz.
STREET_SNR_DB, HUM_SNR_DB = 15.0, 32.0
BAND_HZ, TAPER_HZ = (300.0, 3400.0), 100.0


class TTSError(Exception):
    pass


# ---- Timbre client with an on-disk cache ------------------------------------------------------
class Timbre:
    def __init__(self, offline: bool = False):
        self.offline = offline
        self.key = os.environ.get("GNANI_API_KEY", "").strip()
        self.url = os.environ.get("GNANI_TTS_URL", TTS_URL)
        self.client: httpx.Client | None = None
        self.requests = self.characters = self.cache_hits = self.retries = 0

    @staticmethod
    def cache_path(text: str, voice: str, language: str) -> Path:
        ident = json.dumps({"model": MODEL, "voice": voice, "language": language, "rate": SAMPLE_RATE,
                            "text": text}, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(ident.encode("utf-8")).hexdigest()[:20]
        return CACHE / f"{voice.lower()}_{digest}.wav"

    def clip(self, text: str, voice: str, language: str) -> Path:
        path = self.cache_path(text, voice, language)
        if path.exists():
            self.cache_hits += 1
            return path
        if self.offline:
            raise TTSError(f"--offline and not cached: {voice}: {text[:50]}")
        if not self.key:
            raise TTSError("GNANI_API_KEY is not set. Put it in .env at the project root.")
        if self.client is None:
            self.client = httpx.Client(timeout=60.0)
        body = {"text": text, "model": MODEL, "voice": voice, "language": language,
                "audio_config": {"sample_rate": SAMPLE_RATE, "num_channels": 1, "container": "wav"}}
        headers = {"X-API-Key-ID": self.key, "Content-Type": "application/json"}
        for attempt in range(len(BACKOFF) + 1):
            can_retry = attempt < len(BACKOFF)
            try:
                r = self.client.post(self.url, json=body, headers=headers)
            except httpx.TransportError as e:
                if not can_retry:
                    raise TTSError(f"network error: {e!r}") from None
                self._wait(attempt, f"network error {type(e).__name__}")
                continue
            if r.status_code == 200:
                if not r.content.startswith(b"RIFF"):
                    raise TTSError(f"200 but not WAV ({r.headers.get('content-type')}, {len(r.content)} bytes)")
                if len(r.content) <= 100:  # seen live Nov 15: 200 OK with a 44-byte header and no audio
                    if not can_retry:
                        raise TTSError("Timbre returned an empty WAV (no samples) on every attempt")
                    self._wait(attempt, f"empty WAV ({len(r.content)} bytes)")
                    continue
                part = path.with_suffix(".part")
                part.write_bytes(r.content)
                part.replace(path)
                self.requests += 1
                self.characters += len(text)
                return path
            if r.status_code in RETRY_STATUS and can_retry:
                self._wait(attempt, f"HTTP {r.status_code}")
                continue
            meaning = STATUS_MEANING.get(r.status_code, "error")
            raise TTSError(f"Timbre HTTP {r.status_code} ({meaning}): {r.text[:300]}")
        raise TTSError("retries exhausted")

    def _wait(self, attempt: int, why: str) -> None:
        self.retries += 1
        print(f"    {why}, retrying in {BACKOFF[attempt]:.1f} s", flush=True)
        time.sleep(BACKOFF[attempt])

    def close(self) -> None:
        if self.client is not None:
            self.client.close()


# ---- Audio helpers --------------------------------------------------------------------------
def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def load_mono16k(path: Path) -> np.ndarray:
    data, rate = sf.read(str(path), dtype="float32", always_2d=True)
    data = data.mean(axis=1)
    if rate == SAMPLE_RATE:
        return data
    with tempfile.TemporaryDirectory() as tmp:  # Timbre should return 16 kHz; resample if it did not
        out = Path(tmp) / "r.wav"
        ffmpeg("-i", str(path), "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", str(out))
        data, _ = sf.read(str(out), dtype="float32")
    return data


def trim(x: np.ndarray, margin_ms: int = 40) -> np.ndarray:
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if peak == 0.0:
        return x
    idx = np.flatnonzero(np.abs(x) > max(0.02 * peak, 1e-3))
    margin = SAMPLE_RATE * margin_ms // 1000
    return x[max(0, idx[0] - margin): idx[-1] + margin]


def active_rms(x: np.ndarray, frame: int = 512) -> float:
    n = len(x) // frame
    if n == 0:
        return float(np.sqrt(np.mean(x ** 2))) if x.size else 0.0
    rms = np.sqrt(np.mean(x[: n * frame].reshape(n, frame) ** 2, axis=1))
    loud = rms[rms > 0.1 * rms.max()]
    return float(np.sqrt(np.mean(loud ** 2)))


def level(x: np.ndarray) -> np.ndarray:
    r = active_rms(x)
    if r > 0:
        x = x * (SPEECH_RMS / r)
    peak = float(np.max(np.abs(x)))
    return x * (PEAK_MAX / peak) if peak > PEAK_MAX else x


def silence(ms: int) -> np.ndarray:
    return np.zeros(SAMPLE_RATE * ms // 1000, dtype=np.float32)


def seed_for(name: str) -> int:
    return int.from_bytes(hashlib.sha256(name.encode()).digest()[:4], "little")


def write_wav(path: Path, x: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.clip(x, -1.0, 1.0), SAMPLE_RATE, subtype="PCM_16")


# ---- Phone-line degradation -----------------------------------------------------------------
def _norm(x: np.ndarray) -> np.ndarray:
    r = float(np.sqrt(np.mean(x ** 2)))
    return x / r if r > 0 else x


def street_noise(n: int, rng: np.random.Generator) -> np.ndarray:
    sr = SAMPLE_RATE
    f = np.fft.rfftfreq(n, 1 / sr)
    f[0] = f[1]
    spec = np.fft.rfft(rng.standard_normal(n))
    pink = _norm(np.fft.irfft(spec / np.sqrt(f), n))
    rumble = _norm(np.fft.irfft(spec * np.where(f < 250, 1.0 / f, 0.0), n))  # engines, low traffic
    t = np.arange(n) / sr
    swell = 1.0 + 0.45 * np.sin(2 * np.pi * 0.06 * t + rng.uniform(0, 6.3)) \
        + 0.25 * np.sin(2 * np.pi * 0.21 * t + rng.uniform(0, 6.3))
    noise = (0.7 * pink + 0.6 * rumble) * np.clip(swell, 0.25, None)
    for _ in range(max(1, n // (sr * 20))):  # passing vehicles: 3-5 s louder swells
        start, dur = int(rng.uniform(0, n - sr)), int(rng.uniform(3, 5) * sr)
        end = min(n, start + dur)
        noise[start:end] *= 1.0 + 1.2 * np.hanning(end - start)
    noise = _norm(noise)
    for _ in range(max(1, n // (sr * 25))):  # short two-tone horn, about one per 25 s
        start, dur = int(rng.uniform(0, n - sr)), int(0.35 * sr)
        tt = np.arange(dur) / sr
        horn = sum(np.sin(2 * np.pi * k * base * tt) / k for base in (420.0, 525.0) for k in (1, 2, 3))
        env = np.minimum(1.0, np.minimum(tt, tt[::-1]) / 0.02)
        noise[start:start + dur] += 1.8 * _norm(horn) * env
    return noise


def mains_hum(n: int) -> np.ndarray:
    t = np.arange(n) / SAMPLE_RATE
    return _norm(sum(np.sin(2 * np.pi * 50.0 * k * t) / k for k in range(1, 16)))  # buzzy 50 Hz


def band_limit(x: np.ndarray) -> np.ndarray:
    n = len(x)
    f = np.fft.rfftfreq(n, 1 / SAMPLE_RATE)
    lo, hi = BAND_HZ
    gain = np.zeros_like(f)
    gain[(f >= lo) & (f <= hi)] = 1.0
    rise = (f > lo - TAPER_HZ) & (f < lo)
    fall = (f > hi) & (f < hi + TAPER_HZ)
    gain[rise] = 0.5 - 0.5 * np.cos(np.pi * (f[rise] - (lo - TAPER_HZ)) / TAPER_HZ)
    gain[fall] = 0.5 + 0.5 * np.cos(np.pi * (f[fall] - hi) / TAPER_HZ)
    return np.fft.irfft(np.fft.rfft(x) * gain, n).astype(np.float32)


def phone_line(clean: np.ndarray, name: str) -> np.ndarray:
    rng = np.random.default_rng(seed_for(name))
    n = len(clean)
    speech = active_rms(clean)
    mixed = clean + street_noise(n, rng) * speech * 10 ** (-STREET_SNR_DB / 20) \
        + mains_hum(n) * speech * 10 ** (-HUM_SNR_DB / 20)
    banded = band_limit(mixed)
    peak = float(np.max(np.abs(banded)))
    if peak > PEAK_MAX:
        banded *= PEAK_MAX / peak
    with tempfile.TemporaryDirectory() as tmp:  # 16 k -> 8 k mu-law (G.711) -> 16 k, like a phone codec
        a, b, c = (Path(tmp) / s for s in ("a.wav", "b.wav", "c.wav"))
        write_wav(a, banded)
        ffmpeg("-i", str(a), "-ar", "8000", "-ac", "1", "-c:a", "pcm_mulaw", str(b))
        ffmpeg("-i", str(b), "-ar", str(SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le", str(c))
        out, _ = sf.read(str(c), dtype="float32")
    return out[:n] if len(out) >= n else np.pad(out, (0, n - len(out)))


# ---- Scripts, building, manifest --------------------------------------------------------------
def load_scripts() -> list[dict]:
    scripts = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(SCRIPTS.glob("*.json"))]
    for s in scripts:
        assert s["label"] in ("scam", "normal"), s["id"]
        assert set(t["speaker"] for t in s["turns"]) <= set(s["voices"]), s["id"]
        assert not any(ch.isdigit() for t in s["turns"] for ch in t["text"]), f"{s['id']}: write numbers as words"
    scripts.sort(key=lambda s: (s["id"] != FIRST, s["label"] != "scam", s["id"]))
    return scripts


def build_clean(script: dict, tts: Timbre) -> np.ndarray:
    rng = np.random.default_rng(seed_for(script["id"]))
    parts = [silence(LEAD_MS)]
    for i, turn in enumerate(script["turns"]):
        voice = script["voices"][turn["speaker"]]
        cached = tts.cache_path(turn["text"], voice, script["language"]).exists()
        print(f"  turn {i + 1:>2}/{len(script['turns'])} {voice:<8} {'cache' if cached else 'Timbre'}", flush=True)
        clip = level(trim(load_mono16k(tts.clip(turn["text"], voice, script["language"]))))
        if i:
            parts.append(silence(int(rng.integers(*GAP_MS))))
        parts.append(clip.astype(np.float32))
    parts.append(silence(TAIL_MS))
    return np.concatenate(parts)


def write_manifest(scripts: list[dict]) -> dict:
    files = []
    for variant, folder in (("clean", CLEAN), ("phone", PHONE)):
        for s in scripts:
            wav = folder / f"{s['id']}.wav"
            if wav.exists():
                files.append({"path": f"{variant}/{wav.name}", "id": s["id"], "label": s["label"],
                              "variant": variant, "duration_s": round(sf.info(str(wav)).duration, 2),
                              "title": s["title"], "script": f"scripts/{s['id']}.json", "voices": s["voices"]})
    manifest = {
        "about": "Synthetic calls for Saavdhaan. Scripts written for this test, invented names, voiced with Gnani "
                 "Timbre. 'phone' = street noise + mains hum, 300-3400 Hz, mu-law 8 kHz and back to 16 kHz.",
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sample_rate": SAMPLE_RATE, "format": "WAV PCM16 mono", "tts_model": MODEL,
        "counts": {v: {lab: sum(1 for f in files if f["variant"] == v and f["label"] == lab)
                       for lab in ("scam", "normal")} for v in ("clean", "phone")},
        "files": files,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def log_usage(tts: Timbre, built: list[str]) -> None:
    runs = json.loads(USAGE_LOG.read_text(encoding="utf-8")) if USAGE_LOG.exists() else []
    runs.append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model": MODEL,
                 "requests": tts.requests, "characters": tts.characters, "cache_hits": tts.cache_hits,
                 "retries": tts.retries, "built": built})
    USAGE_LOG.write_text(json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", help="script ids to build (default: all)")
    ap.add_argument("--offline", action="store_true", help="never call Timbre; use cached clips only")
    ap.add_argument("--no-phone", action="store_true", help="skip the phone-line versions")
    ap.add_argument("--dry-run", action="store_true", help="list uncached turns and characters, then exit")
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    for d in (CLEAN, PHONE, CACHE):
        d.mkdir(parents=True, exist_ok=True)

    scripts = load_scripts()
    chosen = [s for s in scripts if not args.only or s["id"] in args.only]
    if args.only and len(chosen) != len(set(args.only)):
        print(f"unknown id in --only; known: {[s['id'] for s in scripts]}")
        return 2

    if args.dry_run:
        todo = [(s["id"], t) for s in chosen for t in s["turns"]
                if not Timbre.cache_path(t["text"], s["voices"][t["speaker"]], s["language"]).exists()]
        print(f"{len(todo)} uncached turns, {sum(len(t['text']) for _, t in todo)} characters "
              f"(of {sum(len(t['text']) for s in chosen for t in s['turns'])} total in {len(chosen)} scripts)")
        print(f"GNANI_API_KEY set: {bool(os.environ.get('GNANI_API_KEY', '').strip())}")
        return 0

    tts = Timbre(offline=args.offline)
    built: list[str] = []
    try:
        for s in chosen:
            print(f"{s['id']} ({s['label']}, {len(s['turns'])} turns)", flush=True)
            clean = build_clean(s, tts)
            write_wav(CLEAN / f"{s['id']}.wav", clean)
            secs = len(clean) / SAMPLE_RATE
            note = "" if 45 <= secs <= 75 else "  <-- outside 45-75 s"
            print(f"  wrote clean/{s['id']}.wav  {secs:.1f} s{note}", flush=True)
            if not args.no_phone:
                write_wav(PHONE / f"{s['id']}.wav", phone_line(clean, s["id"]))
                print(f"  wrote phone/{s['id']}.wav", flush=True)
            built.append(s["id"])
            write_manifest(scripts)  # after every call, so the first file is usable at once
    except TTSError as e:
        print(f"STOPPED: {e}")
        return 1
    finally:
        tts.close()
        if tts.requests or built:
            log_usage(tts, built)
        print(f"Timbre requests: {tts.requests}, characters sent: {tts.characters}, "
              f"cache hits: {tts.cache_hits}, retries: {tts.retries}")
    m = write_manifest(scripts)
    print(f"manifest: {MANIFEST.relative_to(ROOT)}  counts: {m['counts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

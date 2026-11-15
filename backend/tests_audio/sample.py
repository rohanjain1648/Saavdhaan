"""Build (once) the synthetic Hindi scam-call WAV the smoke tests stream. Cached on disk."""
from __future__ import annotations

from pathlib import Path

from backend.gnani_tts import synthesize
from backend.tests_audio.wavutil import pcm16_from_wav_bytes, silence, write_wav

CACHE = Path(__file__).resolve().parent / "cache"
SAMPLE_WAV = CACHE / "smoke_scam_hi.wav"
CALLER_VOICE = "Yashraj"  # different from the warning voice (Avinash) so they are easy to tell apart

# Synthetic script, invented officer name, numbers as words.
SENTENCES = [
    "नमस्ते, मैं मुंबई साइबर क्राइम ब्रांच से इंस्पेक्टर वर्मा बोल रहा हूँ।",
    "आपके आधार कार्ड से जुड़े एक पार्सल में ड्रग्स मिले हैं, और आपके नाम पर अरेस्ट वारंट जारी हुआ है।",
    "आप अभी डिजिटल अरेस्ट में हैं, यह कॉल मत काटिए और किसी को मत बताइए।",
    "वेरिफिकेशन के लिए दो लाख रुपये इस सेफ अकाउंट में तुरंत ट्रांसफर कीजिए, और जो ओटीपी आया है वो बताइए।",
]


async def ensure_sample_wav(path: Path = SAMPLE_WAV) -> Path:
    if path.exists():
        return path
    pcm = silence(300)
    for i, text in enumerate(SENTENCES, 1):
        print(f"  synthesizing sentence {i}/{len(SENTENCES)} with Timbre ({CALLER_VOICE}) ...", flush=True)
        pcm += pcm16_from_wav_bytes(await synthesize(text, "hi-IN", CALLER_VOICE)) + silence(900)
    write_wav(path, pcm)
    print(f"  wrote {path} ({len(pcm) / 32000:.1f} s)")
    return path

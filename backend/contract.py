"""Shared contract for Saavdhaan. FROZEN: every session imports this, nobody edits it.

If something here is wrong, stop and tell the human instead of changing it,
because three other sessions are building against the same shapes.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal

# ---- Audio -----------------------------------------------------------------
SAMPLE_RATE = 16000          # Hz, mono, signed 16-bit little-endian PCM
FRAME_BYTES = 1024           # exactly 512 samples = 32 ms; Gnani requires this size

# ---- Risk ------------------------------------------------------------------
Level = Literal["safe", "caution", "danger"]
CAUTION_AT = 40              # score >= 40 -> caution
DANGER_AT = 70               # score >= 70 -> danger

TACTICS = (
    "authority_impersonation",   # police, CBI, customs, RBI, TRAI, courier, bank officer
    "digital_arrest",            # "you are under digital arrest", video-call custody
    "urgency_threat",            # arrest warrant, account freeze, "within two hours"
    "isolation_secrecy",         # "do not tell anyone", "do not cut the call"
    "money_transfer",            # "safe account", RTGS/UPI transfer, verification deposit
    "credential_request",        # OTP, PIN, CVV, Aadhaar, PAN, net-banking password
    "remote_access_app",         # AnyDesk, TeamViewer, screen share, install this APK
)


def level_for(score: int) -> Level:
    if score >= DANGER_AT:
        return "danger"
    if score >= CAUTION_AT:
        return "caution"
    return "safe"


@dataclass
class RiskUpdate:
    score: int                                   # 0-100
    level: Level
    tactics: list[str] = field(default_factory=list)    # subset of TACTICS
    evidence: list[str] = field(default_factory=list)   # short quotes from the transcript
    source: Literal["keywords", "llm"] = "keywords"
    should_warn: bool = False                    # True exactly once per call

    def to_event(self) -> dict:
        return {"type": "risk", **asdict(self)}


# ---- Browser <-> backend WebSocket, path /ws/call ---------------------------
#
# Client -> server
#   text   {"type": "start", "language": "hi-IN", "warn_language": "hi-IN"}
#   binary PCM frames, FRAME_BYTES each, sent at real-time pace
#   text   {"type": "stop"}
#
# Server -> client (all text JSON)
#   {"type": "status", "state": "connecting" | "listening" | "ended"}
#   {"type": "transcript", "index": 1, "text": "...", "t_ms": 5320, "latency_ms": 410}
#   {"type": "risk", "score": 82, "level": "danger", "tactics": [...],
#    "evidence": [...], "source": "keywords" | "llm", "should_warn": false}
#   {"type": "warning", "text": "...", "audio_b64": "<base64 WAV>", "t_ms": 21400}
#   {"type": "alert", "to": "family", "text": "..."}            (simulated, on screen only)
#   {"type": "summary", "peak_score": 91, "tactics": [...], "evidence": [...],
#    "first_warning_ms": 21400, "advice": "Call 1930 ..."}
#   {"type": "error", "message": "..."}
#
# t_ms is milliseconds of audio received since "start".

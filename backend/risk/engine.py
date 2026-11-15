"""RiskEngine: one instance per call. Interface fixed in PLAN.md ("RiskEngine interface").

    engine = RiskEngine()                    # reads LLM_* from the environment
    update = engine.add_sentence(text)       # sync, instant, keyword-based
    update = await engine.judge()            # LLM over the last 10 sentences; never raises
    engine.summary()                         # the "summary" event minus "type"

Score of every update = max(keyword score so far, latest successful LLM score). Keyword scores
only rise during a call (tactics seen so far), so a wrong LLM "safe" cannot hide a keyword hit.
The latest LLM score is carried into later keyword updates too; otherwise the updates would
alternate keyword, LLM, keyword, ... and an LLM-only danger could never be "two in a row".
"""
from __future__ import annotations

import logging

import httpx

from backend.contract import CAUTION_AT, TACTICS, RiskUpdate, level_for
from backend.risk.keywords import KeywordTracker
from backend.risk.llm_judge import WINDOW, LLMConfig, llm_judge

log = logging.getLogger("saavdhaan.risk")

ADVICE_RISKY = (
    "Call 1930 (National Cyber Crime Helpline) or report at cybercrime.gov.in, especially if "
    "money or details were shared. Real police, CBI, customs, TRAI or banks never arrest anyone "
    "on a video call and never ask for an OTP or a transfer to a 'safe account'."
)
ADVICE_SAFE = (
    "No scam pattern was detected on this call. If a caller ever threatens arrest or asks for "
    "an OTP or a money transfer, hang up and call 1930 (National Cyber Crime Helpline)."
)
UPDATE_EVIDENCE = 5
SUMMARY_EVIDENCE = 5


class RiskEngine:
    def __init__(self, config: LLMConfig | None = None,
                 transport: httpx.AsyncBaseTransport | None = None):
        self._config = config or LLMConfig.from_env()
        self._transport = transport           # tests inject httpx.MockTransport here
        self._kw = KeywordTracker()
        self._sentences: list[str] = []
        self._llm: RiskUpdate | None = None   # latest successful LLM verdict
        self._llm_tactics: set[str] = set()
        self._llm_evidence: list[str] = []
        self._judged_upto = 0                 # sentence count at the last successful judge
        self._prev_level = "safe"
        self._warned = False
        self.peak_score = 0
        self.updates = 0

    # ---- public interface ------------------------------------------------------------------
    def add_sentence(self, text: str) -> RiskUpdate:
        text = " ".join(str(text or "").split())
        if text:
            self._sentences.append(text)
            self._kw.add(text)
        carried = self._llm is not None and self._llm.score > self._kw.score
        return self._emit("llm" if carried else "keywords")

    async def judge(self) -> RiskUpdate:
        if not self._sentences:
            return self._emit("keywords")
        if self._llm is not None and self._judged_upto == len(self._sentences):
            return self._emit("llm")          # nothing new since the last verdict
        count = len(self._sentences)
        fallback = self._keyword_only()
        try:
            result = await llm_judge(self._sentences[-WINDOW:], fallback,
                                     self._config, self._transport)
        except Exception as e:                # llm_judge already never raises; belt and braces
            log.warning("judge failed unexpectedly: %r", e)
            result = fallback
        if result.source != "llm":
            # A failed or skipped LLM check is not new evidence. Re-reporting the state without
            # counting it keeps "two danger updates in a row" meaning two sentences, not one
            # sentence plus its own failed re-check (seen live on Nov 15: one-sentence warning).
            return self._current()
        self._llm = result
        self._judged_upto = count
        self._llm_tactics.update(result.tactics)
        for q in result.evidence:
            if q not in self._llm_evidence:
                self._llm_evidence.append(q)
        return self._emit("llm", first=result.evidence)

    def summary(self) -> dict:
        risky = self.peak_score >= CAUTION_AT
        return {
            "peak_score": self.peak_score,
            "tactics": self._tactics(),
            "evidence": self._top_evidence(SUMMARY_EVIDENCE),
            "first_warning_ms": None,         # the server knows the audio clock; it fills this in
            "advice": ADVICE_RISKY if risky else ADVICE_SAFE,
        }

    # ---- internals ------------------------------------------------------------------------------
    def _tactics(self) -> list[str]:
        seen = set(self._kw.tactics) | self._llm_tactics
        return [t for t in TACTICS if t in seen]

    def _top_evidence(self, limit: int, first: list[str] | None = None) -> list[str]:
        out: list[str] = []
        for q in (first or []) + self._kw.evidence(limit) + self._llm_evidence:
            if q not in out:
                out.append(q)
        return out[:limit]

    def _keyword_only(self) -> RiskUpdate:
        score = self._kw.score
        return RiskUpdate(score, level_for(score), list(self._kw.tactics),
                          self._kw.evidence(UPDATE_EVIDENCE), "keywords", False)

    def _current(self) -> RiskUpdate:
        """The current state, without advancing the warn counter or the update count."""
        score = max(self._kw.score, self._llm.score if self._llm is not None else 0)
        carried = self._llm is not None and self._llm.score > self._kw.score
        return RiskUpdate(score=score, level=level_for(score), tactics=self._tactics(),
                          evidence=self._top_evidence(UPDATE_EVIDENCE),
                          source="llm" if carried else "keywords", should_warn=False)

    def _emit(self, source: str, first: list[str] | None = None) -> RiskUpdate:
        score = self._kw.score
        if self._llm is not None:
            score = max(score, self._llm.score)
        level = level_for(score)
        warn = level == "danger" and self._prev_level == "danger" and not self._warned
        self._warned = self._warned or warn
        self._prev_level = level
        self.peak_score = max(self.peak_score, score)
        self.updates += 1
        return RiskUpdate(
            score=score,
            level=level,
            tactics=self._tactics(),
            evidence=self._top_evidence(UPDATE_EVIDENCE, first),
            source=source,
            should_warn=warn,
        )

"""Print how the ten test calls score, sentence by sentence, and (if LLM_API_KEY is set in the
environment or .env) what the real LLM judge says about each full call.

Run: .\\.venv\\Scripts\\python.exe -m backend.risk.report
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from backend.risk import LLMConfig, RiskEngine
from backend.risk.llm_judge import llm_judge
from backend.risk.tests.transcripts import NORMALS, SCAMS

ROOT = Path(__file__).resolve().parents[2]


def keyword_table() -> None:
    no_llm = LLMConfig(api_key="")
    print("Keyword engine (score after each sentence, * = should_warn)")
    for kind, calls in (("scam", SCAMS), ("normal", NORMALS)):
        for name, lines in calls.items():
            engine = RiskEngine(no_llm)
            scores, danger_at, warn_at, caution_at = [], None, None, None
            for i, s in enumerate(lines, 1):
                u = engine.add_sentence(s)
                scores.append(f"{u.score}{'*' if u.should_warn else ''}")
                if u.level == "danger" and danger_at is None:
                    danger_at = i
                if u.level == "caution" and caution_at is None:
                    caution_at = i
                if u.should_warn:
                    warn_at = i
            note = (f"danger at sentence {danger_at}, warns at {warn_at}" if danger_at
                    else f"caution from sentence {caution_at}" if caution_at else "safe throughout")
            print(f"  {kind:6s} {name:26s} {' '.join(scores):34s} {note}")


async def llm_table(config: LLMConfig) -> None:
    print(f"\nReal LLM judge, one call per transcript ({config.model})")
    for kind, calls in (("scam", SCAMS), ("normal", NORMALS)):
        for name, lines in calls.items():
            engine = RiskEngine(LLMConfig(api_key=""))
            for s in lines:
                kw = engine.add_sentence(s)
            sentinel = kw
            r = await llm_judge(lines, sentinel, config)
            if r is sentinel:
                print(f"  {kind:6s} {name:26s} LLM failed, keyword {kw.score} stands")
                continue
            print(f"  {kind:6s} {name:26s} llm {r.score:3d} ({r.level}), keyword {kw.score:3d}, "
                  f"combined {max(r.score, kw.score):3d} | {','.join(r.tactics)}")
            await asyncio.sleep(0.5)  # be gentle with free-tier rate limits


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except Exception:
        pass
    keyword_table()
    config = LLMConfig.from_env()
    if config.enabled:
        asyncio.run(llm_table(config))
    else:
        print("\nLLM_API_KEY not set: real LLM judge not run.")


if __name__ == "__main__":
    main()

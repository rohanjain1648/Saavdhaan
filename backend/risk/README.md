# backend/risk: RiskEngine (Session B)

1. Use: `from backend.risk import RiskEngine`, then `engine.add_sentence(text)`, `await engine.judge()`, `engine.summary()`.
2. Tests: `.\.venv\Scripts\python.exe -m pytest backend/risk -q` (no network or key needed).
3. Scores per test call: `.\.venv\Scripts\python.exe -m backend.risk.report` (it also runs the real LLM judge when `LLM_API_KEY` is set in `.env`).
4. LLM judge is optional: with no `LLM_API_KEY`, or on any error or after 6 s, `judge()` returns the keyword result.
5. Phrase lists and weights live in `keywords.py`; one tactic alone stays below danger, and authority + threat + money/OTP is floored at 80.

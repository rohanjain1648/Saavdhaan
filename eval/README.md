# eval: synthetic test calls and the metrics run

How to run (from the project root, `GNANI_API_KEY` in `.env`):

1. `.\.venv\Scripts\python.exe -m eval.make_audio --dry-run` shows how many Timbre characters are still uncached.
2. `.\.venv\Scripts\python.exe -m eval.make_audio` voices all 8 scripts (CBI scam first) into `audio/clean/` and `audio/phone/`, and writes `audio/manifest.json`. Reruns are free: every clip is cached in `audio/cache/`.
3. Start the real backend: `.\.venv\Scripts\python.exe -m uvicorn backend.server:app --port 8000`.
4. `.\.venv\Scripts\python.exe -m eval.run_eval` streams all 16 files, one at a time in real time (about 20 minutes), and writes `results.json` and `RESULTS.md`.
5. To check only the script, run it against the mock (`--url ws://localhost:PORT/ws/call --out-dir <scratch>`). A mock run titles its own write-up "MOCK RUN" and its numbers mean nothing.

What is here:

- `scripts/*.json`: 4 scam and 4 normal two-speaker Hinglish calls, written in Devanagari for Timbre (`hi-IN`).
  Invented names and companies, numbers written as words, no real phone, account, Aadhaar or PAN numbers. The normal
  calls deliberately reuse scam vocabulary (account, KYC, parcel, verify, OTP, "don't tell mummy", UPI, Aadhaar).
  The scripts were written from the contract's tactic list without reading `backend/risk/`, so they are not tuned
  to the keyword rules.
- Voices: each of the 8 voices used appears in one scam and one normal call, so the voice says nothing about the
  label. Avinash is left out because it is the warning voice.
- `make_audio.py`: Timbre v3.0, one request at a time, backoff on 429/5xx. Each turn is trimmed, levelled to
  -20 dBFS and joined with 550-900 ms pauses. Phone version: generated street noise (traffic swells, passing
  vehicles, horns) at 15 dB below speech, plus 50 Hz hum, band-limited to 300-3400 Hz, then 8 kHz mu-law and back
  to 16 kHz. `audio/tts_usage.json` logs requests and characters per run. Gnani has no balance API, so credits
  are not tracked here.
- `run_eval.py`: the metrics run. Scam caught = a `warning` event; false alarm = a `warning` on a normal call;
  time to warning = the warning event's `t_ms`; latency = the `latency_ms` the backend reports.

Eight calls is a smoke test, not a benchmark.

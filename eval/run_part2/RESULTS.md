# Saavdhaan smoke test

Run 2026-11-15 14:43 IST against `ws://localhost:8000/ws/call`, 2 synthetic calls (0 scam, 2 normal) x 2 audio version(s): clean, phone.

**Sample size: 2 calls. This is a smoke test, not a benchmark.** The calls were scripted for this test and voiced with Gnani Timbre text-to-speech, so they are cleaner and more predictable than real phone calls. One run, no repeats, no confidence intervals.

| Audio | Scams warned | False alarms on normal calls | Median transcript latency |
|---|---|---|---|
| clean | 0 / 0 | 0 / 2 | 75 ms (57 sentences) |
| phone | 0 / 0 | 0 / 2 | 71 ms (67 sentences) |

## Time from call start to the spoken warning, scam calls

Seconds of call audio before the warning event (`t_ms` in the event). The call length is in brackets.

| Scam call | clean | phone |
|---|---|---|

## Peak risk per call

| Call | Label | clean | phone |
|---|---|---|---|
| normal_courier_directions | normal | 25 safe | 25 safe |
| normal_family_money | normal | 45 caution | 40 caution |

## How this was measured

- `eval/run_eval.py` streams each WAV to `/ws/call` in 1,024-byte frames at real-time pace, one call at a time, and records every event in `eval/results.json`.
- A scam counts as caught if the server sent a `warning` event during the call. A false alarm is a `warning` on a normal call.
- Transcript latency is the `latency_ms` the backend reports on each `transcript` event (from Gnani Prisma), not measured by this script.
- Phone audio: street noise and mains hum added, band-limited to 300-3400 Hz, mu-law at 8 kHz, back to 16 kHz. See `eval/make_audio.py`.
- Server `/health`: `{"ok": true, "engine": "backend.risk", "gnani_key_set": true, "warning_audio_ready": true, "family_devices": 0, "llm_judge": {"state": "failing", "detail": "HTTP 401: {\"error\":{\"message\":\"Invalid API Key\",\"type\":\"invalid_request_error\",\"code\":\"invalid_api_key\"}}\n"}}`

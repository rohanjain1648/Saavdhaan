# Saavdhaan smoke test

Run 2026-11-15 14:26 IST against `ws://localhost:8000/ws/call`, 8 synthetic calls (4 scam, 4 normal) x 2 audio version(s): clean, phone.

**Sample size: 8 calls. This is a smoke test, not a benchmark.** The calls were scripted for this test and voiced with Gnani Timbre text-to-speech, so they are cleaner and more predictable than real phone calls. One run, no repeats, no confidence intervals.

**Risk scoring in this run: keyword rules only.** The LLM judge was `failing` (HTTP 401: {"error":{"message":"Invalid API Key","type":"invalid_request_error","code":"invalid_api_key"}}), so every score came from the keyword engine.

| Audio | Scams warned | False alarms on normal calls | Median transcript latency |
|---|---|---|---|
| clean | 4 / 4 | 0 / 4 | 81 ms (247 sentences) |
| phone | 4 / 4 | 0 / 4 | 75 ms (267 sentences) |

## Time from call start to the spoken warning, scam calls

Seconds of call audio before the warning event (`t_ms` in the event). The call length is in brackets.

| Scam call | clean | phone |
|---|---|---|
| scam_bank_kyc_otp | 66.9 s (of 83 s) | 66.8 s (of 83 s) |
| scam_cbi_digital_arrest | 32.7 s (of 90 s) | 32.7 s (of 90 s) |
| scam_customs_parcel | 53.6 s (of 79 s) | 53.5 s (of 79 s) |
| scam_trai_sim | 46.4 s (of 74 s) | 46.5 s (of 74 s) |

## Peak risk per call

| Call | Label | clean | phone |
|---|---|---|---|
| scam_bank_kyc_otp | scam | 85 danger (warned) | 80 danger (warned) |
| scam_cbi_digital_arrest | scam | 100 danger (warned) | 100 danger (warned) |
| scam_customs_parcel | scam | 100 danger (warned) | 100 danger (warned) |
| scam_trai_sim | scam | 100 danger (warned) | 100 danger (warned) |
| normal_bank_rm | normal | 40 caution | 40 caution |
| normal_clinic_reminder | normal | 30 safe | 30 safe |
| normal_courier_directions | normal | 25 safe | 25 safe |
| normal_family_money | normal | 45 caution | 40 caution |

## How this was measured

- `eval/run_eval.py` streams each WAV to `/ws/call` in 1,024-byte frames at real-time pace, one call at a time, and records every event in `eval/results.json`.
- A scam counts as caught if the server sent a `warning` event during the call. A false alarm is a `warning` on a normal call.
- Transcript latency is the `latency_ms` the backend reports on each `transcript` event (from Gnani Prisma), not measured by this script.
- Phone audio: street noise and mains hum added, band-limited to 300-3400 Hz, mu-law at 8 kHz, back to 16 kHz. See `eval/make_audio.py`.
- Server `/health`: `{"ok": true, "engine": "backend.risk", "gnani_key_set": true, "warning_audio_ready": true, "family_devices": 0, "llm_judge": {"state": "failing", "detail": "HTTP 401: {\"error\":{\"message\":\"Invalid API Key\",\"type\":\"invalid_request_error\",\"code\":\"invalid_api_key\"}}\n"}}`

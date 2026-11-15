# Session A: audio backend

Read `PLAN.md` and `backend/contract.py` first. They define the rules, the event shapes and the
Gnani API facts. You own `backend/server.py`, `backend/gnani_stt.py`, `backend/gnani_tts.py` and
`backend/tests_audio/`. Deadline for a working piece: 14:30 IST today.

## Goal

A FastAPI app that accepts microphone audio from the browser on `/ws/call`, relays it to Gnani's
streaming speech-to-text, and sends back transcript, risk, warning, alert and summary events
exactly as `contract.py` describes.

## Build

1. `backend/gnani_stt.py`: an async client for `wss://api.vachana.ai/stt/v3/stream`. It opens
   the socket with the headers in `PLAN.md`, accepts 1,024-byte frames, and yields each
   `transcript` message. Surface `error` messages and refused handshakes (401, 402, 403, 429)
   as clear exceptions with the server's message in them.
2. `backend/gnani_tts.py`: `async def synthesize(text, language="hi-IN", voice="Avinash") -> bytes`
   using the REST endpoint, returning WAV bytes. Retry 429 and 5xx with 0.5, 1, 2 s backoff.
3. `backend/server.py`:
   - `GET /health`, and serve `frontend/` as static files at `/` if the folder exists.
   - `/ws/call`: on `start`, open the Gnani stream and send `status: listening`. Forward binary
     frames. If a frame is not exactly 1,024 bytes, re-chunk it; never drop audio.
   - For each sentence: send `transcript`, call `engine.add_sentence()`, send the `risk` event,
     then start `engine.judge()` as a background task and send its `risk` event when it returns.
     Never let a slow or failed judge block the audio path.
   - When an update has `should_warn`, send `warning` with the Hindi text and base64 WAV, then
     `alert`. Synthesize the warning audio when the call starts so it is ready instantly.
   - On `stop` or disconnect: close the Gnani stream, send `summary`, then `status: ended`.
   - Track `t_ms` from the count of audio bytes received, not wall-clock time.
4. Import the engine with `from backend.risk import RiskEngine`. Session B is writing it now. Until
   it exists, fall back to a small stub in `server.py` with the same three methods, so you are
   never blocked. Remove the fallback only if B's version is present and its tests pass.

Warning text (keep it short, one breath):
"Saavdhaan. Yeh call ek scam ho sakta hai. Koi bhi police ya bank phone par paise ya OTP nahi
maangta. Call kaat dijiye aur unnees sau tees par sampark kijiye."

## Prove it works

- `backend/tests_audio/smoke_stt.py`: synthesize one Hindi sentence with Timbre, stream it into
  Gnani STT in real-time-paced frames, print the transcript and latency.
- `backend/tests_audio/smoke_ws.py`: connect to your own `/ws/call`, stream that same WAV, print
  every event received. This is the proof; run it and show the output.
- Run the server: `.\.venv\Scripts\python.exe -m uvicorn backend.server:app --port 8000`.

If `GNANI_API_KEY` is missing from `.env`, build everything, test what you can without it, and
say clearly which checks were not run.

## Report back

How to run it, what was verified with real output, what was cut, and any place the Gnani API
behaved differently from `PLAN.md`.

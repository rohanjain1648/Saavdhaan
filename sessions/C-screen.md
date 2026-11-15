# Session C: the live call screen

Read `PLAN.md` and `backend/contract.py` first. You own `frontend/` and `mock/` only. Deadline
for a working piece: 14:30 IST today.

## Goal

The one screen that will be recorded for a 60–90 second LinkedIn and X video. A viewer with the
sound off, on a phone, must understand within five seconds: a call is being listened to, it is
turning dangerous, and the guardian stepped in. Plain HTML, CSS and JavaScript with no build
step, served as static files by the backend.

## Build

1. `mock/mock_server.py` first (FastAPI, port 8000, path `/ws/call`): accept the client messages
   in `contract.py`, ignore the audio, and replay a scripted scam call as timed `transcript`,
   `risk`, `warning`, `alert` and `summary` events. For `audio_b64` use a short generated tone
   WAV. This lets you build without the real backend, which Session A is writing in parallel.
   Also serve `frontend/` at `/`.
2. `frontend/index.html`, `app.js`, `styles.css`, `pcm-worklet.js`:
   - Microphone capture with an AudioWorklet, in an `AudioContext` at 16,000 Hz, mono. Turn
     `echoCancellation`, `noiseSuppression` and `autoGainControl` off, since the microphone is
     meant to hear a phone on speaker. Send PCM16 little-endian frames of exactly 1,024 bytes.
   - Start and Stop buttons. Send `start` and `stop` as in the contract.
   - Live transcript: each sentence appears as it arrives, with the evidence phrases from
     `risk` events highlighted inside it.
   - A large risk meter, 0–100, with the three levels from the contract. It should move
     smoothly, and the whole screen should change state unmistakably at `danger`.
   - The seven tactics as labels that light up when detected. Give them short human names
     ("Pretends to be police", "Asks for OTP"), not the internal ids.
   - On `warning`: play the audio, show the warning text large, and show the time into the call.
   - On `alert`: a phone-notification-style card, visibly marked "simulated".
   - On `summary`: an end-of-call card with tactics, evidence, time to first warning and the
     1930 helpline.
   - A small persistent line: "Demo: speakerphone mode, synthetic call".
   - Show `error` events and a dropped connection clearly; never fail silently.
3. Layout: must look right recorded at 1920×1080 and stay legible when the video is watched on
   a phone, so use large type and few elements. Screen text in English, with the transcript in
   whatever script arrives (Devanagari must render).

The WebSocket address is the same host that served the page, path `/ws/call`, so the same files
work against the mock and the real backend with no change.

## Prove it works

Run `.\.venv\Scripts\python.exe -m uvicorn mock.mock_server:app --port 8000`, open
`http://localhost:8000`, and drive the full flow in a real browser: start, transcript appears,
meter climbs, warning plays, alert shows, stop, summary shows. Check the browser console is
clean and that the frames sent are 1,024 bytes each. If the real backend is up by then, repeat
against it.

## Report back

How to run it, what you saw working, and what was cut.

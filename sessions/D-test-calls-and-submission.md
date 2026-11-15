# Session D: test calls, metrics and submission text

Read `PLAN.md` and `backend/contract.py` first. You own `eval/` and `submission/` only. Deadlines
today: audio files by 13:30 IST, everything else by 14:45.

## Goal

Three things: synthetic phone calls to test and demo with, an honest metrics run over them, and
the words for the public post and the submission form. This is a contest entry by a student for
Gnani AI's "Great Indian AI Internship Challenge". Its rules require synthetic data only and
forbid misleading demos, so every number must come from a run that actually happened.

## 1. Synthetic calls (do this first; Session A needs one file early)

- `eval/scripts/`: 8 two-speaker call scripts as JSON, each a list of `{speaker, text}` turns,
  about 45–75 seconds when spoken. Four scams (fake CBI digital arrest, fake customs parcel,
  fake bank KYC asking for an OTP, fake TRAI SIM disconnection) and four normal calls (bank
  relationship manager, courier asking directions, family money chat, clinic reminder).
  Natural Hinglish as people really speak it. The victim's lines matter too: hesitation, fear.
  Invented names only; no real phone, account, Aadhaar or PAN numbers; write numbers as words.
  The normal calls should share vocabulary with the scams ("account", "parcel", "verify"), or
  the comparison is too easy to mean anything.
- `eval/make_audio.py`: voice each turn with Gnani Timbre (endpoint and voices in `PLAN.md`),
  one voice per speaker, and join the turns with short pauses into one WAV per call at
  16 kHz mono PCM16. Cache every clip on disk so a rerun costs no credits. Requests go one at
  a time, with backoff on 429.
- Then make a "phone line" version of each: band-limit to 300–3400 Hz, add background noise
  (generate it: street-like noise, hum), and resample 16 k → 8 k → 16 k. `ffmpeg` is installed;
  `numpy` and `soundfile` are in the venv.
- Output: `eval/audio/clean/*.wav` and `eval/audio/phone/*.wav`, plus `eval/audio/manifest.json`
  with the label (scam or normal) per file. Finish one scam file first and tell the human its
  path, so Session A can test with it.

## 2. Metrics run

`eval/run_eval.py`: for each WAV, connect to `ws://localhost:8000/ws/call`, send `start`, stream
the file in 1,024-byte frames at real-time pace, send `stop`, and record every event. One call
at a time. Write `eval/results.json` and a short `eval/RESULTS.md` table:

- scams caught (a `warning` was sent) out of 4, and false alarms on the 4 normal calls,
  for clean audio and for phone audio separately;
- seconds from call start to the warning, per scam call;
- median transcript latency as reported in the events.

Build and check the script against `mock/mock_server.py` if the real backend is not up yet.
State the sample size plainly: 8 calls is a smoke test, not a benchmark, and the write-up must
say so.

## 3. Submission text, in `submission/`

Write for people scrolling LinkedIn and X, and for Gnani's reviewers. Plain, specific, no hype.

- `linkedin_post.md` and `x_post.md`. Both tag Gnani AI and include
  `#GreatIndianAIInternshipChallenge` and `#GnaniAI`. Lead with the problem in one line that
  any Indian family recognises. Say what it does, which Gnani models it uses (Prisma v3.0
  speech-to-text, Timbre v3.0 text-to-speech), and that the demo uses a synthetic call played
  on speakerphone. Leave `[RESULTS]` placeholders for numbers until the run has happened.
- `video_script.md`: a shot list for a 60–90 second screen recording with voice-over, including
  a first 3 seconds that work with the sound off.
- `form_answers.md`: project title, the problem, who will use it, the Gnani models and APIs
  used, and a contribution line for a solo participant. Add a short "what is real today, what
  is next" section: today, browser microphone in speakerphone mode; next, a call-merge phone
  line, a self-hosted Evon model so transcripts stay in India, consent and no audio storage.

## Report back

File paths, the credit balance before and after if you can see it, the results table if the
run happened (or a clear statement that it did not), and what was cut.

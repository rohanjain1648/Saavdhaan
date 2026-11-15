# Demo video: 60 seconds

Target: 60 s (the Demo Day Drop award is for the best 60-second demo). Lead with noisy phone-line
audio, because that is the strongest category for this project (Noise Canceller).

Most people watch muted on a phone, so **every shot has a burned-in caption**: white, bold, large,
bottom third, at most 8 words. Voice-over is optional; the captions must carry the story alone.

The call is `eval/audio/phone/scam_cbi_digital_arrest.wav`: a synthetic scam call voiced with Gnani
Timbre, degraded to noisy phone-line quality, played on a speaker next to the laptop. The times
below are from the real run of that file (warning at 0:33).

## Shot list

| Video time | Picture | Caption | Voice-over (optional) |
|---|---|---|---|
| 0:00–0:03 | **Cold open on the payoff**: screen red, "Scam call. Saavdhaan stepped in.", meter at 100, warning card. | A fake "CBI officer" called. It stepped in. | (none: must work muted) |
| 0:03–0:08 | Black card, white text. | "Digital arrest" scams: fake CBI, police, customs, bank | "Fake officers call, say you're under digital arrest, and keep you on the line until you pay." |
| 0:08–0:12 | Ready screen, then press **Start listening**. | Test call. Noisy phone-line audio. On speaker. | "This is a scripted test call, with phone-line noise, played on speaker." |
| 0:12–0:22 | Live transcript (call 0:12–0:31): "मैं CBI मुंबई branch से inspector…", "…Aadhaar card पर money laundering case…". Meter climbs, "Pretends to be police" lights up. *Jump-cut the dead air; never speed up.* | Gnani Prisma transcribes Hinglish live | "Gnani's Prisma model transcribes it live: Hindi and English, mixed." |
| 0:22–0:26 | "आपके नाम पर arrest warrant जारी हो चुका है।" appears. Screen turns red: **Danger**. | Police + threat = danger | "Police, plus a threat. That's the pattern." |
| 0:26–0:36 | Warning card at **0:33 into the call**; the Hindi warning plays aloud. Keep about 8 s of it. | "This may be a scam. Hang up. Call 1930." | (none: let the warning speak) |
| 0:36–0:42 | Cut to the **family page**: "Possible scam call right now" with the caller's quoted words. Then the call screen's card: "Delivered to 1 device". | Family gets the alert, with the caller's words | "And the family is told, with the caller's own words." |
| 0:42–0:47 | Press **Stop**; the summary card: tactics, quotes, first warning at 0:33, 1930. | Every tactic, every quote, the helpline | "At the end: what was said, and where to report it." |
| 0:47–0:55 | Results card: **Noisy phone line: 4 of 4 scams caught, 0 of 4 false alarms, 75 ms transcription.** Small text: "8 synthetic calls. Smoke test, not a benchmark." | 4/4 scams caught on noisy phone audio | "On noisy phone audio: four of four scams caught, no false alarms." |
| 0:55–1:00 | End card: Saavdhaan · your name · "Built with Gnani Prisma v3.0 + Timbre v3.0" · #GreatIndianAIInternshipChallenge #GnaniAI | (same as picture) | (none) |

## Recording it (Windows 11)

**Before you record**

1. Check the server: open http://localhost:8000/health and confirm `"gnani_key_set": true` and
   `"warning_audio_ready": true`.
2. Do one full rehearsal run and confirm you hear the warning. Load the page once and don't reload
   it during takes.
3. Turn off notifications (Focus assist) and close other tabs.

**Take 1: the call screen** (most of the video)

1. Open http://localhost:8000 in Chrome and press **F11** for full screen. Keep this window in
   front the whole time: Chrome holds back sound in a covered window.
2. Start recording with **Win + Alt + R** (Xbox Game Bar records the active window with system
   sound). Files go to `Videos\Captures`.
3. Press **S** (Start listening), then play
   `D:\downloads\gnan ai\eval\audio\phone\scam_cbi_digital_arrest.wav` from your phone held next to
   the laptop, or from the laptop speakers. With the laptop speakers, the recording captures the
   call audio too.
4. Let it run past the warning (0:33) to about 0:50, press **S** to stop, and wait for the summary.
   Stop the recording with **Win + Alt + R**.

**Take 2: the family alert** (5 seconds of footage)

1. Open http://localhost:8000/family.html in a separate, narrow Chrome window (about phone width).
2. Start the call again in the call-screen tab (press S and play the file), switch to the family
   window, and record it (Win + Alt + R) until the alert card appears at about 0:33.

**Edit** in Clipchamp (built into Windows): jump-cut the pauses, add the captions, the black problem
card, the results card and the end card. Export at 1080p.

## Honesty rules (the contest disqualifies misleading demos)

- Use only takes against the real backend, never the mock server.
- Cutting dead air is fine; never speed up the transcript or move the warning. The "0:33 into the
  call" on screen is the real time.
- Keep "Test call" visible in the 0:08 caption so nobody mistakes it for a real call or person.
- The results card numbers come from `eval/RESULTS.md` only.
- The microphone pauses while the warning plays (about 12 s), so a few caller lines in that window
  won't appear in the transcript. That is expected; don't add them back.

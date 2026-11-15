# Demo video: about 2 minutes 10 seconds

**Length:** the submission needs 2–3 minutes. X accounts without Premium can upload video only up to
**2:20**, so aim for **2:05–2:15**: that meets the requirement and posts to X without trimming.
LinkedIn takes it as is.

**Story:** a scam call it catches, then a real bank call it lets through. The second half shows
it doesn't cry wolf, which matters as much as the catch. Lead with noisy phone-line audio, the
project's strongest award category (Noise Canceller).

Most people watch muted, so **every shot has a burned-in caption**: white, bold, large, bottom third,
at most 8 words. Voice-over is recommended but the captions must carry the story alone.

All calls are synthetic: scripts written for this project, voiced with Gnani Timbre, degraded to
noisy phone-line quality, played on a speaker next to the laptop. Times in brackets are call times
from the real test run.

## Shot list

| Video | Picture | Caption | Voice-over |
|---|---|---|---|
| **0:00–0:04** | Cold open on the payoff: red screen, "Scam call. Saavdhaan stepped in.", meter at 100, warning card. | A fake "CBI officer" called. It stepped in. | (none) |
| **0:04–0:14** | Black card, white text, one line at a time: "I'm from the CBI." / "You are under digital arrest." / "Don't tell anyone." | Every family in India knows this call | "I'm from the CBI. You're under digital arrest. Don't tell anyone. Move your money to a safe account. Thousands of families have heard this call." |
| **0:14–0:22** | Title "Saavdhaan", then the ready screen; phone on speaker beside the laptop. | A live guardian for scam calls | "Saavdhaan listens to the call on speakerphone and steps in before the money moves. This is a scripted test call with phone-line noise." |
| **0:22–0:38** | Press **Start**. Transcript arrives: "मैं CBI मुंबई branch से inspector…" [0:12], "…Aadhaar card पर money laundering case…" [0:16]. "Pretends to be police" lights up. Jump-cut the pauses. | Gnani Prisma transcribes Hinglish, live | "Gnani's Prisma model transcribes it live, Hindi and English mixed the way people speak, even on a noisy line." |
| **0:38–0:44** | "आपके नाम पर arrest warrant जारी हो चुका है।" [0:31]. Screen turns red: **Danger**; "Threatens arrest" lights up. | Police + threat = danger | "Every sentence is checked for scam tactics. Police plus a threat: danger." |
| **0:44–0:56** | Warning card, **"at 0:33 into the call"**; the Hindi warning plays aloud. Keep 10–12 s of it. | "This may be a scam. Hang up. Call 1930." | (none: let the warning speak) |
| **0:56–1:06** | Family page (take 2): "Possible scam call right now", the tactics and the caller's quoted words. Then the call screen card: "Delivered to 1 device". | The family gets the alert, with the caller's words | "At the same moment, the family is alerted, with exactly what the caller said." |
| **1:06–1:14** | Press **Stop**; summary card: tactics, quotes, first warning at 0:33, 1930. | Every tactic. Every quote. The helpline. | "When the call ends: what was said, and where to report it." |
| **1:14–1:18** | Black card. | But a real bank calls too. | "But a scam detector that cries wolf is useless. Real banks call too." |
| **1:18–1:38** | Take 3, the bank call: "मैं सहयोग बैंक… relationship manager…" [0:07], "…savings account में transfer…" [0:20], "…KYC…" [0:34], "PAN card और Aadhaar…" [0:42]: meter goes to **Caution 40** and stops. "बैंक अभी phone पर OTP या PIN नहीं मांगता।" [0:52]. No warning. | Same words: account, KYC, OTP. No alarm. | "This bank call uses the same words: account, transfer, KYC, Aadhaar, OTP. It gets cautious, but it never raises an alarm. One word isn't a scam; the combination is." |
| **1:38–1:50** | Diagram card: browser mic → **Gnani Prisma v3.0** (streaming, code-mix) → risk engine (7 tactics) → **Gnani Timbre v3.0** spoken warning → family page. | Built on Gnani Prisma + Timbre | "Under the hood: Prisma v3.0 streaming speech-to-text, a risk engine for seven tactics, and Timbre v3.0 to speak the warning." |
| **1:50–2:00** | Results card: **Noisy phone line: 4/4 scams caught · 0/4 false alarms · 75 ms transcription**. Small text: "8 synthetic calls, clean and phone-line. Smoke test, not a benchmark." | 4/4 scams caught. 0 false alarms. | "On eight test calls with phone-line noise: four of four scams caught, zero false alarms." |
| **2:00–2:06** | Card: "Next: a real phone line · transcripts stay in India (Gnani Evon) · more Indian languages". *If the Tamil test passed, show 3 s of the Tamil warning card here instead.* | Next: a real phone line, more languages | "Next: a real phone line, transcripts kept in India, and more Indian languages." |
| **2:06–2:12** | End card: Saavdhaan · your name · "Built with Gnani Prisma v3.0 + Timbre v3.0" · 1930 · #GreatIndianAIInternshipChallenge #GnaniAI | (same as picture) | "If you get this call: hang up, and call 1930." |

## Recording it (Windows 11)

**Before you record**

1. Open http://localhost:8000/health: `"gnani_key_set": true` and `"warning_audio_ready": true`.
2. Do one rehearsal and confirm you hear the warning. Load the page once; don't reload between
   takes unless something breaks.
3. Turn on Focus assist (no notifications) and close other tabs.

**Take 1: scam call** (0:22–1:14)

1. Open http://localhost:8000 in Chrome, press **F11**, and keep it in front: Chrome holds back
   sound in a covered window.
2. **Win + Alt + R** starts recording (Xbox Game Bar, records the window with system sound; files
   go to `Videos\Captures`).
3. Press **S**, then play `D:\downloads\gnan ai\eval\audio\phone\scam_cbi_digital_arrest.wav` from
   your phone next to the laptop, or from the laptop speakers (then the recording also has the
   call audio).
4. Let it run to about 0:50 of the call, press **S**, wait for the summary, **Win + Alt + R** to stop.

**Take 2: family alert** (0:56–1:06)

Open http://localhost:8000/family.html in a narrow Chrome window. Start the scam call again from
the call screen (press S, play the file), switch to the family window, record until the alert
appears at about 0:33.

**Take 3: bank call** (1:18–1:38)

Same as take 1 with `eval\audio\phone\normal_bank_rm.wav`; stop after about 0:55 of the call.

**Cards**: problem, "But a real bank calls too", diagram, results, next, end. Make them as title
cards in Clipchamp, or use the ready-made images if provided.

**Edit** in Clipchamp (built into Windows): jump-cut pauses, add captions and voice-over, export
1080p. Check the length is under 2:20 before posting to X.

## Honesty rules (the contest disqualifies misleading demos)

- Real-backend takes only, never the mock server.
- Cut dead air, but never speed up the transcript or move the warning: "0:33 into the call" on
  screen is the real time.
- Keep "test call" in the 0:14 caption so nobody mistakes it for a real person.
- Results come from `eval/RESULTS.md` only. Scoring for those results was keyword rules only.
- The microphone pauses while the warning plays (about 12 s), so a few caller lines in that window
  don't appear in the transcript. That's expected; don't add them back.
- Show Tamil only if its live test passed, and only as the real screen.

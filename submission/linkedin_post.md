# LinkedIn post

<!--
Before posting:
1. In the LinkedIn editor, type "@Gnani" and pick the Gnani.ai company page so the tag is real.
2. Replace [RESULTS] with numbers from eval/RESULTS.md (real run only, never the mock run).
   Template: "it warned on X of 4 scam calls (median Y seconds into the call) and on Z of 4 normal calls.
   On the same calls degraded to phone quality: X2 of 4 and Z2 of 4."
3. Upload the video directly (not as a link). Put the repo link in the first comment if you share it.
-->

Somebody in almost every Indian family has had this call by now: "I'm from the CBI. Your Aadhaar is linked to a drugs parcel. You are under digital arrest. Don't tell anyone."

I built Saavdhaan for the people who pick up that call.

It listens to a phone call on speakerphone and transcribes it live, in Hindi and English mixed the way people actually speak. Every sentence is checked for the tactics these scams depend on: pretending to be police, customs or the bank, "digital arrest", a deadline with a threat, "don't tell your family", "move your money to a safe account", "read me the OTP". When the risk stays high, it says a warning out loud in Hindi and pushes a live alert, with the caller's exact words, to a family member's phone.

Gnani models used:
• Prisma v3.0 speech-to-text, streaming, Hindi-English code-mix
• Timbre v3.0 text-to-speech, for the spoken warning and to voice the test calls

The video uses a synthetic call: a scam script I wrote, voiced with Timbre and played on speakerphone next to the laptop. No real call, person or phone number is involved.

On 8 synthetic test calls (4 scams, and 4 normal calls that use the same words, like "account", "parcel" and "OTP"), it warned on all 4 scams (median 50 seconds into the call) and on none of the 4 normal calls. With the same calls degraded to noisy phone-line quality: again 4 of 4 and 0 of 4. Median transcription latency reported by Prisma: under 100 ms per sentence. Eight calls is a smoke test, not a benchmark.

What it is not yet: it works through a browser microphone today. Next is a call-merge phone line so it needs no laptop, a self-hosted model so transcripts stay in India, clear consent, and no audio stored.

Built for the Great Indian AI Internship Challenge by @Gnani.ai.

#GreatIndianAIInternshipChallenge #GnaniAI

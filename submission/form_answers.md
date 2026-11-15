# Submission form answers

Fill the [BRACKETS] before submitting. Every number must come from a real run in eval/RESULTS.md.

## Project title

Saavdhaan: a live guardian for "digital arrest" scam calls

## The problem

"Digital arrest" and impersonation scams are now a common phone fraud in India. A caller poses as
CBI, customs, TRAI, the police or a bank, says the victim is linked to a crime, keeps them on the
call (often on video) for hours, forbids them to tell their family, and gets them to move money to a
"safe account" or read out an OTP. The victims are often older people at home alone. By the time a
son or daughter hears about it, the money has gone. People are told "police never call like this",
but in the moment, scared and isolated, they don't remember it. What's missing is something on the
call that says so out loud, at the right moment, in their language.

## Who will use it

- Older parents and people who live alone, who are the most targeted and the least able to check a
  caller's story in the moment.
- Their families, who would set it up and receive the alert.
- Later: banks, telecom operators and cyber-crime cells, as an opt-in protection that speaks Indian
  languages.

## What it does

Saavdhaan listens to a call on speakerphone and transcribes it live in Hindi-English code-mix. Each
sentence is scored for seven tactics: authority impersonation, "digital arrest", urgency and threats,
isolation and secrecy, money transfer, requests for OTP, PIN or Aadhaar details, and remote-access
apps. When the risk stays at "danger" for two updates in a row, it speaks a Hindi warning out loud
("This call may be a scam. Police and banks never ask for money or an OTP on the phone. Hang up and
call 1930."), pushes a live alert to every family device that has the family page open (the call
screen shows how many devices received it), and gives an end-of-call summary with the
evidence quotes and the 1930 helpline.

## Gnani models and APIs used

- **Prisma v3.0, streaming speech-to-text** (`wss://api.vachana.ai/stt/v3/stream`), with
  `language_code: hi-IN` and `format: codemix`, 16 kHz PCM16 in 1,024-byte frames. Turns the
  live call into one transcript per sentence.
- **Timbre v3.0, text-to-speech** (`POST https://api.vachana.ai/api/v1/tts/inference`). Speaks the Hindi
  warning during the call (voice Avinash). Also used to voice the 8 synthetic test calls, with 8 other
  voices, one per speaker.
- Not Gnani: the risk scoring is keyword rules for seven scam tactics, in Devanagari and Latin script.
  An optional LLM second opinion (any OpenAI-compatible API) is built in; it was not active for the
  results below, which are keyword rules only.

## Results (synthetic data only)

8 synthetic calls: 4 scams (fake CBI digital arrest, fake customs parcel, fake bank KYC asking for an
OTP, fake TRAI SIM disconnection) and 4 normal calls that use the same vocabulary (bank relationship
manager, courier asking directions, a family money chat, a clinic reminder), each in clean and
phone-quality versions. Scams warned: 4/4 clean and 4/4 phone. False alarms: 0/4 clean and 0/4
phone. Median time from call start to the spoken warning: 50 s (range 33 to 67 s). Median transcript
latency reported by Prisma: 81 ms clean, 75 ms phone (514 sentences). Risk scoring for this run was
keyword rules only. Run on 15 Nov 2026 at real-time speed against the live Gnani APIs. This is a
smoke test, not a benchmark. Scripts, audio pipeline and raw event logs are in `eval/`.

## Contribution (solo participant)

Solo project. I designed and built all of it: the streaming audio backend and Gnani integration,
the scam-tactic risk engine, the live call screen, the synthetic test calls and the evaluation, and
this write-up. [CONFIRM or edit: I used AI coding assistants for parts of the code.]

## What is real today, what is next

**Real today**
- Runs on a laptop: the browser microphone listens to a phone on speakerphone, and the backend streams
  the audio to Gnani Prisma and speaks the warning with Gnani Timbre.
- The demo call is synthetic: a script written for this project, voiced with Timbre and played on
  speaker. The family alert is delivered live over the network to a family page (for example on a
  relative's phone), with the tactics and quoted evidence; a "call ended" update follows.

**Next**
- A call-merge phone line, so the guardian joins the call as a third party and needs no laptop.
- A self-hosted Gnani Evon model, so transcripts stay in India.
- Consent from everyone on the call, and a firm rule that no call audio is stored.
- Family alerts by SMS or WhatsApp as well as the family page, and more languages for the warning.

## Links

- Demo video: [VIDEO LINK]
- LinkedIn post: [LINKEDIN LINK]
- X post: [X LINK]
- Code: [REPO LINK, if shared]

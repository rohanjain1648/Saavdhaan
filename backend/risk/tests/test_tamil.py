"""Tamil / Tanglish calls through the keyword engine.

Transcripts mimic Gnani Prisma with language_code=ta-IN and format=codemix: Tamil script, English
words in Latin letters, often with a Tamil case ending after a hyphen ("arrest-ல", "OTP-ஐ").
All names are invented; no real numbers.
"""
import asyncio

import pytest

from backend.risk import LLMConfig, RiskEngine

NO_LLM = LLMConfig(base_url="https://llm.test/v1", api_key="", model="m")

TA_SCAMS = {
    "ta_cbi_digital_arrest": [
        "வணக்கம், நான் Mumbai CBI cyber crime branch-ல இருந்து inspector ராஜேஷ் பேசறேன்.",
        "உங்க Aadhaar card-ல ஒரு money laundering case பதிவாகியிருக்கு.",
        "உங்க பேர்ல arrest warrant வந்திருக்கு.",
        "இப்போ நீங்க digital arrest-ல இருக்கீங்க, video call-ஐ cut பண்ணக்கூடாது.",
        "இதை யார்கிட்டயும் சொல்லாதீங்க, உங்க பையன்கிட்ட கூட.",
        "Verification-க்கு உங்க பணம் எல்லாத்தையும் RBI safe account-க்கு transfer பண்ணுங்க.",
    ],
    "ta_bank_kyc_otp": [
        "Sir, நான் State Bank KYC department-ல இருந்து பேசறேன்.",
        "உங்க KYC update ஆகலைன்னா இன்னைக்கே உங்க account block ஆகிடும்.",
        "இப்போ உங்க mobile-க்கு ஒரு OTP வந்திருக்கும்.",
        "அந்த OTP-ஐ உடனே சொல்லுங்க, இல்லைன்னா account freeze ஆகிடும்.",
        "போலீஸ் case போடுவாங்க, சீக்கிரம் சொல்லுங்க.",
    ],
}

TA_NORMALS = {
    "ta_bank_relationship_manager": [
        "வணக்கம் sir, நான் உங்க bank relationship manager பிரியா பேசறேன்.",
        "உங்க fixed deposit அடுத்த வாரம் mature ஆகுது.",
        "Renew பண்ணணுமா, இல்ல savings account-க்கு transfer பண்ணணுமா?",
        "KYC-க்கு branch வரும்போது Aadhaar copy கொண்டு வாங்க.",
        "ஞாபகம் வச்சுக்கோங்க, OTP-ஐ யார்கிட்டயும் சொல்லாதீங்க, bank ஒருபோதும் OTP கேட்காது.",
    ],
    "ta_courier_directions": [
        "Hello madam, நான் Blue Dart courier-ல இருந்து பேசறேன்.",
        "உங்களுக்கு ஒரு parcel வந்திருக்கு, address கண்டுபிடிக்க முடியல.",
        "கோயில் பக்கத்துல எந்த தெரு?",
        "Delivery ஆனதும் ஒரு OTP வரும், அதை என்கிட்ட சொல்லுங்க.",
        "சரி madam, பத்து நிமிஷத்துல வந்துடறேன்.",
    ],
}


def run(sentences, judge_each=False):
    engine = RiskEngine(NO_LLM)

    async def go():
        out = []
        for s in sentences:
            out.append(engine.add_sentence(s))
            if judge_each:
                out.append(await engine.judge())
        return out

    return asyncio.run(go())


@pytest.mark.parametrize("judge_each", [False, True], ids=["add-only", "add+judge"])
@pytest.mark.parametrize("name", TA_SCAMS)
def test_tamil_scam_reaches_danger_and_warns_once(name, judge_each):
    updates = run(TA_SCAMS[name], judge_each)
    assert max(u.score for u in updates) >= 70, [(u.score, u.tactics) for u in updates]
    assert sum(u.should_warn for u in updates) == 1


@pytest.mark.parametrize("name", TA_NORMALS)
def test_tamil_normal_call_never_reaches_danger(name):
    updates = run(TA_NORMALS[name], judge_each=True)
    assert all(u.level != "danger" for u in updates), [(u.score, u.tactics) for u in updates]
    assert not any(u.should_warn for u in updates)


def test_tamil_never_share_otp_advice_is_not_a_credential_request():
    updates = run(["ஞாபகம் வச்சுக்கோங்க, OTP-ஐ யார்கிட்டயும் சொல்லாதீங்க, bank ஒருபோதும் OTP கேட்காது."])
    assert "credential_request" not in updates[-1].tactics
    assert "isolation_secrecy" not in updates[-1].tactics


def test_tamil_case_endings_after_english_words_still_match():
    updates = run(["இப்போ நீங்க digital arrest-ல இருக்கீங்க."])
    assert "digital_arrest" in updates[-1].tactics

import re

import pytest

from backend.contract import DANGER_AT, TACTICS
from backend.risk.keywords import (COMPILED, PHRASES, QUOTE_MAX, STRONG, KeywordTracker,
                                   match_sentence, normalize, score_weights)


def tactics_of(sentence: str) -> dict[str, int]:
    return {t: w for t, (w, _) in match_sentence(sentence).items()}


def test_phrase_lists_cover_exactly_the_contract_tactics():
    assert set(PHRASES) == set(TACTICS)


def test_no_placeholder_leaked_into_a_pattern():
    # e.g. "{gap(2)}" left literal because a pattern was written r"" instead of rf""
    for p in COMPILED:
        assert not re.search(r"\{[A-Za-z]", p.pattern.pattern), p.pattern.pattern[:80]


@pytest.mark.parametrize("tactic", TACTICS)
def test_one_tactic_alone_never_reaches_danger(tactic):
    strongest = max(w for t, items in PHRASES.items() if t == tactic for _, w in items)
    assert score_weights({tactic: strongest}) < DANGER_AT


def test_authority_threat_and_money_or_credential_reach_danger_even_at_minimum_strength():
    base = {"authority_impersonation": STRONG, "urgency_threat": STRONG}
    assert score_weights({**base, "money_transfer": STRONG}) >= DANGER_AT
    assert score_weights({**base, "credential_request": STRONG}) >= DANGER_AT


def test_combinations_count_for_more_than_their_parts():
    a = score_weights({"authority_impersonation": 25})
    b = score_weights({"urgency_threat": 25})
    assert score_weights({"authority_impersonation": 25, "urgency_threat": 25}) > a + b


def test_digital_arrest_phrase_alone_stays_below_danger():
    t = KeywordTracker()
    t.add("Aap digital arrest mein hain.")
    assert t.score < DANGER_AT


@pytest.mark.parametrize("latin, devanagari, tactic", [
    ("Main CBI se bol raha hoon", "मैं सीबीआई से बोल रहा हूँ", "authority_impersonation"),
    ("Aap digital arrest mein hain", "आप डिजिटल अरेस्ट में हैं", "digital_arrest"),
    ("Aapke naam par arrest warrant hai", "आपके नाम पर अरेस्ट वारंट है", "urgency_threat"),
    ("Kisi ko mat bataiye", "किसी को मत बताइए", "isolation_secrecy"),
    ("Paise safe account mein transfer kijiye", "पैसे सेफ अकाउंट में ट्रांसफर कीजिए", "money_transfer"),
    ("OTP bataiye", "ओटीपी बताइए", "credential_request"),
    ("AnyDesk download kijiye", "एनीडेस्क डाउनलोड कीजिए", "remote_access_app"),
])
def test_both_scripts_match(latin, devanagari, tactic):
    assert tactics_of(latin).get(tactic, 0) >= STRONG
    assert tactics_of(devanagari).get(tactic, 0) >= STRONG


@pytest.mark.parametrize("misheard, tactic", [
    ("aap digital arest mein ho", "digital_arrest"),
    ("dijital arrest", "digital_arrest"),
    ("Aadhar number batayiye", "credential_request"),
    ("AnyDisk app kholiye", "remote_access_app"),
    ("safe acount mein bhejiye", "money_transfer"),
    ("pulis station se bol raha hoon", "authority_impersonation"),
])
def test_common_misspellings_match(misheard, tactic):
    assert tactics_of(misheard).get(tactic, 0) >= STRONG


def test_nukta_and_chandrabindu_are_folded():
    assert normalize("फ़ोन मत काटिए") == normalize("फोन मत काटिए")
    assert normalize("माँगता") == normalize("मांगता")
    assert tactics_of("कृपया फ़ोन मत काटिए") == tactics_of("कृपया फोन मत काटिए")


def test_bank_safety_advice_is_not_a_credential_or_secrecy_hit():
    hits = tactics_of("Bank kabhi bhi phone par OTP ya PIN nahi maangta, kisi ko mat bataiye.")
    assert "credential_request" not in hits and "isolation_secrecy" not in hits


def test_everyday_words_are_not_tactics():
    assert "money_transfer" not in tactics_of("मैं आपका कॉल नारकोटिक्स डिपार्टमेंट को ट्रांसफर कर रही हूँ।")
    assert "credential_request" not in tactics_of("Pin code wahi hai na jo order mein likha hai?")
    assert "remote_access_app" not in tactics_of("Aap MyJio app se recharge kar sakte hain.")


def test_a_threat_outweighs_a_status_report():
    threat = tactics_of("Aapka number do ghante mein band kar diya jayega.")["urgency_threat"]
    status = tactics_of("Aapka number band aa raha tha.")["urgency_threat"]
    assert threat > status


def test_weak_hits_add_points_but_are_not_reported_as_tactics():
    t = KeywordTracker()
    t.add("Main HDFC bank se bol rahi hoon.")
    assert t.score > 0 and t.tactics == [] and t.evidence() == []


def test_evidence_is_a_short_clause_of_the_sentence():
    sentence = ("Namaste ji, aapka bill pending hai, " * 4 +
                "isliye abhi AnyDesk download kijiye, nahi toh bijli kaat di jayegi.")
    t = KeywordTracker()
    t.add(sentence)
    assert t.evidence()
    for quote in t.evidence():
        assert len(quote) <= QUOTE_MAX + 1
        assert quote.rstrip("…") in sentence
    assert any("AnyDesk" in q for q in t.evidence())

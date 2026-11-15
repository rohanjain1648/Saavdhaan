"""Keyword scorer for scam-call tactics.

Input is speech-to-text of noisy phone audio: Hindi in Devanagari or Latin letters, English in
Latin, Hinglish mixed within a sentence, with misheard words. So every phrase lists both
scripts and the spellings STT tends to produce, and text is normalised before matching
(lowercase, nukta and chandrabindu folded, punctuation turned into spaces).

Scoring, per call:
  * each phrase has a weight; a tactic's weight is the strongest phrase seen for it so far
    (repeating a phrase does not add up, so one tactic can never climb on its own);
  * score = sum of tactic weights + COMBO_BONUS for every strong tactic beyond the first;
  * authority + threat + (money or credential) is floored at 80, and a remote-access app
    together with a money or credential request is floored at 75.
Weights run 10 (weak: everyday callers say this too) to 40 ("digital arrest"). A weak hit
adds points but is not reported as a tactic and does not count toward combinations.
The largest single weight is 40, so one tactic alone stays below DANGER_AT (70).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from backend.contract import TACTICS

STRONG = 15          # a tactic at or above this weight is reported and counts in combinations
COMBO_BONUS = 10     # per strong tactic beyond the first
QUOTE_MAX = 120      # characters in an evidence quote

# Characters that make up a "word" after normalisation: Latin, digits and the Devanagari block
# (matras and virama included, which Python's \w does not treat as word characters).
_WORD = "[0-9a-zऀ-ॿ]"
_GAP = r"(?: \S+){0,%d}"  # up to N extra words between two parts of a phrase


def gap(n: int = 4) -> str:
    return _GAP % n


G = gap()      # default gap of up to 4 words
G6 = gap(6)

# ---- word variants (Latin spellings, misspellings, Devanagari) -------------------------------
REQ = r"(?:bata|batay|bataa|bol|bolo|boliye|share|de do|de dijiye|dijiye|send|bhej|read|confirm|verify|tell|give|बता|बोल|शेयर|दीजिए|दीजिये|दे दो|भेज|कन्फर्म|वेरिफाई)\w*"
OTP = r"(?:otp|o t p|ओटीपी|ओ टी पी|ओटिपी)"
MONEY = r"(?:paise|paisa|paison|rupay\w*|rupee\w*|rs|amount|money|funds?|balance|savings?|पैसे|पैसा|पैसों|रुपये|रुपए|रुपया|रकम|राशि|अमाउंट|बैलेंस)"
SEND = r"(?:transfer|tranfer|transfar|bhej|send|jama|deposit|move|ट्रांसफर|ट्रांसफ़र|भेज|जमा|डिपॉजिट)\w*"
ACCOUNT = r"(?:account|acount|accunt|khata|khate|अकाउंट|एकाउंट|खाता|खाते)"
NOT = r"(?:mat|na|nahi|nahin|मत|ना|नहीं|नही)"
SAY = r"(?:bata|bol|baat|kah|keh|बता|बोल|बात|कह)\w*"
ARREST = r"(?:arrest|arest|arrst|ar rest|अरेस्ट|एरेस्ट|अरेस्टेड)\w*"
CALL = r"(?:call|phone|fone|line|कॉल|काल|फोन|फ़ोन|लाइन)"
CUTOFF_TARGET = rf"(?:sim|number|mobile|connection|{ACCOUNT}|bijli|light|meter|सिम|नंबर|मोबाइल|कनेक्शन|बिजली|लाइट|मीटर)"
CUTOFF = r"(?:band|bandh|block|freeze|frozen|suspend|deactivat|disconnect|kaat|kat|seal|बंद|ब्लॉक|फ्रीज|सस्पेंड|डीएक्टिवेट|डिसकनेक्ट|काट|कट|सील)\w*"

# ---- phrase lists ------------------------------------------------------------------------------
# Each entry is (regex fragment, weight). Fragments match whole words; use \w* for "and any
# word ending", and the G / gap(n) helpers for "a few words in between".
PHRASES: dict[str, list[tuple[str, int]]] = {
    "authority_impersonation": [
        (r"cbi|c b i|सीबीआई|सी बी आई|सीबीई|central bureau( of investigation)?", 25),
        (r"police|polis|pulis|पुलिस|पोलिस|thana|थाना|थाने|police station", 25),
        (r"inspector|inspekter|इंस्पेक्टर|इन्स्पेक्टर|constable|हवलदार|dcp|commissioner|कमिश्नर", 25),
        (r"customs?|kastam|कस्टम्स|कस्टम", 25),
        (r"narcotics?|narkotics|नारकोटिक्स|नार्कोटिक्स|ncb|एनसीबी", 25),
        (r"enforcement directorate|प्रवर्तन निदेशालय|ed (?:officer|department|office|se)", 25),
        (r"rbi|r b i|आरबीआई|reserve bank|रिजर्व बैंक|रिज़र्व बैंक", 25),
        (r"trai|ट्राई|telecom regulatory|टेलीकॉम रेगुलेटरी|department of telecom\w*|दूरसंचार विभाग", 25),
        (r"crime branch|cyber cell|cyber crime|cybercrime|साइबर क्राइम|साइबर सेल|क्राइम ब्रांच", 25),
        (r"interpol|fbi|mumbai police|delhi police|मुंबई पुलिस|दिल्ली पुलिस", 25),
        (r"income tax|आयकर|इनकम टैक्स", 20),
        (r"court|supreme court|high court|अदालत|न्यायालय|कोर्ट|judge|जज", 20),
        (r"sarkari (?:officer|adhikari)|government officer|सरकारी अधिकारी", 20),
        (r"head office|हेड ऑफिस|fraud department|kyc department|security department|risk department|bank manager|बैंक मैनेजर", 15),
        (r"(?:bijli|बिजली|electricity|electric|बिजली) (?:vibhag|board|department|office|officer|विभाग|बोर्ड|डिपार्टमेंट|ऑफिस|ऑफिसर|अधिकारी)", 15),
        (r"mseb|bses|discom|power corporation", 15),
        # Everyday callers: banks, couriers, telcos. Weak on purpose.
        (r"officer|ofisar|अफसर|ऑफिसर|अधिकारी|adhikari", 10),
        (r"bank|बैंक|sbi|hdfc|icici|axis|kotak|pnb", 10),
        (r"courier|curier|kurier|कूरियर|कुरियर|fedex|fed ex|फेडेक्स|dhl|blue dart|delhivery|delivery|डिलीवरी", 10),
        (r"customer care|कस्टमर केयर|jio|airtel|vodafone|bsnl|जियो|एयरटेल", 10),
    ],
    "digital_arrest": [
        (rf"(?:digital|dijital|digitel|digi tal|dgital|डिजिटल|डिजीटल|डिजिटली) {ARREST}", 40),
        (rf"(?:virtual|online|ऑनलाइन|वर्चुअल) {ARREST}", 40),
        (r"(?:online|digital|ऑनलाइन|डिजिटल) (?:custody|hirasat|हिरासत|कस्टडी)", 35),
        (rf"video{gap(2)} (?:call|कॉल){G} (?:statement|bayan|bayaan|बयान|interrogation|poochtach|puchtach|पूछताछ|investigation|inquiry|जांच|जाँच)", 30),
        (rf"(?:statement|bayan|bayaan|बयान|interrogation|poochtach|पूछताछ){G} (?:video|वीडियो)", 30),
        (rf"(?:वीडियो|video) (?:call|कॉल){G} (?:par|pe|mein|पर|पे|में) (?:rah|bane|reh|रह|बने)\w*", 30),
        (r"skype|स्काइप|स्काईप", 25),
        (rf"camera (?:on|chalu|ऑन|चालू){G} (?:rakh|kar|रख|कर)\w*|कैमरा (?:on|ऑन|चालू){G} (?:रख|कर)\w*", 25),
        (r"house arrest|हाउस अरेस्ट|surveillance|nigrani|निगरानी", 20),
    ],
    "urgency_threat": [
        (rf"(?:{ARREST}|giraftari|गिरफ्तारी){G} (?:warrant|warant|varrant|वारंट|वॉरंट)|(?:warrant|warant|वारंट|वॉरंट)", 25),
        (r"giraftar\w*|girftar\w*|गिरफ्तार\w*|गिरफतार\w*", 25),
        (ARREST, 15),   # bare "arrest"; kept low because "digital arrest" also contains it
        (r"jail|jel|जेल|lockup|lock up|हवालात", 20),
        (rf"(?:fir|f i r|एफआईआर|एफ आई आर|case|kes|केस|complaint|मुकदमा|मामला){G} (?:darj|register|file|filed|दर्ज|रजिस्टर)\w*", 20),
        (r"money laundering|मनी लॉन्ड्रिंग|मनी लांड्रिंग|hawala|हवाला|drug trafficking|human trafficking|तस्करी", 20),
        (r"drugs?|ड्रग्स|ड्रग|mdma|एमडीएमए|ganja|गांजा|charas", 20),
        # "number band ho jayega" (a threat) outweighs "number band aa raha tha" (a status report)
        (rf"{CUTOFF_TARGET}{G6} {CUTOFF}{gap(2)} (?:jayega|jaega|jaayega|jayegi|jaegi|jaayegi|denge|karenge|will be|जाएगा|जायेगा|जाएगी|जायेगी|देंगे|करेंगे)", 25),
        (rf"{CUTOFF_TARGET}{G6} {CUTOFF}", 20),
        (r"(?:legal|kanooni|kanuni|कानूनी|क़ानूनी) (?:action|karwai|karyawahi|kaarvai|कार्रवाई|कार्यवाही|एक्शन)", 20),
        (rf"(?:do|2|teen|3|ek|1|24|chaubis|दो|तीन|एक|चौबीस) (?:ghante|ghanton|ghanta|hours?|घंटे|घंटों|घंटा)", 15),
        (r"illegal|gair ?kanooni|gair ?kanuni|गैरकानूनी|गैर कानूनी|गैर क़ानूनी|अवैध", 15),
        (rf"(?:kyc|केवाईसी){G} (?:expire|expiry|expired|update nahi|एक्सपायर)\w*", 15),
        (r"penalty|jurmana|जुर्माना|पेनल्टी|last warning|final notice|आखिरी चेतावनी", 15),
        (r"turant|turat|तुरंत|फौरन|immediately|abhi ke abhi|jaldi kijiye|जल्दी कीजिए", 10),
    ],
    "isolation_secrecy": [
        (rf"(?:kisi|kisiko|किसी|किसीको) ?(?:ko|se|को|से)?{G} (?:{NOT} {SAY}|{SAY}{gap(2)} {NOT})", 25),
        (r"(?:do not|don ?t|never) (?:tell|inform|share this with|discuss this with) (?:anyone|anybody|your family|family|others)", 25),
        (rf"(?:family|parivar|pariwar|ghar|gharwal\w*|परिवार|घर|घरवाल\w*){gap(3)} (?:ko|se|को|से|walon|वालों)\w*{gap(3)} {NOT} {SAY}", 25),
        (rf"{CALL}{gap(2)} {NOT} (?:kaat|kat|kaato|cut|disconnect|rakh|रख|काट|कट)\w*", 25),
        (r"(?:do not|don ?t) (?:cut|disconnect|end|drop) (?:the )?(?:call|line|phone)|stay on the (?:call|line)", 25),
        (r"bina kisi ko bataye|बिना किसी को बताए|बिना किसी को बताये", 25),
        (rf"(?:akele|akela|alone|अकेले|अकेला){gap(3)} (?:room|kamre|kamra|कमरे|कमरा)", 20),
        (r"confidential|secret|gopniya|गोपनीय|गुप्त", 15),
    ],
    "money_transfer": [
        (rf"(?:safe|seif|safe side|सेफ|surakshit|सुरक्षित|secure|sikyor) {ACCOUNT}", 30),
        (rf"(?:rbi|government|sarkari|सरकारी|verification|verifikation|वेरिफिकेशन|escrow|nodal|नोडल|आरबीआई){gap(2)} {ACCOUNT}", 25),
        (r"(?:verification|security|refundable|processing|clearance|registration) (?:fee|charge|deposit|amount|फीस|चार्ज)", 25),
        (rf"{MONEY}{G6} {SEND}", 20),
        (rf"{SEND}{gap(3)} {MONEY}", 20),
        (r"rtgs|neft|imps|आरटीजीएस|एनईएफटी|आईएमपीएस", 20),
        (rf"(?:payment|pement|पेमेंट|bhugtan|भुगतान){gap(2)} (?:kar|kij|kiji|karo|kare|कर|कीज|कीजि)\w*", 20),
        (rf"(?:fine|penalty|jurmana|जुर्माना){gap(3)} (?:bhar|pay|de|भर|दे)\w*", 20),
        (r"gift card|crypto|bitcoin|usdt", 20),
        (r"upi|यूपीआई|google pay|gpay|phonepe|paytm|पेटीएम", 15),
    ],
    "credential_request": [
        (rf"{OTP}{G} {REQ}|{REQ}{G} {OTP}", 25),
        (OTP, 15),
        (r"cvv|c v v|सीवीवी|सी वी वी|card ke peeche|कार्ड के पीछे", 30),
        (rf"(?:atm|card|debit|credit|upi|एटीएम|कार्ड|यूपीआई) (?:pin|पिन)|(?:pin|पिन)(?! ?(?:code|कोड))(?: number| नंबर)?{G} {REQ}", 25),
        (rf"(?:net ?banking|internet banking|नेट बैंकिंग|नेटबैंकिंग){gap(2)} (?:password|pass word|पासवर्ड|user ?id|login|लॉगिन)", 25),
        (rf"(?:card number|card no|कार्ड नंबर|expiry date|एक्सपायरी){G} {REQ}", 20),
        (rf"(?:aadhaar|aadhar|adhar|aadhaar|adhaar|आधार|pan|पैन)(?: card| कार्ड)?{gap(2)} (?:number|no|नंबर|details?|डिटेल)\w*{G} {REQ}", 20),
        (rf"(?:code|kod|कोड){G6} {REQ}", 15),
        (rf"{ACCOUNT} (?:number|no|नंबर|details?|डिटेल)\w*{G} {REQ}", 15),
        (r"password|pasword|पासवर्ड", 15),
        (r"aadhaar|aadhar|adhar|adhaar|आधार|pan card|पैन कार्ड", 10),
    ],
    "remote_access_app": [
        (r"any ?desk|any ?disk|eni ?desk|एनीडेस्क|एनी डेस्क|एनीडेक्स|एनी डिस्क", 30),
        (r"team ?viewer|टीमव्यूअर|टीम व्यूअर|quick ?support|क्विक सपोर्ट|rust ?desk|airdroid|ultra ?viewer|ammyy", 30),
        (r"screen (?:share|sharing|shair|shear)\w*|स्क्रीन (?:शेयर|शेअर)\w*|share (?:your |apni |अपनी )?screen", 25),
        (r"remote (?:access|control|app|desktop)|रिमोट (?:एक्सेस|कंट्रोल)", 25),
        (r"apk|a p k|एपीके|ए पी के", 25),
        (rf"(?:app|application|ऐप|एप|एप्लीकेशन){gap(3)} (?:download|install|instal|डाउनलोड|इंस्टॉल|इंस्टाल)\w*|(?:download|install|डाउनलोड|इंस्टॉल){gap(3)} (?:app|ऐप|एप)", 15),
    ],
}

# A sentence that matches one of these is the protective advice real banks give ("never share
# your OTP with anyone"), so its credential and secrecy hits are ignored.
SAFE_ADVICE = [
    rf"(?:kabhi|kabhee|never|कभी){G6} (?:{OTP}|pin|cvv|password|पिन|पासवर्ड|सीवीवी)",
    rf"(?:{OTP}|pin|cvv|password|पिन|पासवर्ड){G6} (?:nahi|nahin|नहीं|नही|never) (?:maang|mang|pooch|puch|ask|मांग|माँग|पूछ)\w*",
    r"(?:never|do not|don ?t) share|share (?:na|mat|nahi) (?:kar|kare|karein|kijiye|करें|कीजिए)\w*|शेयर (?:न|ना|मत) (?:करें|कीजिए|करना)",
]
SAFE_ADVICE_SUPPRESSES = ("credential_request", "isolation_secrecy")


# ---- normalisation and compiled patterns ---------------------------------------------------------
_PUNCT = re.compile(r"[^0-9a-zऀ-ॿ]+")
_FOLD = str.maketrans({"़": None, "ँ": "ं", "‌": None, "‍": None,
                       "।": " ", "॥": " "})


def _fold(text: str) -> str:
    # Decompose first so the precomposed nukta letters (U+0929, U+0958-U+095F) lose their
    # nukta too: "फ़ोन" becomes "फोन". Chandrabindu folds to anusvara: "माँग" becomes "मांग".
    # No lowercasing here: patterns go through this too, and lower() would turn \S into \s.
    text = unicodedata.normalize("NFD", text).translate(_FOLD)
    return unicodedata.normalize("NFC", text)


def normalize(text: str) -> str:
    """Lowercase, fold nukta / chandrabindu, drop punctuation, collapse spaces."""
    return " ".join(_PUNCT.sub(" ", _fold(text.lower())).split())


def _compile(fragment: str) -> re.Pattern:
    # Patterns are folded like the text, so a pattern written with a nukta still matches.
    body = _fold(fragment).replace(r"\w", _WORD)
    return re.compile(rf"(?<!{_WORD})(?:{body})(?!{_WORD})")


@dataclass(frozen=True)
class Phrase:
    tactic: str
    weight: int
    pattern: re.Pattern


COMPILED: list[Phrase] = [
    Phrase(tactic, weight, _compile(fragment))
    for tactic, items in PHRASES.items()
    for fragment, weight in items
]
_SAFE = [_compile(f) for f in SAFE_ADVICE]

assert set(PHRASES) == set(TACTICS), "keyword tactics must match contract.TACTICS"
assert max(p.weight for p in COMPILED) < 70, "one tactic alone must stay below danger"


# ---- matching and scoring --------------------------------------------------------------------------
_CLAUSE_SPLIT = re.compile(r"(?<=[,.;:!?।॥])\s+|\s+[-–—]\s+")


def _quote(sentence: str, pattern: re.Pattern) -> str:
    """The clause of the original sentence that contains the match, trimmed to QUOTE_MAX."""
    text = sentence.strip()
    for clause in _CLAUSE_SPLIT.split(text):
        if pattern.search(normalize(clause)):
            text = clause.strip()
            break
    if len(text) > QUOTE_MAX:
        cut = text[:QUOTE_MAX].rsplit(" ", 1)[0]
        text = cut + "…"
    return text


def match_sentence(sentence: str) -> dict[str, tuple[int, str]]:
    """Tactic -> (strongest weight in this sentence, evidence quote)."""
    norm = normalize(sentence)
    if not norm:
        return {}
    safe = any(p.search(norm) for p in _SAFE)
    found: dict[str, tuple[int, str]] = {}
    for ph in COMPILED:
        if safe and ph.tactic in SAFE_ADVICE_SUPPRESSES:
            continue
        if ph.tactic in found and found[ph.tactic][0] >= ph.weight:
            continue
        if ph.pattern.search(norm):
            found[ph.tactic] = (ph.weight, _quote(sentence, ph.pattern))
    return found


def score_weights(weights: dict[str, int]) -> int:
    """Score a call from its tactic weights (strongest phrase per tactic)."""
    def has(t: str) -> bool:
        return weights.get(t, 0) >= STRONG

    strong = [t for t in weights if has(t)]
    score = sum(weights.values()) + COMBO_BONUS * max(0, len(strong) - 1)
    if has("authority_impersonation") and has("urgency_threat") and (
        has("money_transfer") or has("credential_request")
    ):
        score = max(score, 80)
    if has("remote_access_app") and (has("credential_request") or has("money_transfer")):
        score = max(score, 75)
    return max(0, min(100, score))


@dataclass
class Hit:
    tactic: str
    weight: int
    quote: str
    index: int          # 1-based sentence number


@dataclass
class KeywordTracker:
    """Keyword state for one call. add() is cheap: a few hundred regex searches on one sentence."""

    weights: dict[str, int] = field(default_factory=dict)
    best: dict[str, Hit] = field(default_factory=dict)   # strongest hit per tactic
    count: int = 0

    def add(self, sentence: str) -> list[Hit]:
        self.count += 1
        hits = []
        for tactic, (weight, quote) in match_sentence(sentence).items():
            hit = Hit(tactic, weight, quote, self.count)
            hits.append(hit)
            if weight > self.weights.get(tactic, 0):
                self.weights[tactic] = weight
                self.best[tactic] = hit
        return hits

    @property
    def score(self) -> int:
        return score_weights(self.weights)

    @property
    def tactics(self) -> list[str]:
        """Strong tactics, in contract order."""
        return [t for t in TACTICS if self.weights.get(t, 0) >= STRONG]

    def evidence(self, limit: int = 5) -> list[str]:
        """Quotes for the strong tactics, strongest first, de-duplicated."""
        hits = sorted((h for h in self.best.values() if h.weight >= STRONG),
                      key=lambda h: (-h.weight, h.index))
        out: list[str] = []
        for h in hits:
            if h.quote not in out:
                out.append(h.quote)
        return out[:limit]

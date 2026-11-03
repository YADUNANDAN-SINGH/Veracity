# Scam-script layer 1 (Project Document §1.6): 11 categories of phrases,
# in English (Indian and US scams), Hinglish and Hindi (Whisper writes Hindi
# in Devanagari). Flags appear instantly; the LLM layer adds what the phrases miss.
#
# Keep adding real scam phrases you find in news reports. The evidence is the
# exact matched text, so the dashboard can highlight it in the transcript.
#
# Whisper misspells Hindi on phone audio ("दिजिटल आरेष्ट" for "डिजिटल अरेस्ट"),
# so text and patterns are both "folded" before matching: sounds it confuses
# become one letter. The evidence is still cut from the original text.

import re
import unicodedata

# Rest of a Hindi word (\w stops at vowel signs, which are combining marks); not । or ॥
DV = "[\u0900-\u0963\u0966-\u097F]*"

_RULES: dict[str, tuple[int, list[str]]] = {
    "OTP_PIN_REQUEST": (3, [
        r"\bOTP\b", r"one[- ]time password", r"\bCVV\b", r"\bUPI pin\b", r"\bATM pin\b", r"\bPIN\b",
        r"verification code", r"security code", r"code (?:we|I) (?:just )?(?:sent|texted)",
        r"\bcode (?:batao|bataiye|bolo|share karo)", r"ओ?टीपी", r"पिन",
    ]),
    "AUTHORITY_IMPERSONATION": (3, [
        r"\bCBI\b", r"cyber ?(?:cell|crime)", r"\bpolice\b", r"\bcustoms\b", r"\bTRAI\b", r"income ?tax",
        r"enforcement directorate", r"\bnarcotics\b", r"\bNCB\b", r"\bRBI\b", r"\binspector\b",
        # US: government, police and the fake lawyer who takes over a "grandchild in jail" call
        r"\bIRS\b", r"social security (?:administration|office)", r"\bFBI\b", r"\bU\.?S\.? marshals?\b",
        r"\bsheriff'?s?\b", r"\b(?:officer|detective|sergeant|deputy)\b", r"fraud (?:department|team|prevention)",
        r"\b(?:lawyer|attorney|public defender|bail bonds?(?:man)?)\b",
        r"पुलिस", r"सीबीआई", r"साइबर (?:सेल|क्राइम)", r"इंस्पेक्टर",
    ]),
    "THREAT_ARREST": (3, [
        r"digital(?:ly)? arrest", r"\bwarrant\b", r"money laundering", r"\bgiraftar\w*", r"\bjail\b",
        r"\barrest\w*", r"\bcustody\b", r"\bdeport\w*", r"legal action",
        r"डिजिटल अरेस्ट", rf"गिरफ्तार{DV}", r"जेल", r"अरेस्ट",
    ]),
    "PAYMENT_PRESSURE": (3, [
        r"safe account", r"secure account", r"transfer (?:the |your |all )?(?:money|amount|funds)",
        # US: payment apps, wires and cash pick-ups
        r"\b(?:send|pay|wire)\b.{0,30}?\b(?:paypal|venmo|zelle|cash ?app|western union|moneygram)\b",
        r"\b(?:send|wire|transfer)\b(?:\s+\w+){0,3}?\s+(?:money|cash|funds|dollars|bucks)\b",
        r"\b(?:need|owe|send|wire|transfer|pay)\b.{0,20}?\$\s?\d[\d,]{2,}", r"\bwire (?:transfer|it|the)\b",
        r"pick(?:ed)? up (?:the )?(?:cash|money)", r"(?:cash|money) in (?:an |a )?envelope",
        r"\bpaise? (?:bhejo|bhejiye|transfer)\w*", r"gift ?cards?", r"\bcrypto\w*", r"\bbitcoin\b",
        r"security deposit", rf"पैसे भेज{DV}", r"ट्रांसफर", r"सेफ अकाउंट",
        # "all your money" only with a transfer word close by
        r"(?:सारे|पूरे) पैसे.{0,30}?(?:ट्रांसफर|भेज|डाल|जमा|अकाउंट)",
    ]),
    "REMOTE_ACCESS": (3, [
        r"any ?desk", r"team ?viewer", r"quick ?support", r"screen ?shar\w*", r"\bAPK\b",
        r"remote(?:ly)? (?:access|control)", r"screen ?connect", r"connect ?wise",
        r"install (?:this|the|an?) app", r"app (?:install|download) kar\w*", r"एनीडेस्क", r"स्क्रीन शेयर",
    ]),
    "SECRECY": (2, [
        r"(?:don'?t|do not) tell (?:anyone|anybody|mom|dad|mum|my (?:mom|dad|mum|parents|family)|"
        r"your (?:bank|family|kids|son|daughter|children))",
        r"keep (?:this|it) (?:a )?secret", r"keep (?:this|it) between us", r"between you and me",
        r"(?:don'?t|do not) (?:hang up|disconnect|end (?:the|this) call)", r"stay on the (?:line|phone|call)",
        r"kisi ko (?:mat|na|bhi mat) bata\w*", r"call (?:mat|na) kaat\w*",
        rf"किसी को (?:मत|ना|भी मत) बता{DV}", rf"(?:कॉल|फोन) (?:मत|ना) काट{DV}",
    ]),
    "KYC_ACCOUNT_BLOCK": (2, [
        r"\bKYC\b", r"account (?:will be |is |has been )?(?:blocked|suspended|frozen|closed|band)",
        r"(?:account|card) (?:has been |was |is |will be )?(?:compromised|hacked|locked)",
        r"suspicious (?:activity|charges?|transactions?)",
        r"SIM (?:card )?(?:will be )?(?:blocked|band|deactivated)", r"(?:खाता|अकाउंट) (?:बंद|ब्लॉक)", r"सिम बंद",
    ]),
    "PARCEL_COURIER": (2, [
        r"parcels?(?: in your name)?", r"\bcourier\b", r"\bFedEx\b", r"\bDHL\b", r"पार्सल", r"कूरियर",
    ]),
    "FAMILY_EMERGENCY": (2, [
        r"\baccident\b", r"\bhospital\b", r"\bbail\b", r"car (?:crash|wreck)",
        # why a cloned or impostor voice "sounds different"
        r"(?:broke|broken) (?:my )?nose", r"\bsound(?:s|ing)? (?:a (?:bit|little) )?different\b",
        r"new (?:number|phone|cell)", r"naya number", r"\bmusibat\b",
        r"एक्सीडेंट", r"अस्पताल", r"नया नंबर", r"मुसीबत",
    ]),
    "PRIZE_LOTTERY": (2, [
        r"\blottery\b", r"you (?:have|'ve) won", r"\bprize\b", r"\bsweepstakes\b", r"\bKBC\b", r"लॉटरी", r"इनाम",
    ]),
    "URGENCY": (1, [
        r"\bimmediately\b", r"right now", r"right away", r"as soon as possible", r"\bASAP\b", r"\burgent(?:ly)?\b",
        r"\bhurry\b", r"before (?:the )?(?:judge|court|hearing)", r"\bturant\b", r"abhi ke abhi",
        r"(?:within|in the next) (?:\d+|one|two|few|an?) (?:minutes?|hours?)", r"तुरंत", r"अभी के अभी",
    ]),
}

# Letters Whisper swaps on narrow-band audio → one letter each
_FOLD = {
    # retroflex and dental t/d, voiced or not (मत → मद, अरेस्ट → आरेष्ट)
    **dict.fromkeys("टठडढतथदध", "त"),
    **dict.fromkeys("शषस", "स"),
    **dict.fromkeys("णङञ", "न"),
    "ं": "न",  # anusvara: अकाउंट and अकाउन्त
    # long and short vowels
    "आ": "अ", "ई": "इ", "ऊ": "उ", "ऐ": "ए", "औ": "ओ",
    "ी": "ि", "ू": "ु", "ै": "े", "ौ": "ो",
}
_DROP = set("\u093c\u094d\u0901\u0903")  # nukta, virama (्), chandrabindu, visarga


def fold(text: str) -> tuple[str, list[int]]:
    """Folded text, and for each of its characters the index it came from in `text`."""
    out, origin = [], []
    for i, ch in enumerate(text):
        if ch in _DROP:
            continue
        out.append(_FOLD.get(ch, ch))
        origin.append(i)
    return "".join(out), origin


def _evidence(text: str, origin: list[int], start: int, end: int) -> str:
    """The original words behind a match in the folded text, ending on a whole syllable."""
    a, b = origin[start], origin[end - 1] + 1
    while b < len(text) and unicodedata.category(text[b]) in ("Mn", "Mc"):  # trailing vowel signs, ्
        b += 1
    return text[a:b]


_COMPILED = {
    category: (severity, [re.compile(fold(p)[0], re.IGNORECASE) for p in patterns])
    for category, (severity, patterns) in _RULES.items()
}

CATEGORIES = list(_RULES)
SEVERITY = {category: severity for category, (severity, _) in _RULES.items()}


def scan(text: str) -> list[dict]:
    """One hit per category found in `text`; patterns are tried in order, most specific first."""
    folded, origin = fold(text)
    hits = []
    for category, (severity, patterns) in _COMPILED.items():
        for pattern in patterns:
            match = pattern.search(folded)
            if match and match.end() > match.start():
                evidence = _evidence(text, origin, match.start(), match.end())
                hits.append({"category": category, "severity": severity, "evidence": evidence})
                break
    return hits


def is_duplicate(evidence: str, flags: list[dict]) -> bool:
    """True if these words, or words containing them, are already evidence for a flag."""
    key = evidence.lower()
    return any(key in f["evidence"].lower() or f["evidence"].lower() in key for f in flags)


def script_score(categories: set[str]) -> int:
    """8 × severities of distinct categories, plus the known scam patterns; 0–100."""
    score = 8 * sum(SEVERITY[c] for c in categories)
    if {"AUTHORITY_IMPERSONATION", "PAYMENT_PRESSURE"} <= categories:
        score += 20  # digital arrest
    if {"FAMILY_EMERGENCY", "PAYMENT_PRESSURE"} <= categories:
        score += 20  # voice-clone "family in trouble"
    if "OTP_PIN_REQUEST" in categories:
        score += 10
    return min(100, score)

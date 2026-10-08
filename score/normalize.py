"""Text normalization applied identically to gold and hypothesis before any metric.

English: Whisper EnglishTextNormalizer (fillers removed, number words -> digits,
British -> American spelling), preceded by unit and token rules below.
Other languages: Whisper BasicTextNormalizer (lowercase, punctuation stripped,
diacritics kept) after converting digits to words with num2words, so "25" and
"fünfundzwanzig" score the same.
"""
import re

from num2words import num2words
from whisper_normalizer.basic import BasicTextNormalizer
from whisper_normalizer.english import EnglishTextNormalizer

_EN = EnglishTextNormalizer()
_BASIC = BasicTextNormalizer()

# applied before the Whisper normalizer, which then turns number words into digits
_UNIT_RULES = [
    (r"(\d)\s*mcg\b", r"\1 micrograms"),
    (r"(\d)\s*(µg|μg|ug)\b", r"\1 micrograms"),
    (r"(\d)\s*mg\b", r"\1 milligrams"),
    (r"(\d)\s*ml\b", r"\1 milliliters"),
    (r"(\d)\s*kg\b", r"\1 kilograms"),
    (r"(\d)\s*g\b", r"\1 grams"),
    (r"\bmillilitres?\b", "milliliters"),
    (r"\bmilligram\b", "milligrams"),
    (r"\bmicrogram\b", "micrograms"),
]
_TOKEN_RULES = [
    (r"\bo\.?k\.?\b", "okay"),
    (r"\bok\b", "okay"),
    (r"\ball right\b", "alright"),
    # interjections and fillers the Whisper filler list misses
    (r"\b(?:ooh+|ah+|uhm+|erm+|er|mhmm+|mm+ ?hmm+|mm+-hmm+|uh-huh|hm+)\b", " "),
]
_NUMBERISH = re.compile(r"^(?:\d+|zero|one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|forty|"
                        r"fifty|sixty|seventy|eighty|ninety|hundred|double|triple)$")


def _drop_oh(text):
    """"oh" is a filler unless a neighbouring word is a number ("five oh two" = 502).
    Left in place, Whisper would turn every interjection "oh" into the digit 0."""
    toks = text.split()
    bare = [re.sub(r"[^\w]", "", t).lower() for t in toks]
    keep = []
    for i, t in enumerate(toks):
        if re.fullmatch(r"oh+", bare[i]):
            near = [bare[j] for j in (i - 1, i + 1) if 0 <= j < len(toks)]
            if not any(_NUMBERISH.match(n) for n in near):
                continue
        keep.append(t)
    return " ".join(keep)
# Praat/PriMock markup, removed from gold (clips carrying UNIN/INAUDIBLE are dropped upstream)
_MARKUP = re.compile(r"</?UNSURE>|<UNIN/>|<INAUDIBLE_SPEECH/>", re.I)

_N2W_LANG = {"de": "de", "fr": "fr", "tr": "tr", "en": "en"}

# Written abbreviations that readers say in full. Canonical form is the abbreviation, so singular,
# plural and case-inflected spoken forms all collapse to one token.
_KM = r"\b(?:kilometer(?:n|s)?|kilomètres?|kilometre(?:ler|lik)?)\b"
_ABBREV = {
    "de": [(_KM, "km"), (r"\bgigahertz\b", "ghz"), (r"\bnach christus\b", "n chr"), (r"\bvor christus\b", "v chr"),
           (r"\bn\. ?chr\.?", "n chr"), (r"\bv\. ?chr\.?", "v chr"), (r"\bprozent\b", "%")],
    "fr": [(_KM, "km"), (r"\bkm ?/ ?h\b", "km heure"), (r"\bkm heure\b", "km heure"), (r"\bgigahertz\b", "ghz"),
           (r"\bavant j[ée]sus[- ]christ\b", "av j c"), (r"\bapr[èe]s j[ée]sus[- ]christ\b", "ap j c"),
           (r"\bav\. ?j\.?-?c\.?", "av j c"), (r"\bj[ée]sus[- ]christ\b", "j c"), (r"\bpour ?cent\b", "%")],
    "tr": [(_KM, "km"), (r"\bgigahertz\b", "ghz"), (r"\byüzde (\w+)", r"% \1")],
}


def strip_markup(text):
    return re.sub(r"\s+", " ", _MARKUP.sub(" ", text)).strip()


def normalize(text, lang="en"):
    text = strip_markup(text or "")
    if lang == "en":
        for pat, rep in _UNIT_RULES + _TOKEN_RULES:
            text = re.sub(pat, rep, text, flags=re.I)
        text = _drop_oh(text)
        out = _EN(text)
        # drop tokens with no letter or digit (stray "." left by the number normalizer)
        return " ".join(t for t in out.split() if re.search(r"\w", t))
    lang2 = _N2W_LANG.get(lang, lang)
    text = text.replace("\u200b", "")
    # thousands separators: "1.000" (de/tr), "1 000" (fr, incl. narrow no-break space) -> 1000
    text = re.sub(r"\b\d{1,3}(?:[.\u00a0\u202f ]\d{3})+\b(?![.,]\d)", lambda m: re.sub(r"\D", "", m.group(0)), text)
    if lang2 == "tr":
        # Turkish suffix apostrophe joins a suffix to a name or number: "Meydanı'ndaki", "20'nci"
        text = re.sub(r"(\w)['’](\w)", r"\1\2", text)
    for pat, rep in _ABBREV.get(lang2, []):
        text = re.sub(pat, rep, text, flags=re.I)

    def _num(m):
        raw = m.group(0).replace(",", ".")
        try:
            words = num2words(float(raw) if "." in raw else int(raw), lang=lang2)
        except (NotImplementedError, ValueError, OverflowError):
            return m.group(0)
        # keep a glued Turkish suffix glued ("20nci" -> "yirminci")
        return " " + words + ("" if lang2 == "tr" and m.end() < len(m.string) and m.string[m.end()].isalpha() else " ")

    text = re.sub(r"\d+(?:,\d+)?", _num, text)
    if lang2 == "de":
        text = re.sub(r"\bein(hundert|tausend)", r"\1", text, flags=re.I)  # "einhundert" is said "hundert"
    out = _BASIC(text)
    return re.sub(r"\s+", " ", out).strip()

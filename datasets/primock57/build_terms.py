"""Build the fixed medical term list from PriMock57 gold text, before any engine runs.

Deterministic, no LLM. Lexicon = English labels and aliases of Wikidata items (CC0) that carry
  drug:      an ATC code (P267)
  condition: an ICD-10 (P494) or ICD-11 (P7807) code (diseases, symptoms, findings)
Stereo prefixes such as "(±)-" are stripped ("(±)-salbutamol" -> "salbutamol").
Gold n-grams (1-4 tokens, normalized) that match a normalized lexicon label become terms.
Single-token terms that are common English (wordfreq zipf >= 4.5, e.g. "pain", "back") are
dropped so the list measures clinical vocabulary rather than everyday words.
dosage: regex over normalized gold, a number followed by a dose unit ("400 milligrams", "4 puffs").

Output: datasets/primock57/terms.json (committed). The Wikidata snapshot is cached in
data/primock57/lexicon/ so re-runs are offline and identical.
"""
import csv
import hashlib
import json
import pathlib
import re
import sys
import urllib.parse
import urllib.request

from wordfreq import zipf_frequency

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from score.normalize import normalize  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
LEX = ROOT / "data" / "primock57" / "lexicon"
PROPS = {"drug": ["P267"], "condition": ["P494", "P7807"]}
DOSE_RE = re.compile(r"\b\d+(?:\.\d+)? (?:milligrams|micrograms|milliliters|grams|tablets?|puffs?|capsules?|pills?|units|drops|sachets?)\b")
COMMON_ZIPF = 4.5
# frequency of dosing ("twice a day", "3 times a day"): counted with dosages
DOSING_RE = re.compile(r"\b(?:once|twice|\d+ times) (?:a|per) (?:day|week)\b")

# Lexicon matches that are not clinical vocabulary. Fixed before any engine ran; reasons kept
# so a reviewer can contest any line. ICD-11 extension codes pull in anatomy and qualifiers.
EXCLUDE = {
    "anatomy": "abdomen|belly|belly button|bum|calf|colon|ear|ears|ear drum|elbow|finger|gut|jaw|kidney|knee|lip|"
               "lips|lower abdomen|middle ear|muscles|navel|nerve|palm|pecs|stomach|thumb|thyroid|toes|tummy|wrist|"
               "tissues|field of vision|left hand side|left side|upper respiratory tract",
    "qualifier_or_generic": "acute|mild|moderate|minimal|slight|severely|severity|small amount|odd|sensation|"
                            "exposure|recurrence|illness|injuries|nervous|a virus|virus|bacteria|ache|bite|sore|"
                            "shortness|the flu|fever or",
    "not_medical_in_context": "settle|pets|gps|high school|missus|ups|or or|or or or|bee|wasp|wee|ors|coke|"
                              "cocaine|oxygen|tuberculosis|vitamins",
}
EXCLUDED = {t: why for why, terms in EXCLUDE.items() for t in terms.split("|")}


def fetch(prop):
    path = LEX / f"{prop}.csv"
    if not path.exists():
        LEX.mkdir(parents=True, exist_ok=True)
        q = ("SELECT DISTINCT ?l WHERE { ?i wdt:%s ?c . { ?i rdfs:label ?l } UNION { ?i skos:altLabel ?l } "
             "FILTER(LANG(?l)='en') }" % prop)
        req = urllib.request.Request(
            "https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": q}),
            headers={"Accept": "text/csv", "User-Agent": "stt-scribe-bench/0.1 (research)"})
        with urllib.request.urlopen(req, timeout=300) as r:
            path.write_bytes(r.read())
    with open(path, newline="") as f:
        return [row["l"] for row in csv.DictReader(f)]


def lexicon():
    lex = {}
    for cat, props in PROPS.items():
        for prop in props:
            for label in fetch(prop):
                label = re.sub(r"^\([^)]*\)-", "", label.strip())
                n = normalize(label)
                if len(n) < 3 or not re.search(r"[a-z]", n) or len(n.split()) > 4:
                    continue
                lex.setdefault(n, cat if cat == "drug" else lex.get(n, cat))
    return lex


def main():
    clips = [json.loads(l) for l in open(HERE / "clips.jsonl")]
    lex = lexicon()
    counts = {}
    for c in clips:
        toks = normalize(c["gold"]).split()
        for n in range(1, 5):
            for i in range(len(toks) - n + 1):
                g = " ".join(toks[i:i + n])
                if g in lex:
                    counts[g] = counts.get(g, 0) + 1
        norm = normalize(c["gold"])
        for m in DOSE_RE.findall(norm) + DOSING_RE.findall(norm):
            counts[m] = counts.get(m, 0) + 1
    terms = []
    for t, n in sorted(counts.items()):
        if t in EXCLUDED:
            continue
        cat = "dosage" if (DOSE_RE.fullmatch(t) or DOSING_RE.fullmatch(t)) else lex[t]
        if cat != "dosage" and " " not in t and zipf_frequency(t, "en") >= COMMON_ZIPF:
            continue
        terms.append({"term": t, "category": cat, "gold_occurrences": n})
    blob = json.dumps(terms, sort_keys=True).encode()
    out = {"source": "Wikidata CC0 labels (ATC P267, ICD-10 P494, ICD-11 P7807) matched to PriMock57 gold",
           "common_word_zipf_cutoff": COMMON_ZIPF, "excluded": EXCLUDED, "sha256": hashlib.sha256(blob).hexdigest(),
           "n_terms": len(terms),
           "by_category": {k: sum(t["category"] == k for t in terms) for k in ("drug", "condition", "dosage")},
           "terms": terms}
    (HERE / "terms.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print({k: out[k] for k in ("n_terms", "by_category", "sha256")})


if __name__ == "__main__":
    main()

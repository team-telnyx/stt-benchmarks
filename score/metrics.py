"""Metrics over one run directory. Every number here is recomputable from runs/<id>/raw.

WER: corpus-level (sum of S+D+I over sum of gold words) on normalized text, speech clips only.
     A failed request (error, timeout, non-200) counts as an empty hypothesis: every gold word
     is a deletion. Failures are also reported as a rate. 95% CI from a cluster bootstrap over
     groups (consultations / speakers), 1000 resamples, fixed seed.
Term recall: gold occurrences of fixed-list terms (greedy longest match on normalized gold)
     found in the normalized hypothesis, counted per occurrence, by category.
Number recall: gold tokens containing a digit after normalization, multiset match in hypothesis.
Hallucination: silence probes whose normalized hypothesis is non-empty.
Wrong language: lingua language ID over 8 candidate languages on the raw hypothesis. Counted only
     when the hypothesis has >= 4 words and the top language has confidence >= 0.5; the rate is
     over clips that meet that bar. Shorter turns are judged by exact match in the phone-in track.
Latency (realtime lane): median and p90 over successful speech clips, re-anchored to speech found by
     an energy VAD (score/vad.py): TTFT from the chunk holding speech onset to first text, final
     from the chunk holding speech end to the last final. Raw values (from clip edges) stay in raw/.
"""
import collections
import json
import random
import re

import jiwer

from score.normalize import normalize
from score.vad import clip_seconds, speech_bounds

LID_MIN_WORDS = 4
LID_MIN_CONF = 0.5
_LID = None


def lid(text):
    global _LID
    if _LID is None:
        from lingua import Language, LanguageDetectorBuilder
        _LID = LanguageDetectorBuilder.from_languages(
            Language.ENGLISH, Language.GERMAN, Language.FRENCH, Language.TURKISH, Language.SPANISH,
            Language.ITALIAN, Language.DUTCH, Language.PORTUGUESE).build()
    top = _LID.compute_language_confidence_values(text)[0]
    return top.language.iso_code_639_1.name.lower(), top.value


BOOT_N = 1000
BOOT_SEED = 7


def term_index(terms):
    by_len = collections.defaultdict(dict)
    for t in terms:
        toks = tuple(t["term"].split())
        by_len[len(toks)][toks] = t["category"]
    return dict(sorted(by_len.items(), reverse=True))


def find_terms(tokens, index):
    """Greedy longest match, non-overlapping. Returns list of (term, category)."""
    out, i = [], 0
    while i < len(tokens):
        for n, table in index.items():
            cand = tuple(tokens[i:i + n])
            if cand in table:
                out.append((" ".join(cand), table[cand]))
                i += n
                break
        else:
            i += 1
    return out


def contains_count(hyp_tokens, term):
    t = term.split()
    n = len(t)
    return sum(1 for i in range(len(hyp_tokens) - n + 1) if hyp_tokens[i:i + n] == t)


def score_clip(clip, res, index):
    lang = clip["lang"]
    ok = bool(res and res.get("ok"))
    hyp = normalize(res.get("text") or "", lang) if ok else ""
    gold = normalize(clip["gold"], lang)
    row = {"id": clip["id"], "group": clip["group"], "kind": clip["kind"], "ok": ok,
           "error": None if ok else (res or {}).get("error", "missing"), "gold_norm": gold, "hyp_norm": hyp,
           "dur": clip["dur"]}
    if res:
        for k in ("ttfp", "final_s", "first_kind", "wall_s", "detected_language"):
            if k in res:
                row[k] = res[k]
        if ok and clip["kind"] == "speech" and clip.get("pcm8k") and ("final_s" in res or "ttfp" in res):
            # re-anchor realtime latency to speech: chunk i (100 ms) is sent at t_first + i*0.1, so
            # the chunk holding speech end is sent (n_chunks-1-k_end)*0.1 s before the last chunk
            onset, end = speech_bounds(clip["pcm8k"])
            n_chunks = -(-round(clip_seconds(clip["pcm8k"]) * 1000) // 100)
            k_on, k_end = int(onset / 0.1), min(int(end / 0.1), n_chunks - 1)
            if res.get("final_s") is not None:
                row["final_speech_s"] = round(res["final_s"] + (n_chunks - 1 - k_end) * 0.1, 3)
            if res.get("ttfp") is not None:
                row["ttfp_speech_s"] = round(res["ttfp"] - k_on * 0.1, 3)
    if clip["kind"] == "silence":
        row["hallucinated"] = bool(hyp)
        return row
    g, h = gold.split(), hyp.split()
    raw_hyp = (res.get("text") or "") if ok else ""
    if len(raw_hyp.split()) >= LID_MIN_WORDS:
        code, conf = lid(raw_hyp)
        if conf >= LID_MIN_CONF:
            row["lid"] = code
            row["wrong_language"] = code != lang
    if h:
        o = jiwer.process_words(gold, hyp)
        row.update(S=o.substitutions, D=o.deletions, I=o.insertions, N=len(g))
    else:
        row.update(S=0, D=len(g), I=0, N=len(g))
    terms = find_terms(g, index) if index else []
    hit = collections.Counter()
    tot = collections.Counter()
    seen = collections.Counter()
    for term, cat in terms:
        tot[cat] += 1
        seen[term] += 1
        if contains_count(h, term) >= seen[term]:
            hit[cat] += 1
    row["terms_total"] = dict(tot)
    row["terms_hit"] = dict(hit)
    row["term_misses"] = [t for t, c in collections.Counter(t for t, _ in terms).items() if contains_count(h, t) < c]
    nums = [t for t in g if re.search(r"\d", t)]
    hc = collections.Counter(t for t in h if re.search(r"\d", t))
    gc = collections.Counter(nums)
    row["num_total"] = len(nums)
    row["num_hit"] = sum(min(c, hc[t]) for t, c in gc.items())
    return row


def _wer(rows):
    n = sum(r["N"] for r in rows)
    return (sum(r["S"] + r["D"] + r["I"] for r in rows) / n) if n else None


def bootstrap_ci(rows):
    groups = collections.defaultdict(list)
    for r in rows:
        groups[r["group"]].append(r)
    keys = sorted(groups)
    if len(keys) < 2:
        return None, None
    rng = random.Random(BOOT_SEED)
    vals = []
    for _ in range(BOOT_N):
        sample = [r for k in (rng.choice(keys) for _ in keys) for r in groups[k]]
        w = _wer(sample)
        if w is not None:
            vals.append(w)
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]


def pct(vals, q):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    return vals[min(len(vals) - 1, int(round(q * (len(vals) - 1))))]


def summarize(rows):
    speech = [r for r in rows if r["kind"] == "speech"]
    sil = [r for r in rows if r["kind"] == "silence"]
    ok_speech = [r for r in speech if r["ok"]]
    lo, hi = bootstrap_ci(speech)
    tot, hit = collections.Counter(), collections.Counter()
    for r in speech:
        tot.update(r.get("terms_total", {}))
        hit.update(r.get("terms_hit", {}))
    s = {
        "n_speech": len(speech),
        "audio_min": round(sum(r["dur"] for r in speech) / 60, 2),
        "failures": sum(not r["ok"] for r in speech) + sum(not r["ok"] for r in sil),
        "failure_rate": round(sum(not r["ok"] for r in speech) / len(speech), 4) if speech else None,
        "wer": _wer(speech),
        "wer_ci95": [lo, hi],
        "wer_ok_only": _wer(ok_speech),
        "sub_rate": sum(r["S"] for r in speech) / max(1, sum(r["N"] for r in speech)),
        "del_rate": sum(r["D"] for r in speech) / max(1, sum(r["N"] for r in speech)),
        "ins_rate": sum(r["I"] for r in speech) / max(1, sum(r["N"] for r in speech)),
        "term_recall": (sum(hit.values()) / sum(tot.values())) if sum(tot.values()) else None,
        "term_recall_by_cat": {k: {"hit": hit[k], "total": tot[k], "recall": hit[k] / tot[k]} for k in sorted(tot)},
        "num_recall": (sum(r.get("num_hit", 0) for r in speech) / sum(r.get("num_total", 0) for r in speech))
        if sum(r.get("num_total", 0) for r in speech) else None,
        "num_total": sum(r.get("num_total", 0) for r in speech),
        "lid_judged": sum("wrong_language" in r for r in speech),
        "wrong_language": sum(r.get("wrong_language", False) for r in speech),
        "silence_probes": len(sil),
        "hallucinations": sum(r.get("hallucinated", False) for r in sil),
    }
    if any("final_s" in r for r in speech):
        okr = [r for r in ok_speech]
        s.update({
            # latency anchored to detected speech onset / end (score/vad.py), not to clip edges
            "ttfp_p50": pct([r.get("ttfp_speech_s") for r in okr], 0.5), "ttfp_p90": pct([r.get("ttfp_speech_s") for r in okr], 0.9),
            "final_p50": pct([r.get("final_speech_s") for r in okr], 0.5), "final_p90": pct([r.get("final_speech_s") for r in okr], 0.9),
            "final_from_audio_end_p50": pct([r.get("final_s") for r in okr], 0.5),
            "first_kind": dict(collections.Counter(r.get("first_kind") for r in okr)),
        })
    if any("wall_s" in r for r in speech):
        s["wall_p50"] = pct([r.get("wall_s") for r in ok_speech], 0.5)
    return s


def load_raw(run_dir, engine_dir, clip_id):
    p = run_dir / "raw" / engine_dir / f"{clip_id}.json"
    return json.loads(p.read_text()) if p.exists() else None

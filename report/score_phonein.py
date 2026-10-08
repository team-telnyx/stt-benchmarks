"""Score the phone-in run (real PSTN, 5 speakers, 3 packs). Same extra canonicalization for gold and every engine:
number words 0-9 -> digits, mg/mcg/ml units, spoken email 'dot'/'at', leading spoken-ID residue stripped (cut artifact).
Metrics: WER per pack; line exact match (whitespace-insensitive) for N and S; wrong-language count on S; term recall on M."""
import json, re, sys, pathlib, collections
import jiwer
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from score.normalize import normalize
from score.metrics import lid
ROOT = pathlib.Path(__file__).resolve().parents[1]
RUN = ROOT / "runs" / (sys.argv[1] if len(sys.argv) > 1 else "2026-10-01-phonein")
D = "zero one two three four five six seven eight nine".split()
UNIT = {"milligrams": "mg", "milligram": "mg", "micrograms": "mcg", "microgram": "mcg", "milliliters": "ml", "milliliter": "ml"}
ID_RESIDUE = set(D) | {"n", "m", "s", "and", "an", "em", "es", "ess", "oh", "en", "in"} | {str(i) for i in range(31)} | \
  set("ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty".split())
TERMS = ["lisinopril", "metformin", "atorvastatin", "eliquis", "levothyroxine", "amoxicillin", "penicillin", "sulfa",
         "ozempic", "sertraline", "gabapentin", "ibuprofen", "warfarin", "walgreens", "cvs", "rite aid", "blue cross",
         "aetna", "medicare", "unitedhealthcare", "kaiser permanente", "10 mg", "500 mg", "40 mg", "5 mg", "75 mcg",
         "250 mg", "0.5 mg", "50 mg", "300 mg", "101.5", "ramanathan"]
def canon(t):
    t = normalize(t or "")
    toks = [UNIT.get(w, D.index(w) if False else w) for w in t.split()]
    toks = [str(D.index(w)) if w in D else w for w in toks]
    return " ".join(toks)
def strip_residue(gold_c, hyp_c):
    g, h = gold_c.split(), hyp_c.split()
    k = 0
    while k < min(3, len(h)) and h[k] in ID_RESIDUE and (not g or h[k] != g[0]): k += 1
    return " ".join(h[k:])
def squash(t): return re.sub(r"\b(dot|at)\b", "", t).replace(" ", "")
clips = {}
for spk_dir in sorted((ROOT / "data/phonein").iterdir()):
    if not (spk_dir / "script.txt").exists(): continue
    for line in (spk_dir / "script.txt").read_text().splitlines():
        if line.startswith("#") or not line.strip(): continue
        stem, lang, text = line.split("\t")
        clips[f"{spk_dir.name}__{stem}"] = {"spk": spk_dir.name, "pack": stem[0], "gold": text}
lane = {}
rows = collections.defaultdict(list)
for edir in sorted((RUN / "raw").iterdir()):
    eng = edir.name; lane[eng] = "realtime" if eng.startswith(("txrt", "el-scribe_v2_realtime")) else "batch"
    for cid, c in clips.items():
        f = edir / f"{cid}.json"
        if not f.exists(): continue
        r = json.loads(f.read_text())
        g = canon(c["gold"]); h = strip_residue(g, canon(r.get("text") or "")) if r.get("ok") else None
        rows[eng].append({**c, "id": cid, "ok": bool(r.get("ok")), "g": g, "h": h, "raw": r.get("text") or ""})
def summ(rs, pack, cond=None):
    rs = [r for r in rs if r["pack"] == pack and (cond is None or (("speakerphone" in r["spk"]) == (cond == "speaker")))]
    if not rs: return None
    ok = [r for r in rs if r["ok"]]; fail = len(rs) - len(ok)
    wer = jiwer.wer([r["g"] or "x" for r in ok], [r["h"] or "" for r in ok]) if ok else None
    exact = sum(1 for r in ok if squash(r["g"]) == squash(r["h"] or ""))
    def tol(r):
        g, h = r["g"].split(), (r["h"] or "").split()
        return squash(r["g"]) == squash(r["h"] or "") or (len(h) == len(g) + 1 and h[1:] == g)
    out = {"n": len(rs), "fail": fail, "wer": wer, "exact": exact, "exact_tol": sum(1 for r in ok if tol(r))}
    if pack == "S":
        wl = 0
        for r in ok:
            h = (r["raw"] or "").strip()
            if h and re.search(r"\b(ja|oui|nein|non|si|sí|nee|jo|da|evet|hayır|ne)\b", h.lower()) and not re.search(r"\bno\b", r["gold"].lower()):
                wl += 1
        out["wrong_lang"] = wl
    if pack == "M":
        hit = tot = 0
        for r in ok:
            for t in TERMS:
                n = len(re.findall(rf"(?<!\S){re.escape(t)}(?!\S)", r["g"]))
                if n: tot += n; hit += min(n, len(re.findall(rf"(?<!\S){re.escape(t)}(?!\S)", r["h"] or "")))
        out["terms"] = (hit, tot)
    return out
res = {e: {p: summ(rs, p) for p in "NSM"} | {f"{p}_{c}": summ(rs, p, c) for p in "NSM" for c in ("handset", "speaker")} for e, rs in rows.items()}
json.dump({"lane": lane, "results": res}, open(RUN / "phonein_scores.json", "w"), indent=1, default=str)
for ln in ("batch", "realtime"):
    print(f"\n== {ln.upper()} ==  (N names/numbers, S short turns, M medical; exact = whole line right)")
    print(f"{'engine':32} {'clips':>5} {'fail':>4} | {'N exact':>9} {'N WER':>6} | {'S ok*':>9} {'S wrongLang':>11} | {'M WER':>6} {'M terms':>9} | {'spkr N exact':>12} {'spkr M WER':>10}")
    for e in sorted(e for e in res if lane[e] == ln):
        r = res[e]; N, S, M = r["N"], r["S"], r["M"]; Ns, Ms = r["N_speaker"], r["M_speaker"]
        if not N: continue
        tot = sum(x["n"] for x in (N, S, M) if x); fl = sum(x["fail"] for x in (N, S, M) if x)
        f = lambda x: f"{x*100:5.1f}%" if x is not None else "  n/a"
        print(f"{e:32} {tot:5} {fl:4} | {N['exact']:>3}/{N['n']-N['fail']:<5} {f(N['wer'])} | {S['exact_tol']:>3}/{S['n']-S['fail']:<5} {S['wrong_lang']:>11} | {f(M['wer'])} {M['terms'][0]:>3}/{M['terms'][1]:<5} | "
              f"{(str(Ns['exact'])+'/'+str(Ns['n']-Ns['fail'])) if Ns else '-':>12} {f(Ms['wer']) if Ms else '-':>10}")

"""Export every engine output from every run into one flat per-clip table for slicing.
Writes exports/results_per_clip.csv (and .parquet if pyarrow is present).
One row = one clip x one engine x one run. Includes raw transcript, normalized gold/hyp, word errors
(S/D/I/N, so any WER slice = sum(S+D+I)/sum(N)), medical term hits, numbers, latency, failures, and
clip metadata (dataset, consultation/speaker/pack, language, duration). Re-run any time:
  .venv/bin/python report/export_all.py"""
import csv, importlib, json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from score.metrics import score_clip, term_index
from engines.registry import ENGINES
OUT = ROOT / "exports"; OUT.mkdir(parents=True, exist_ok=True)
COLS = ["run", "dataset", "subset", "engine", "vendor", "model", "lane", "clip", "group", "speaker", "pack", "condition", "lang", "kind",
        "dur_s", "ok", "error", "gold_raw", "hyp_raw", "gold_norm", "hyp_norm", "S", "D", "I", "N", "clip_wer",
        "terms_total", "terms_hit", "term_misses", "num_total", "num_hit", "hallucinated", "lid", "wrong_language",
        "ttfp_speech_s", "final_speech_s", "first_kind", "wall_s"]
rows = []
for run in sorted(p for p in (ROOT / "runs").iterdir() if (p / "meta.json").exists()):
    meta = json.loads((run / "meta.json").read_text())
    ds, subset = meta["dataset"], meta["subset"]
    loader = importlib.import_module(f"datasets.{ds}.loader")
    clips = {c["id"]: c for c in loader.load(subset)}
    tpath = getattr(loader, "TERMS", None)
    index = term_index(json.loads(pathlib.Path(tpath).read_text())["terms"]) if tpath and pathlib.Path(tpath).exists() else None
    for edir in sorted((run / "raw").iterdir()):
        base = edir.name.split("+")[0]; cfg = ENGINES.get(base, {})
        for f in edir.glob("*.json"):
            res = json.loads(f.read_text()); c = clips.get(f.stem)
            if not c: continue
            r = score_clip(c, res, index)
            spk = c.get("speaker") or (c["id"].split("__")[0] if ds == "phonein" else "")
            pack = c["id"].split("__")[1][0] if ds == "phonein" else ""
            rows.append({"run": run.name, "dataset": ds, "subset": subset, "engine": edir.name, "vendor": cfg.get("vendor"),
                "model": cfg.get("model"), "lane": cfg.get("lane"), "clip": c["id"], "group": c.get("group"), "speaker": spk,
                "pack": {"N": "names_numbers", "S": "short_turns", "M": "medical_phone"}.get(pack, ""),
                "condition": ("speakerphone" if "speakerphone" in spk else "handset") if ds == "phonein" else ("phone_codec_8k" if "rawlevel" not in run.name else "phone_codec_8k_rawlevel"),
                "lang": c["lang"], "kind": c.get("kind", "speech"), "dur_s": c["dur"], "ok": r["ok"], "error": r.get("error"),
                "gold_raw": c["gold"], "hyp_raw": res.get("text") if res.get("ok") else "", "gold_norm": r.get("gold_norm"), "hyp_norm": r.get("hyp_norm"),
                **{k: r.get(k) for k in ("S", "D", "I", "N")},
                "clip_wer": round((r["S"] + r["D"] + r["I"]) / r["N"], 4) if r.get("N") else None,
                "terms_total": sum((r.get("terms_total") or {}).values()) if r.get("terms_total") is not None else None,
                "terms_hit": sum((r.get("terms_hit") or {}).values()) if r.get("terms_hit") is not None else None,
                "term_misses": "|".join(r.get("term_misses") or []), "num_total": r.get("num_total"), "num_hit": r.get("num_hit"),
                "hallucinated": r.get("hallucinated"), "lid": r.get("lid"), "wrong_language": r.get("wrong_language"),
                "ttfp_speech_s": r.get("ttfp_speech_s"), "final_speech_s": r.get("final_speech_s"), "first_kind": r.get("first_kind"), "wall_s": r.get("wall_s")})
    print(run.name, "rows so far", len(rows), flush=True)
with open(OUT / "results_per_clip.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=COLS); w.writeheader(); w.writerows(rows)
try:
    import pandas as pd; pd.DataFrame(rows, columns=COLS).to_parquet(OUT / "results_per_clip.parquet", index=False); print("parquet ok")
except Exception as e:
    print("parquet skipped:", e)
(OUT / "README.md").write_text(open(__file__).read().split('"""')[1] + "\nRaw engine JSON per clip is written to runs/<run>/raw/<engine>/ when you run the harness; audio goes in data/.\n")
print("rows", len(rows), "->", OUT)

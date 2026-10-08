"""Score a run and write results.csv, scores/<engine>.jsonl and scorecard.html.

  python report/build.py --run-id 2026-10-01-medical-pilot [--copy-to <dir>]
"""
import argparse
import csv
import datetime
import difflib
import hashlib
import html
import importlib
import json
import pathlib
import random
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engines.common import PRICE_PER_HOUR  # noqa: E402
from engines.registry import ENGINES  # noqa: E402
from score import metrics  # noqa: E402
from score.normalize import normalize  # noqa: E402

DIFF_SAMPLES = 10
LANG_NAMES = {"en": "English", "de": "German", "fr": "French", "tr": "Turkish"}
DIFF_SEED = 11


def engine_dirs(run_dir):
    return sorted(p.name for p in (run_dir / "raw").iterdir() if p.is_dir())


def word_diff(gold, hyp):
    g, h = gold.split(), hyp.split()
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=g, b=h, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(html.escape(" ".join(g[i1:i2])))
        if op in ("replace", "delete"):
            out.append(f'<del>{html.escape(" ".join(g[i1:i2]))}</del>')
        if op in ("replace", "insert"):
            out.append(f'<ins>{html.escape(" ".join(h[j1:j2]))}</ins>')
    return " ".join(out)


def fmt(v, kind="pct"):
    if v is None:
        return "n/a"
    if kind == "pct":
        return f"{100 * v:.1f}%"
    if kind == "s":
        return f"{v:.2f} s"
    return str(v)


def build(run_id, copy_to=None):
    run_dir = ROOT / "runs" / run_id
    meta = json.loads((run_dir / "meta.json").read_text())
    loader = importlib.import_module(f"datasets.{meta['dataset']}.loader")
    clips = loader.load(meta["subset"])
    terms_path = getattr(loader, "TERMS", None)
    terms = json.load(open(terms_path)) if terms_path else None
    index = metrics.term_index(terms["terms"]) if terms else None
    (run_dir / "scores").mkdir(exist_ok=True)

    summaries = {}
    by_lang = {}
    rows_by_engine = {}
    for ed in engine_dirs(run_dir):
        eid = ed.split("+")[0]
        cfg = ENGINES[eid]
        # speech clips whose gold is empty under the current normalizer are excluded, as in prep
        eligible = [c for c in clips if c["lang"] in cfg["langs"] and (c["kind"] == "silence" or normalize(c["gold"], c["lang"]))]
        rows = [metrics.score_clip(c, metrics.load_raw(run_dir, ed, c["id"]), index) for c in eligible]
        rows_by_engine[ed] = rows
        with open(run_dir / "scores" / f"{ed}.jsonl", "w") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        s = metrics.summarize(rows)
        langs_here = sorted({c["lang"] for c in eligible})
        if len({c["lang"] for c in clips}) > 1:  # multilingual dataset: every engine gets per-language rows
            lang_of = {c["id"]: c["lang"] for c in eligible}
            for lg in langs_here:
                ls = metrics.summarize([r for r in rows if lang_of[r["id"]] == lg])
                ls.update({"engine": ed, "lane": cfg["lane"], "vendor": cfg["vendor"], "model": cfg["model"],
                           "keyterms": "+keyterms" in ed, "usd_per_audio_hour": PRICE_PER_HOUR[cfg["price"]],
                           "lang": lg, "missing": sum(r.get("error") == "missing" for r in rows if lang_of[r["id"]] == lg)})
                by_lang.setdefault(lg, {})[ed] = ls
        s.update({"lang": "all" if len({c["lang"] for c in clips}) > 1 else (langs_here[0] if langs_here else ""), "engine": ed, "lane": cfg["lane"], "vendor": cfg["vendor"], "model": cfg["model"],
                  "keyterms": "+keyterms" in ed, "usd_per_audio_hour": PRICE_PER_HOUR[cfg["price"]],
                  "missing": sum(r.get("error") == "missing" for r in rows),
                  "excluded_empty_gold": sum(1 for c in clips if c["lang"] in cfg["langs"] and c["kind"] == "speech"
                                             and not normalize(c["gold"], c["lang"]))})
        summaries[ed] = s

    if not getattr(loader, "LATENCY_COMPARABLE", True):
        for s_ in list(summaries.values()) + [x for d in by_lang.values() for x in d.values()]:
            for k in ("ttfp_p50", "ttfp_p90", "final_p50", "final_p90", "final_from_audio_end_p50"):
                s_.pop(k, None)
    cols = ["lane", "lang", "engine", "vendor", "model", "keyterms", "n_speech", "audio_min", "wer", "wer_ci95", "wer_ok_only",
            "sub_rate", "del_rate", "ins_rate", "term_recall", "num_recall", "num_total", "failures", "failure_rate",
            "missing", "wrong_language", "lid_judged", "hallucinations", "silence_probes", "ttfp_p50", "ttfp_p90", "final_p50", "final_p90",
            "wall_p50", "usd_per_audio_hour"]
    with open(run_dir / "results.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols + ["recall_drug", "recall_condition", "recall_dosage"])
        for s in list(summaries.values()) + [x for lg in sorted(by_lang) for x in by_lang[lg].values()]:
            cat = s["term_recall_by_cat"]
            w.writerow([json.dumps(s.get(c)) if isinstance(s.get(c), (list, dict)) else s.get(c) for c in cols]
                       + [cat.get(k, {}).get("recall") for k in ("drug", "condition", "dosage")])
    (run_dir / "summary.json").write_text(json.dumps({"all": summaries, "by_lang": by_lang}, indent=1))
    html_text = render(run_id, meta, summaries, rows_by_engine, terms, clips, by_lang, loader)
    out = run_dir / "scorecard.html"
    out.write_text(html_text)
    if copy_to:
        dest = pathlib.Path(copy_to).expanduser()
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy(out, dest / f"scorecard-{run_id}.html")
    return summaries


CSS = """
:root{--bg:#fbfaf7;--fg:#1d1c1a;--mut:#6b6760;--line:#e4e0d8;--card:#fff;--good:#1f7a4d;--goodbg:#e3f3ea;
--bad:#a8321f;--badbg:#fbe7e2;--acc:#b5532f;--ins:#e3f3ea;--del:#fbe7e2}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#171614;--fg:#ece8e1;--mut:#a39d93;
--line:#34312c;--card:#201e1b;--good:#6fd29f;--goodbg:#1d3a2b;--bad:#f0907c;--badbg:#45231b;--acc:#e08a62;--ins:#1d3a2b;--del:#45231b}}
:root[data-theme="dark"]{--bg:#171614;--fg:#ece8e1;--mut:#a39d93;--line:#34312c;--card:#201e1b;--good:#6fd29f;
--goodbg:#1d3a2b;--bad:#f0907c;--badbg:#45231b;--acc:#e08a62;--ins:#1d3a2b;--del:#45231b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,
"Segoe UI",Inter,system-ui,sans-serif}main{max-width:1180px;margin:0 auto;padding:28px 16px 64px;overflow-wrap:anywhere}html,body{overflow-x:hidden}
h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:36px 0 10px;border-bottom:1px solid var(--line);padding-bottom:6px}
h3{font-size:15px;margin:22px 0 8px}.mut{color:var(--mut)}.meta{display:flex;flex-wrap:wrap;gap:8px 22px;font-size:13px;color:var(--mut);margin:10px 0 0}
.tw{overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--card)}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}th{font-weight:600;color:var(--mut);background:var(--bg);position:sticky;top:0}
td.best{background:var(--goodbg);color:var(--good);font-weight:600}td.worst{color:var(--bad)}
tr.el td:first-child{border-left:3px solid var(--acc)}
.diff{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:6px 0;font-size:13px}
.diff .g{color:var(--mut)}del{background:var(--del);color:var(--bad);text-decoration:line-through}
ins{background:var(--ins);color:var(--good);text-decoration:none}details{margin:6px 0}summary{cursor:pointer;font-weight:600}
code{font-size:12px;background:var(--card);border:1px solid var(--line);border-radius:4px;padding:1px 4px}
ul{padding-left:20px}.note{font-size:13px;color:var(--mut)}
"""


def table(lane, summaries, latency, terms=True):
    rows = [s for s in summaries.values() if s["lane"] == lane]
    if not rows:
        return ""
    metrics_cols = [("WER", "wer", "pct", "low"), ("WER 95% CI", "wer_ci95", "ci", None),
                    ("WER excl. failures", "wer_ok_only", "pct", "low"),
                    ("Sub", "sub_rate", "pct", "low"), ("Del", "del_rate", "pct", "low"), ("Ins", "ins_rate", "pct", "low"),
                    ("Term recall", "term_recall", "pct", "high"), ("Drug", "rec_drug", "pct", "high"),
                    ("Condition", "rec_condition", "pct", "high"), ("Dosage", "rec_dosage", "pct", "high"),
                    ("Numbers", "num_recall", "pct", "high"), ("Failures", "failures", "int", "low"),
                    ("Wrong lang.", "wronglang", "str", None), ("Halluc. on silence", "halluc", "str", None)]
    if not terms:
        metrics_cols = [c for c in metrics_cols if c[1] not in ("term_recall", "rec_drug", "rec_condition", "rec_dosage")]
    if not any(s["silence_probes"] for s in rows):
        metrics_cols = [c for c in metrics_cols if c[1] != "halluc"]
    if latency:
        metrics_cols += [("TTFT p50", "ttfp_p50", "s", "low"), ("Final p50", "final_p50", "s", "low"),
                         ("Final p90", "final_p90", "s", "low")]
    metrics_cols += [("$/audio h", "usd_per_audio_hour", "usd", "low")]
    for s in rows:
        for k in ("drug", "condition", "dosage"):
            s["rec_" + k] = s["term_recall_by_cat"].get(k, {}).get("recall")
        s["halluc"] = f'{s["hallucinations"]}/{s["silence_probes"]}'
        s["wronglang"] = f'{s["wrong_language"]}/{s["lid_judged"]}'
    rows.sort(key=lambda s: (s["wer"] if s["wer"] is not None else 9))
    best = {}
    for _, k, kind, d in metrics_cols:
        vals = [s.get(k) for s in rows if isinstance(s.get(k), (int, float))]
        if d and len(vals) > 1:
            best[k] = (min(vals) if d == "low" else max(vals), max(vals) if d == "low" else min(vals))
    # occurrence counts next to recall headers, so small denominators are visible
    tot = {k: max(s["term_recall_by_cat"].get(k, {}).get("total", 0) for s in rows) for k in ("drug", "condition", "dosage")}
    tot["term_recall"] = sum(tot.values())
    tot["num_recall"] = max(s.get("num_total", 0) for s in rows)

    def label(c):
        k = c[1].replace("rec_", "")
        return f'{c[0]} <span class="mut">n={tot[k]}</span>' if k in tot and tot[k] else c[0]
    h = ['<div class="tw"><table><thead><tr><th>Engine</th>' + "".join(f"<th>{label(c)}</th>" for c in metrics_cols) + "</tr></thead><tbody>"]
    for s in rows:
        cls = "el" if s["vendor"] == "elevenlabs" else ""
        name = html.escape(s["engine"]) + (f' <span class="mut">({s["n_speech"]} clips)</span>')
        tds = []
        for _, k, kind, d in metrics_cols:
            v = s.get(k)
            if kind == "ci":
                txt = f"{100 * v[0]:.1f} to {100 * v[1]:.1f}" if v and v[0] is not None else "n/a"
            elif kind == "usd":
                txt = f"${v:.2f}"
            elif kind == "int":
                txt = str(v)
            elif kind == "str":
                txt = str(v)
            else:
                txt = fmt(v, kind)
            c = ""
            if k in best and isinstance(v, (int, float)):
                c = "best" if v == best[k][0] else ("worst" if v == best[k][1] else "")
            tds.append(f'<td class="{c}">{txt}</td>')
        h.append(f'<tr class="{cls}"><td>{name}</td>' + "".join(tds) + "</tr>")
    h.append("</tbody></table></div>")
    return "".join(h)


def render(run_id, meta, summaries, rows_by_engine, terms, clips, by_lang=None, loader_mod=None):
    when = datetime.datetime.fromtimestamp(meta.get("created") or meta["passes"][0]["start"]).strftime("%Y-%m-%d %H:%M")
    norm_sha = hashlib.sha256((ROOT / "score" / "normalize.py").read_bytes()).hexdigest()[:12]
    parts = [f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
             f"<title>STT Scorecard {html.escape(run_id)}</title><style>{CSS}</style></head><body><main>",
             f"<h1>STT scorecard: {html.escape(run_id)}</h1>",
             f'<div class="meta"><span>Dataset: {html.escape(meta["dataset"])} ({html.escape(meta["subset"])})</span>'
             f'<span>{meta["n_clips"]} clips, {meta["audio_seconds"] / 60:.1f} min</span><span>Run started {when}</span>'
             f'<span>Audio: 8 kHz G.711 mu-law (codec simulation)</span><span>Normalizer sha {norm_sha}</span>'
             + (f'<span>Term list sha {terms["sha256"][:12]} ({terms["n_terms"]} terms)</span>' if terms else "")
             + f'<span>Clip list sha {meta["clip_list_sha256"][:12]}</span></div>']
    missing = {e: s["missing"] for e, s in summaries.items() if s["missing"]}
    if missing:
        parts.append('<p class="diff" style="border-color:var(--bad)"><strong>Incomplete run.</strong> Clips not yet run: '
                     + ", ".join(f"{html.escape(e)} {n}" for e, n in missing.items())
                     + ". Missing clips count as failures in this view. Do not quote these numbers.</p>")
    dns_dir = ROOT / "runs" / run_id / "client_dns_failures"
    if dns_dir.exists():
        n = sum(1 for _ in dns_dir.rglob("*.json"))
        parts.append(f'<p class="note">Re-run after a client-side failure: {n} requests failed before reaching any server, '
                     'from local DNS failures for api.telnyx.com (NameResolutionError, plus WebSocket handshake timeouts in the same minutes '
                     'across all Telnyx engines while ElevenLabs sessions succeeded). They were re-run. Originals are kept in client_dns_failures/.</p>')
    lanes = sorted({s["lane"] for s in summaries.values()})
    for lane in lanes:
        parts.append(f"<h2>{'Batch lane (file in, transcript out)' if lane == 'batch' else 'Realtime lane (streamed at real-time pace, 100 ms chunks)'}</h2>")
        lat = lane == "realtime" and getattr(loader_mod, "LATENCY_COMPARABLE", True)
        if lane == "realtime" and not lat:
            parts.append('<p class="note">Latency is not shown for this dataset. Its clips carry variable trailing silence, so '
                         'end-of-audio flushes and silence endpointing are not comparable. See the medical scorecard for latency.</p>')
        if by_lang:
            for lg in sorted(by_lang):
                parts.append(f"<h3>{LANG_NAMES.get(lg, lg)}</h3>")
                parts.append(table(lane, by_lang[lg], latency=lat, terms=bool(terms)))
            parts.append("<h3>All languages pooled</h3>")
            parts.append('<p class="note">Pooled rows are only comparable when the clip counts match. An engine that does not '
                         'support a language is not run on it, so its pooled row covers fewer languages. Compare per language above.</p>')
        parts.append(table(lane, summaries, latency=lat, terms=bool(terms)))
        parts.append('<p class="note">Sorted by WER. Green marks the best value in a column, red the worst. '
                     'ElevenLabs rows have an orange left edge. Failures count as empty transcripts in WER. WER excl. failures scores only the requests that returned.</p>')
    parts.append("<h2>Diffs (seeded sample of 10 speech clips, same clips for every engine)</h2>")
    speech_ids = [c["id"] for c in clips if c["kind"] == "speech"]
    sample = random.Random(DIFF_SEED).sample(speech_ids, min(DIFF_SAMPLES, len(speech_ids)))
    for ed, rows in rows_by_engine.items():
        by_id = {r["id"]: r for r in rows}
        items = []
        for cid in sample:
            r = by_id.get(cid)
            if not r:
                continue
            items.append(f'<div class="diff"><div class="g">{html.escape(cid)} | WER contribution '
                         f'{r["S"] + r["D"] + r["I"]}/{r["N"]}{"" if r["ok"] else " | FAILED: " + html.escape(str(r["error"]))}</div>'
                         f'{word_diff(r["gold_norm"], r["hyp_norm"])}</div>')
        misses = {}
        for r in rows:
            for t in r.get("term_misses", []):
                misses[t] = misses.get(t, 0) + 1
        top = ", ".join(f"{html.escape(t)} ({n})" for t, n in sorted(misses.items(), key=lambda x: -x[1])[:25])
        parts.append(f"<details><summary>{html.escape(ed)}</summary>{''.join(items)}"
                     f"<p class='note'>Most-missed terms: {top or 'none'}</p></details>")
    parts.append("""<h2>Method</h2><ul>
<li>Ground truth: human utterance-level transcripts. Utterances with &lt;UNIN/&gt;, &lt;INAUDIBLE_SPEECH/&gt; or &lt;UNSURE&gt; markup are excluded, as are those that are empty after normalization.</li>
<li>Same audio to every engine: each clip is cut from the 16 kHz source with 150 ms padding and transcoded once to 8 kHz G.711 mu-law. Batch engines and Telnyx realtime receive 16-bit PCM decoded from that mu-law. ElevenLabs realtime receives the mu-law bytes directly.</li>
<li>Defaults on every engine. The only parameter set is the known language, on engines that accept one. Keyterm passes, where present, are labelled +keyterms and use one shared list.</li>
<li>Normalization: Whisper EnglishTextNormalizer plus unit rules (mg to milligrams and similar) and okay/OK, applied to gold and hypothesis alike (score/normalize.py).</li>
<li>Realtime: 100 ms chunks at real-time pace. The flush is the ElevenLabs commit or Telnyx CloseStream where supported. Engines without a flush control get trailing real-time silence. TTFT is the time from the first speech chunk to the first non-empty text. Final is the time from the last speech chunk to the last final transcript.</li>
<li>Term list: fixed before any engine ran. It holds Wikidata (CC0) drug and condition labels matched against gold, with common words and anatomy excluded, plus dosage and dosing patterns (datasets/primock57/terms.json).</li>
<li>Prices: ElevenLabs https://elevenlabs.io/pricing/api, Telnyx https://telnyx.com/pricing/speech-to-text, both read 2026-10-01, list pay-as-you-go.</li>
<li>Data: PriMock57, Babylon Health, CC-BY 4.0, https://github.com/babylonhealth/primock57 (Papadopoulos Korfiatis et al., ACL 2022).</li>
</ul></main></body></html>""")
    return "".join(parts)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--copy-to")
    a = ap.parse_args()
    for s in build(a.run_id, a.copy_to).values():
        print(f'{s["engine"]:32s} wer={fmt(s["wer"])} terms={fmt(s["term_recall"])} fail={s["failures"]} missing={s["missing"]}'
              + (f' final_p50={fmt(s.get("final_p50"), "s")}' if "final_p50" in s else ""))

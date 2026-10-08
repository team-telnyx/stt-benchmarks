"""Run engines over a dataset subset. Resumable: a clip whose raw output exists is skipped.

  python run.py --dataset primock57 --subset pilot --lane batch --run-id 2026-10-01-medical-pilot
  python run.py ... --engines el-scribe_v2,tx-nova-3 --keyterms   (labelled second pass)

Writes runs/<run-id>/raw/<engine>/<clip>.json (full engine output, errors included),
runs/<run-id>/meta.json (dataset, subset, clip list hash, prices; created once) and
runs/<run-id>/passes/<time>-<lane>-<pid>.json (engines, keyterms, start/end, per-engine stats).
"""
import argparse
import asyncio
import concurrent.futures
import hashlib
import importlib
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
MAX_CONNECT_TRIES = 40
SESSION_SLACK_S = 45.0
sys.path.insert(0, str(ROOT))
from engines import batch, realtime  # noqa: E402
from engines.common import PRICE_PER_HOUR, Ledger, SpendCapError  # noqa: E402
from engines.registry import CONCURRENCY, ENGINES  # noqa: E402


def wav_pcm_bytes(path):
    import soundfile as sf
    data, sr = sf.read(str(path), dtype="int16")
    assert sr == 8000, path
    return data.tobytes()


def keyterm_list(dataset):
    mod = importlib.import_module(f"datasets.{dataset}.loader")
    terms_path = getattr(mod, "TERMS", None)
    if not terms_path:
        return None
    terms = json.load(open(terms_path))["terms"]
    # same list to every engine that accepts keyterms; capped at 100 (ElevenLabs batch limit; UNVERIFIED for others)
    ranked = sorted((t for t in terms if t["category"] != "dosage"), key=lambda t: -t["gold_occurrences"])
    return [t["term"] for t in ranked[:100]]


async def run_engine(eid, clips, out_dir, run_id, keyterms, auto_lang=False):
    cfg = ENGINES[eid]
    sem = asyncio.Semaphore(cfg.get("conc") or CONCURRENCY[(cfg["lane"], cfg["vendor"])])
    ledger = Ledger(cfg["vendor"])
    d = out_dir / "raw" / (eid + ("+keyterms" if keyterms else "") + ("+autolang" if auto_lang else ""))
    d.mkdir(parents=True, exist_ok=True)
    stats = {"done": 0, "skipped": 0, "failed": 0, "cap": False}

    async def one(c):
        path = d / f"{c['id']}.json"
        if path.exists():
            stats["skipped"] += 1
            return
        if c["lang"] not in cfg["langs"]:
            return
        lang = None if auto_lang else c["lang"]
        async with sem:
            if stats["cap"]:
                return
            try:
                ledger.charge(cfg["price"], c["dur"], run_id, c["id"])
            except SpendCapError as e:
                stats["cap"] = True
                print(f"[{eid}] STOP {e}", flush=True)
                return
            t0 = time.time()
            try:
                if cfg["lane"] == "batch":
                    fn = {"elevenlabs": batch.elevenlabs, "omi": batch.omi}.get(cfg["vendor"], batch.telnyx)
                    res = await asyncio.to_thread(fn, cfg["model"], c["pcm8k"], lang, keyterms)
                else:
                    # a socket that never opened (handshake refused or timed out, TLS or DNS error) is
                    # retried and counted; anything after the socket opens is the engine's result
                    # pre-connection failures include local DNS bursts lasting minutes: up to 40 tries, 15 s apart
                    for attempt in range(MAX_CONNECT_TRIES):
                        # hard ceiling: a hung session (seen 2026-10-01: socket open, nothing moving for 40 min)
                        # is scored as a failure instead of stalling the run
                        if cfg["vendor"] == "elevenlabs":
                            coro = realtime.elevenlabs(c["ulaw"].read_bytes(), lang, cfg["model"], keyterms)
                        elif cfg["vendor"] == "omi":
                            coro = realtime.omi(wav_pcm_bytes(c["pcm8k"]), lang, cfg["model"])
                        else:
                            coro = realtime.telnyx(wav_pcm_bytes(c["pcm8k"]), lang, cfg["engine"], cfg["model"], keyterms)
                        try:
                            res = await asyncio.wait_for(coro, c["dur"] + SESSION_SLACK_S)
                        except asyncio.TimeoutError:
                            res = {"ok": False, "error": f"session_timeout: no completion within clip + {SESSION_SLACK_S:.0f} s",
                                   "text": None, "connect_s": 0.0}
                        if res["ok"] or res.get("connect_s") is not None or attempt == MAX_CONNECT_TRIES - 1:
                            break
                        await asyncio.sleep(15)
                    res["connect_retries"] = attempt
            except Exception as e:  # any adapter crash is a scored failure
                res = {"ok": False, "error": f"{type(e).__name__}: {e}", "text": None}
            res.update({"engine": eid, "clip": c["id"], "started": t0, "keyterms": bool(keyterms), "language_hint": lang})
            path.write_text(json.dumps(res, ensure_ascii=False))
            stats["done"] += 1
            if not res["ok"]:
                stats["failed"] += 1
            if stats["done"] % 50 == 0:
                print(f"[{eid}] {stats}", flush=True)

    await asyncio.gather(*[one(c) for c in clips])
    print(f"[{eid}] finished {stats}", flush=True)
    return eid, stats


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--subset", default="pilot")
    ap.add_argument("--lane", choices=["batch", "realtime"], required=True)
    ap.add_argument("--engines", default="")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--keyterms", action="store_true")
    ap.add_argument("--auto-language", action="store_true",
                    help="labelled pass with no language hint (Deepgram gets 'multi'); output dir suffix +autolang")
    ap.add_argument("--medical", action="store_true", help="include medical-only engines")
    a = ap.parse_args()

    loader = importlib.import_module(f"datasets.{a.dataset}.loader")
    clips = loader.load(a.subset)
    eids = a.engines.split(",") if a.engines else [
        e for e, c in ENGINES.items() if c["lane"] == a.lane and (a.medical or not c.get("medical"))
        and not (a.medical and c.get("general_only"))]
    for e in eids:
        assert ENGINES[e]["lane"] == a.lane, f"{e} is not a {a.lane} engine; lanes are never mixed"
    keyterms = keyterm_list(a.dataset) if a.keyterms else None

    out = ROOT / "runs" / a.run_id
    (out / "passes").mkdir(parents=True, exist_ok=True)
    clip_ids = [c["id"] for c in clips]
    meta = {"dataset": a.dataset, "subset": a.subset, "n_clips": len(clips),
            "audio_seconds": round(sum(c["dur"] for c in clips), 2),
            "clip_list_sha256": hashlib.sha256("\n".join(clip_ids).encode()).hexdigest(),
            "prices_per_hour": PRICE_PER_HOUR, "created": time.time()}
    try:  # first invocation creates it; concurrent passes (batch + realtime) never rewrite it
        with open(out / "meta.json", "x") as f:
            json.dump(meta, f, indent=1)
    except FileExistsError:
        prev = json.loads((out / "meta.json").read_text())
        assert prev["clip_list_sha256"] == meta["clip_list_sha256"], "run id reused with a different clip list"
    started = time.time()
    pass_path = out / "passes" / f"{time.strftime('%Y%m%dT%H%M%S')}-{a.lane}-{os.getpid()}.json"
    pass_info = {"lane": a.lane, "engines": eids, "keyterms": keyterms, "auto_language": a.auto_language, "start": started}
    pass_path.write_text(json.dumps(pass_info, indent=1))
    print(f"{len(clips)} clips, {meta['audio_seconds'] / 60:.1f} min, engines={eids}", flush=True)

    # batch adapters block in threads (Telnyx waits on its 1 req/s pacer); give every engine room
    asyncio.get_running_loop().set_default_executor(concurrent.futures.ThreadPoolExecutor(64))
    results = await asyncio.gather(*[run_engine(e, clips, out, a.run_id, keyterms, a.auto_language) for e in eids])
    pass_info.update({"end": time.time(), "stats": dict(results)})
    pass_path.write_text(json.dumps(pass_info, indent=1))


if __name__ == "__main__":
    asyncio.run(main())

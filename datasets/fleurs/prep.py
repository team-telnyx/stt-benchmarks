"""Google FLEURS test split for en, de, fr, tr: download, pick one recording per sentence, transcode.

License: CC-BY 4.0. Verified 2026-10-01: dataset card YAML `license: - cc-by-4.0`, HF API tag
`license:cc-by-4.0`, `gated: false`; card text "All datasets are licensed under the Creative
Commons license (CC-BY)". https://huggingface.co/datasets/google/fleurs
Citation: Conneau et al., "FLEURS: Few-shot Learning Evaluation of Universal Representations of
Speech", SLT 2022.

FLEURS is read speech (Wikipedia sentences, 2-3 speakers per sentence). We keep one recording per
sentence id, chosen with a fixed seed, so every sentence counts once. Gold = the raw transcription
column (cased, punctuated, as read). Same audio chain as PriMock57 (datasets/audio.py): the
telephone-level gate, then 8 kHz G.711 mu-law plus PCM decoded from that mu-law. The gate matters
here: FLEURS English has a median active speech level of -57 dBFS (71% of clips below -40 dBFS).
Audio prepared before the gate is kept in data/fleurs/clips_rawlevel/ for the uncalibrated run. Pilot = the first 100 sentence ids per language in seeded order.
Outputs: datasets/fleurs/clips.jsonl and pilot.txt (committed); audio in data/fleurs/ (gitignored).
"""
import csv
import json
import pathlib
import random
import subprocess
import tarfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from datasets.audio import gate_gain_db, transcode  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent
DATA = ROOT / "data" / "fleurs"
LANGS = {"en": "en_us", "de": "de_de", "fr": "fr_fr", "tr": "tr_tr"}
BASE = "https://huggingface.co/datasets/google/fleurs/resolve/main/data/{code}/{f}"
SEED = 20261001
PILOT_PER_LANG = 100

csv.field_size_limit(10 ** 7)


def fetch(code):
    d = DATA / "raw" / code
    d.mkdir(parents=True, exist_ok=True)
    for f in ("test.tsv", "audio/test.tar.gz"):
        dest = d / pathlib.Path(f).name
        if not dest.exists():
            tmp = dest.with_suffix(dest.suffix + ".part")
            urllib.request.urlretrieve(BASE.format(code=code, f=f), tmp)
            tmp.rename(dest)
    wav_dir = d / "wav"
    if not wav_dir.exists():
        with tarfile.open(d / "test.tar.gz") as t:
            t.extractall(d / "_x", filter="data")
        found = list((d / "_x").rglob("*.wav"))
        wav_dir.mkdir()
        for w in found:
            w.rename(wav_dir / w.name)
    return d


def main():
    clips_out, pilot = [], []
    for lang, code in LANGS.items():
        d = fetch(code)
        by_sentence = {}
        with open(d / "test.tsv", newline="") as f:
            for row in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
                sid, fname, raw, _norm, _chars, n_samples, gender = row[:7]
                by_sentence.setdefault(sid, []).append((fname, raw, int(n_samples), gender))
        rng = random.Random(f"{SEED}-{lang}")
        sids = sorted(by_sentence, key=int)
        rng.shuffle(sids)
        out_dir = DATA / "clips" / lang
        out_dir.mkdir(parents=True, exist_ok=True)
        jobs = []
        for rank, sid in enumerate(sids):
            fname, raw, n, gender = sorted(by_sentence[sid])[rng.randrange(len(by_sentence[sid]))]
            cid = f"fleurs_{lang}_{sid}"
            clips_out.append({"id": cid, "lang": lang, "sentence_id": sid, "src": fname, "gold": raw,
                              "dur": round(n / 16000, 3), "gender": gender, "rank": rank})
            if rank < PILOT_PER_LANG:
                pilot.append(cid)
            jobs.append((d / "wav" / fname, out_dir / cid, clips_out[-1]))

        def run(job):
            src, base, row = job
            row["gain_db"], row["active_dbfs"] = gate_gain_db(src)
            if not (base.with_suffix(".pcm8k.wav").exists() and base.with_suffix(".ulaw").exists()):
                transcode(src, base, row["gain_db"])
        with ThreadPoolExecutor(8) as ex:
            list(ex.map(run, jobs))
    with open(HERE / "clips.jsonl", "w") as f:
        for c in clips_out:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    (HERE / "pilot.txt").write_text("\n".join(pilot) + "\n")
    stats = {lang: {"sentences": sum(c["lang"] == lang for c in clips_out),
                    "gated": sum(c["lang"] == lang and c["gain_db"] != 0 for c in clips_out),
                    "hours": round(sum(c["dur"] for c in clips_out if c["lang"] == lang) / 3600, 3),
                    "pilot_min": round(sum(c["dur"] for c in clips_out if c["lang"] == lang and c["rank"] < PILOT_PER_LANG) / 60, 2)}
             for lang in LANGS}
    (HERE / "prep_stats.json").write_text(json.dumps(stats, indent=1) + "\n")
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()

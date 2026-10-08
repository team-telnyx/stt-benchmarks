"""PriMock57 full set, batch lane, in ~45 s chunks (max 50 s).
Why: Telnyx REST STT allows 1 request/s per account; 4,384 utterance clips x 5 Telnyx models would take ~6 h.
Each chunk = consecutive utterance clips of ONE consultation channel (doctor or patient), joined in order
with 0.3 s of digital silence between them (no untranscribed crosstalk enters). Gold = the utterance golds
joined with spaces. Same chunk files go to every engine. Silence probes are not included (batch WER only).
prep:  .venv/bin/python -m datasets.primock57chunk.loader"""
import json, pathlib, subprocess, sys
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC = ROOT / "data/primock57/clips"
OUT = ROOT / "data/primock57chunk"
MAX_S, TARGET_S, GAP_S = 50.0, 45.0, 0.3


def plan():
    rows = [json.loads(l) for l in open(ROOT / "datasets/primock57/clips.jsonl")]
    groups, cur, key = [], [], None
    for r in rows:  # clips.jsonl is ordered by consultation, speaker, time
        k = (r["consultation"], r["speaker"])
        dur = sum(x["dur"] + GAP_S for x in cur)
        if cur and (k != key or dur + r["dur"] > MAX_S or dur >= TARGET_S):
            groups.append(cur); cur = []
        cur.append(r); key = k
    if cur: groups.append(cur)
    return groups


def prep():
    OUT.mkdir(parents=True, exist_ok=True)
    meta = []
    for i, g in enumerate(plan()):
        cid = f"{g[0]['consultation']}_{g[0]['speaker']}_c{i:04d}"
        lst = OUT / f"{cid}.txt"
        lst.write_text("".join(f"file '{SRC / (r['id'] + '.pcm8k.wav')}'\nfile '{OUT / '_gap.wav'}'\n" for r in g))
        meta.append({"id": cid, "consultation": g[0]["consultation"], "speaker": g[0]["speaker"],
                     "gold": " ".join(r["gold"] for r in g), "dur": round(sum(r["dur"] for r in g) + GAP_S * len(g), 3),
                     "parts": [r["id"] for r in g]})
    ff = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y"]
    subprocess.run(ff + ["-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono", "-t", str(GAP_S), "-c:a", "pcm_s16le", str(OUT / "_gap.wav")], check=True)
    for m in meta:
        lst = OUT / f"{m['id']}.txt"
        subprocess.run(ff + ["-f", "concat", "-safe", "0", "-i", str(lst), "-c:a", "pcm_s16le", "-ar", "8000", "-ac", "1", str(OUT / f"{m['id']}.pcm8k.wav")], check=True)
        lst.unlink()
    (OUT / "chunks.jsonl").write_text("".join(json.dumps(m) + "\n" for m in meta))
    print(f"{len(meta)} chunks, {sum(m['dur'] for m in meta)/3600:.2f} h, max {max(m['dur'] for m in meta):.1f} s")


def load(subset="full"):
    out = []
    for l in open(OUT / "chunks.jsonl"):
        m = json.loads(l)
        out.append({"id": m["id"], "lang": "en", "gold": m["gold"], "group": m["consultation"], "kind": "speech",
                    "dur": m["dur"], "speaker": m["speaker"], "pcm8k": OUT / f"{m['id']}.pcm8k.wav", "ulaw": None})
    return out


TERMS = ROOT / "datasets/primock57/terms.json"

if __name__ == "__main__":
    prep()

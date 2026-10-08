"""PriMock57 clip loader. subset: 'pilot' (7 seeded consultations), 'rt90' (realtime subset: consultations
ordered by sha1 of their name, taken until >= 90 min of utterance audio), or 'full'. Silence probes always included."""
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
CLIPS = HERE.parents[1] / "data" / "primock57" / "clips"


def rt90_consultations(rows, minutes=90.0):
    import hashlib
    dur = {}
    for r in rows:
        dur[r["consultation"]] = dur.get(r["consultation"], 0) + r["dur"]
    picked, total = set(), 0.0
    for c in sorted(dur, key=lambda c: hashlib.sha1(c.encode()).hexdigest()):
        if total >= minutes * 60:
            break
        picked.add(c); total += dur[c]
    return picked


def load(subset="pilot"):
    pilot = set((HERE / "pilot.txt").read_text().split())
    rows = [json.loads(l) for l in open(HERE / "clips.jsonl")]
    if subset == "pilot":
        rows = [r for r in rows if r["consultation"] in pilot]
    elif subset == "rt90":
        rows = [r for r in rows if r["consultation"] in rt90_consultations(rows)]
    rows += [json.loads(l) for l in open(HERE / "silence.jsonl")]
    out = []
    for r in rows:
        base = CLIPS / r["id"]
        out.append({"id": r["id"], "lang": "en", "gold": r["gold"], "group": r["consultation"],
                    "kind": r.get("kind", "speech"), "dur": r["dur"], "speaker": r["speaker"],
                    "pcm8k": base.with_suffix(".pcm8k.wav"), "ulaw": base.with_suffix(".ulaw")})
    return out


TERMS = HERE / "terms.json"

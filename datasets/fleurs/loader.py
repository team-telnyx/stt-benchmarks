"""FLEURS loader. subset: 'pilot' (100 sentences per language) or 'full', optionally '-<lang>' (e.g.
'pilot-de'), optionally ':rawlevel' for the audio prepared before the telephone-level gate
(data/fleurs/clips_rawlevel/, used by run 2026-10-01-general-pilot-rawlevel)."""
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
CLIPS = HERE.parents[1] / "data" / "fleurs" / "clips"
TERMS = None
# FLEURS clips are whole recordings with up to several seconds of trailing silence. End-of-audio
# flushes (ElevenLabs commit, CloseStream) then wait out that silence while silence-endpointing
# engines do not, so latency here measures the flush protocol, not the engine. Use PriMock57.
LATENCY_COMPARABLE = False


def load(subset="pilot"):
    rows = [json.loads(l) for l in open(HERE / "clips.jsonl")]
    subset, _, variant = subset.partition(":")
    clips_dir = CLIPS.with_name("clips_rawlevel") if variant == "rawlevel" else CLIPS
    name, _, lang = subset.partition("-")
    if name == "pilot":
        keep = set((HERE / "pilot.txt").read_text().split())
        rows = [r for r in rows if r["id"] in keep]
    if lang:
        rows = [r for r in rows if r["lang"] == lang]
    out = []
    for r in rows:
        base = clips_dir / r["lang"] / r["id"]
        out.append({"id": r["id"], "lang": r["lang"], "gold": r["gold"], "group": f'{r["lang"]}-{r["sentence_id"]}',
                    "kind": "speech", "dur": r["dur"], "speaker": r["gender"], "gain_db": r.get("gain_db", 0.0),
                    "pcm8k": base.with_suffix(".pcm8k.wav"), "ulaw": base.with_suffix(".ulaw")})
    return out

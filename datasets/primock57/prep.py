"""Segment PriMock57 into utterance clips, transcode to phone audio, write the clip manifest.

Each TextGrid interval with text becomes one clip from its own channel (doctor or patient).
Excluded (logged with reason, never scored): utterances with <UNIN/>, <INAUDIBLE_SPEECH/> or
<UNSURE> markup (gold incomplete or uncertain), and utterances whose gold is empty after
normalization (pure fillers such as "Um.").

Audio chain per clip: 16 kHz source -> cut with 150 ms padding (clamped to neighbours) ->
telephone-level gate (datasets/audio.py; speech clips below -36 dBFS raised to -26 dBFS) ->
8 kHz G.711 mu-law (ffmpeg pcm_mulaw) = phone codec simulation. From that one mu-law file we
derive (a) raw .ulaw bytes for engines that take mu-law and (b) a 16-bit PCM 8 kHz WAV decoded
from the same mu-law samples for engines that take PCM. Every engine hears the same signal.

Outputs: datasets/primock57/clips.jsonl (committed), datasets/primock57/pilot.txt (committed),
audio under data/primock57/clips/ (gitignored).
"""
import json
import pathlib
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from praatio import textgrid

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from score.normalize import normalize, strip_markup  # noqa: E402
from datasets.audio import gate_gain_db, transcode  # noqa: E402

RAW = ROOT / "data" / "primock57" / "raw"
CLIPS = ROOT / "data" / "primock57" / "clips"
HERE = pathlib.Path(__file__).resolve().parent
PAD = 0.15
PILOT_SEED = 20261001
PILOT_TARGET_S = 30 * 60


def utterances():
    for tg_path in sorted((RAW / "transcripts").glob("*.TextGrid")):
        stem = tg_path.stem  # day1_consultation01_doctor
        consult, speaker = stem.rsplit("_", 1)
        tg = textgrid.openTextgrid(str(tg_path), includeEmptyIntervals=False)
        entries = [e for tn in tg.tierNames for e in tg.getTier(tn).entries if e.label.strip()]
        entries.sort(key=lambda e: e.start)
        for i, e in enumerate(entries):
            prev_end = entries[i - 1].end if i else 0.0
            next_start = entries[i + 1].start if i + 1 < len(entries) else e.end + PAD
            yield {
                "id": f"{stem}_{i:04d}",
                "consultation": consult,
                "speaker": speaker,
                "src": f"{stem}.wav",
                "start": round(max(prev_end, e.start - PAD, 0.0), 3),
                "end": round(min(next_start, e.end + PAD), 3),
                "utt_start": round(e.start, 3),
                "utt_end": round(e.end, 3),
                "raw_text": e.label.strip(),
            }


def classify(u):
    t = u["raw_text"]
    if "<UNIN/>" in t or "<INAUDIBLE_SPEECH/>" in t:
        return "unintelligible_markup"
    if "UNSURE>" in t:
        return "unsure_markup"
    if not normalize(t):
        return "empty_after_normalization"
    return None


def make_clip(u):
    base = CLIPS / u["id"]
    if base.with_suffix(".pcm8k.wav").exists() and base.with_suffix(".ulaw").exists() and "gain_db" in u:
        return
    src = RAW / "audio" / u["src"]
    # telephone-level gate (datasets/audio.py) on speech only; silence probes keep their room tone
    u["gain_db"] = 0.0 if u.get("kind") == "silence" else gate_gain_db(src, u["start"], u["end"])[0]
    transcode(src, base, u["gain_db"], u["start"], u["end"])


SILENCE_S = 3.0
SILENCE_GUARD = 0.2


def silence_probes():
    """One 3 s window per consultation where neither channel has any transcribed interval
    (tagged or not) within 0.2 s. Alternates doctor/patient channel. Gold is empty."""
    by_consult = {}
    for u in utterances():
        by_consult.setdefault(u["consultation"], []).append((u["utt_start"], u["utt_end"]))
    probes = []
    for n, (c, spans) in enumerate(sorted(by_consult.items())):
        spans.sort()
        speaker = "doctor" if n % 2 == 0 else "patient"
        cursor = 0.0
        for s, e in spans:
            if s - cursor >= SILENCE_S + 2 * SILENCE_GUARD and cursor > 0:
                start = round(cursor + SILENCE_GUARD, 3)
                u = {"id": f"{c}_{speaker}_silence", "consultation": c, "speaker": speaker,
                     "src": f"{c}_{speaker}.wav", "start": start, "end": round(start + SILENCE_S, 3),
                     "gold": "", "dur": SILENCE_S, "kind": "silence"}
                make_clip(u)
                probes.append(u)
                break
            cursor = max(cursor, e)
    return probes


def main():
    CLIPS.mkdir(parents=True, exist_ok=True)
    kept, excluded = [], {}
    for u in utterances():
        reason = classify(u)
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        u["gold"] = strip_markup(u.pop("raw_text"))
        u["dur"] = round(u["end"] - u["start"], 3)
        kept.append(u)
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(make_clip, kept))
    with open(HERE / "clips.jsonl", "w") as f:
        for u in kept:
            f.write(json.dumps(u, ensure_ascii=False) + "\n")

    # pilot: whole consultations (both channels) in a seeded order until 30 min of clip audio
    consults = sorted({u["consultation"] for u in kept})
    random.Random(PILOT_SEED).shuffle(consults)
    pilot, total = [], 0.0
    for c in consults:
        if total >= PILOT_TARGET_S:
            break
        pilot.append(c)
        total += sum(u["dur"] for u in kept if u["consultation"] == c)
    (HERE / "pilot.txt").write_text("\n".join(pilot) + "\n")
    silence = silence_probes()
    with open(HERE / "silence.jsonl", "w") as f:
        for s in silence:
            f.write(json.dumps(s) + "\n")
    stats = {
        "silence_probes": len(silence),
        "kept_clips": len(kept),
        "kept_hours": round(sum(u["dur"] for u in kept) / 3600, 3),
        "excluded": excluded,
        "pilot_consultations": pilot,
        "pilot_clips": sum(u["consultation"] in pilot for u in kept),
        "pilot_minutes": round(total / 60, 2),
    }
    (HERE / "prep_stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()

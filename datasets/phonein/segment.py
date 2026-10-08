"""Cut each phone-in recording into one clip per script line.
Boundary engine: faster-whisper small.en (local, CPU). It is NOT a scored engine; it only places cut
points. Its words are aligned (difflib) to the script with spoken line IDs, then each clip runs from the
end of a line's spoken ID to the start of the next line's ID. Clips whose gold words align poorly are
flagged in script.txt comments for a human listen.
Usage: python3 segment.py   (system python with faster_whisper)"""
import re, json, difflib, subprocess, pathlib
from faster_whisper import WhisperModel
ROOT = pathlib.Path(__file__).resolve().parents[2]
RAW = ROOT / "datasets/phonein/raw"
OUT = ROOT / "data/phonein"
SCRIPT = pathlib.Path(__file__).resolve().parent / "phonein-script.md"
READERS = {"spk1-iphone": "full-bbdd5424-c8de-4f58-9da4-5e3ed6f2535e.wav", "spk2": "full-reader2.wav",
           "spk3-android": "full-reader3.wav", "spk4": "full-reader4.wav", "spk5-speakerphone": "full-reader5-speaker.wav"}
HOLD = {("spk4", "N06"), ("spk5-speakerphone", "N05"), ("spk5-speakerphone", "N06")}  # need human listen
NUM = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty twentyone twentytwo twentythree twentyfour twentyfive twentysix twentyseven twentyeight twentynine thirty".split()
LET = {"and": "n", "an": "n", "en": "n", "in": "n", "em": "m", "um": "m", "es": "s", "ess": "s", "as": "s"}
def norm_tokens(text):
    t = text.lower().replace("-", " ")
    t = re.sub(r"\b([nsm])\s?0?(\d{1,2})\b", lambda m: (f"{m.group(1)} {NUM[int(m.group(2))]}" if int(m.group(2)) < len(NUM) else m.group(0)), t)
    t = re.sub(r"\d", lambda m: " " + NUM[int(m.group())] + " ", t)
    toks = re.findall(r"[a-z']+", t)
    return [LET.get(x, x) for x in toks if x != "zero" and x != "oh"]
def lines():
    out = []
    for l in SCRIPT.read_text().splitlines():
        m = re.match(r"^- ([NSM])(\d{2})\. (.*)$", l)
        if m: out.append((f"{m.group(1)}{m.group(2)}", m.group(3), [m.group(1).lower(), NUM[int(m.group(2))].replace(" ", "")]))
    return out
L = lines(); assert len(L) == 75, len(L)
model = WhisperModel("small.en", device="cpu", compute_type="int8")
report = {}
for spk, fname in READERS.items():
    src = RAW / fname; tmp = f"/tmp/seg_{spk}.wav"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-af", "pan=mono|c0=c0", "-ar", "16000", tmp], check=True)
    cache = pathlib.Path(f"/tmp/seg_{spk}.words.json")
    if cache.exists(): words = json.loads(cache.read_text())
    else:
        segs, _ = model.transcribe(tmp, word_timestamps=True, vad_filter=False, language="en")
        words = [(w.word, w.start, w.end) for s in segs for w in s.words]; cache.write_text(json.dumps(words))
    W = [(tok, a, b) for (wd, a, b) in words for tok in norm_tokens(wd)]
    G, owner = [], []  # gold tokens, (line idx, is_id)
    for i, (_, text, idt) in enumerate(L):
        for t in idt: G.append(t); owner.append((i, True))
        for t in norm_tokens(text): G.append(t); owner.append((i, False))
    sm = difflib.SequenceMatcher(a=G, b=[w[0] for w in W], autojunk=False)
    g2w = {}
    for a, b, n in sm.get_matching_blocks():
        for k in range(n): g2w[a + k] = b + k
    info = []
    for i in range(75):
        idx = [g for g in range(len(G)) if owner[g][0] == i]
        ids = [g for g in idx if owner[g][1] and g in g2w]; cont = [g for g in idx if not owner[g][1]]
        mc = [g for g in cont if g in g2w]
        start = W[g2w[ids[-1]]][2] + 0.05 if ids else (W[g2w[mc[0]]][1] - 0.4 if mc else None)
        info.append({"start": start, "id_hit": bool(ids), "cov": len(mc) / max(1, len(cont)),
                     "first_id_t": W[g2w[[g for g in idx if owner[g][1] and g in g2w][0]]][1] if ids else None})
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(src)], capture_output=True, text=True).stdout)
    pdir = OUT / spk; pdir.mkdir(parents=True, exist_ok=True)
    rows = ["# boundary_engine: faster-whisper small.en (local, not scored); alignment via difflib to spoken line IDs",
            f"# source: datasets/phonein/raw/{fname} channel 0"]
    flagged = []
    for i, (lid, text, _) in enumerate(L):
        s = info[i]["start"]
        nxt = next((info[j] for j in range(i + 1, 75) if info[j]["start"] is not None), None)
        e = (nxt["first_id_t"] - 0.05 if nxt and nxt["first_id_t"] else (nxt["start"] - 0.3 if nxt else dur))
        ntok = len(norm_tokens(text)); exp = 1.0 + 0.5 * ntok
        nxt_id = bool(nxt and nxt["first_id_t"])
        bad = (s is None or e - s < 0.3 or not info[i]["id_hit"] or not nxt_id and i < 74
               or (ntok >= 4 and info[i]["cov"] < 0.3) or (s is not None and e - s > 3 * exp + 2) or (spk, lid) in HOLD)
        if s is None or e - s < 0.3: flagged.append((lid, "unaligned" if s is None else f"bad span {s:.1f}-{e:.1f}")); rows.append(f"# SKIP {lid} unaligned"); continue
        stem = lid
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{max(0,s):.3f}", "-to", f"{e:.3f}", "-i", str(src), "-af", "pan=mono|c0=c0", str(pdir / f"{stem}.wav")], check=True)
        if bad:
            flagged.append((lid, f"cov={info[i]['cov']:.2f} len={e-s:.1f}s hold={(spk,lid) in HOLD}")); rows.append(f"# HOLD {stem}\ten\t{text}")
        else:
            rows.append(f"{stem}\ten\t{text}")
    (pdir / "script.txt").write_text("\n".join(rows) + "\n")
    report[spk] = {"clips_scored": sum(1 for r in rows if not r.startswith("#")), "flagged": flagged}
    print(spk, report[spk]["clips_scored"], "scored;", len(flagged), "held:", flagged[:8], flush=True)
json.dump(report, open(OUT / "segment_report.json", "w"), indent=1)

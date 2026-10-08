"""Phone-in recorded packs (Telnyx PSTN recordings, recorded by a separate agent).

Expected layout, one folder per pack under data/phonein/<pack>/:
  *.wav        one recording per script line (any sample rate; real phone legs are 8 kHz)
  script.txt   ground truth, one line per clip: "<wav filename stem>\t<lang>\t<exact read text>"
               lang is optional (default en); lines starting with # are ignored.
A pack may add silence probes by listing a stem with empty text: "<stem>\t<lang>\t".

prep() converts each wav once to the benchmark codec (8 kHz G.711 mu-law, plus PCM decoded
from that mu-law), exactly like the other datasets. Real PSTN recordings are already phone
audio; the mu-law pass keeps every dataset on one code path (and is lossless on mu-law input).
Run:  python -m datasets.phonein.loader <pack>
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = ROOT / "data" / "phonein"


def _script(pack):
    rows = []
    for line in (BASE / pack / "script.txt").read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        stem = parts[0].strip()
        lang = (parts[1].strip() if len(parts) > 2 else "en") or "en"
        text = parts[-1].strip() if len(parts) > 1 else ""
        rows.append((stem, lang, text))
    return rows


def prep(pack):
    out = BASE / pack / "clips"
    out.mkdir(exist_ok=True)
    ff = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y"]
    for stem, _, _ in _script(pack):
        src = BASE / pack / f"{stem}.wav"
        if not src.exists():
            raise SystemExit(f"missing {src}")
        mu = out / f"{stem}.ulaw.wav"
        subprocess.run(ff + ["-i", str(src), "-ac", "1", "-ar", "8000", "-c:a", "pcm_mulaw", str(mu)], check=True)
        subprocess.run(ff + ["-i", str(mu), "-c:a", "pcm_s16le", str(out / f"{stem}.pcm8k.wav")], check=True)
        subprocess.run(ff + ["-i", str(mu), "-c:a", "copy", "-f", "mulaw", str(out / f"{stem}.ulaw")], check=True)


def load(subset):
    """subset = pack folder name, or 'all' for every pack under data/phonein/."""
    import soundfile as sf
    packs = sorted(p.name for p in BASE.iterdir() if (p / "script.txt").exists()) if subset == "all" else [subset]
    clips = []
    for pack in packs:
        for stem, lang, text in _script(pack):
            pcm = BASE / pack / "clips" / f"{stem}.pcm8k.wav"
            if not pcm.exists():
                raise SystemExit(f"run prep first: python -m datasets.phonein.loader {pack}")
            info = sf.info(str(pcm))
            clips.append({"id": f"{pack}__{stem}", "lang": lang, "gold": text, "group": pack,
                          "kind": "speech" if text else "silence", "dur": round(info.frames / info.samplerate, 3),
                          "speaker": pack, "pcm8k": pcm, "ulaw": pcm.with_name(f"{stem}.ulaw")})
    return clips


TERMS = pathlib.Path(__file__).resolve().parent / "terms.json"  # clinic-style vocabulary for the keyterms pass

if __name__ == "__main__":
    prep(sys.argv[1])
    print(f"prepped {len(load(sys.argv[1]))} clips")

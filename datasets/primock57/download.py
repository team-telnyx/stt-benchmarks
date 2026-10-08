"""Download PriMock57 audio (Git LFS media URLs) and TextGrid transcripts.

PriMock57, Babylon Health, CC-BY 4.0: https://github.com/babylonhealth/primock57
Raw files land in data/primock57/raw/ (gitignored). Re-running skips files already present.
"""
import json
import pathlib
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

REPO = "babylonhealth/primock57"
REF = "main"
ROOT = pathlib.Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "primock57" / "raw"


def listing(folder):
    url = f"https://api.github.com/repos/{REPO}/contents/{folder}?ref={REF}"
    with urllib.request.urlopen(url, timeout=60) as r:
        return [x["name"] for x in json.load(r) if x["type"] == "file"]


def fetch(url, dest):
    if dest.exists() and dest.stat().st_size > 1000:
        return dest.name, "cached"
    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.rename(dest)
    return dest.name, "ok"


def main():
    (RAW / "audio").mkdir(parents=True, exist_ok=True)
    (RAW / "transcripts").mkdir(parents=True, exist_ok=True)
    jobs = []
    for name in listing("transcripts"):
        if name.endswith(".TextGrid"):
            jobs.append((f"https://raw.githubusercontent.com/{REPO}/{REF}/transcripts/{name}", RAW / "transcripts" / name))
    for name in listing("audio"):
        if name.endswith(".wav"):
            # audio is stored in Git LFS; media.githubusercontent.com serves the real bytes
            jobs.append((f"https://media.githubusercontent.com/media/{REPO}/{REF}/audio/{name}", RAW / "audio" / name))
    jobs.append((f"https://raw.githubusercontent.com/{REPO}/{REF}/LICENSE.md", RAW / "LICENSE.md"))
    with ThreadPoolExecutor(8) as ex:
        for name, status in ex.map(lambda j: fetch(*j), jobs):
            print(status, name)
    n_wav = len(list((RAW / "audio").glob("*.wav")))
    n_tg = len(list((RAW / "transcripts").glob("*.TextGrid")))
    print(f"wav={n_wav} textgrid={n_tg}")
    if n_wav != 114 or n_tg != 114:
        sys.exit("expected 114 wav and 114 TextGrid files")


if __name__ == "__main__":
    main()

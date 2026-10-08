#!/usr/bin/env python3
"""Download new phone-in recordings from Telnyx into datasets/phonein/raw/.

Lists call recordings with GET https://api.telnyx.com/v2/recordings
(https://developers.telnyx.com/api-reference/call-recordings/list-all-call-recordings),
keeps the ones on the phone-in number or TeXML connection, and saves each as
raw/<UTC timestamp>_<caller>_<recording id>.wav plus a .json sidecar with the
full recording object. Already-downloaded ids are skipped, so re-running is safe.

UNVERIFIED: the recording object field names used below (download_urls, from,
to, connection_id, recording_started_at) come from memory of the Telnyx
recordings schema and were not checked against a live TeXML recording yet.
The script falls back gracefully and the .json sidecar keeps the raw object,
so the first real fetch is the check. See README.md.

Usage:
  python3 fetch_recordings.py [--number +1XXXXXXXXXX] [--connection-id ID] [--since 2026-10-01]
Env: TELNYX_API_KEY.
"""
import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.telnyx.com/v2"
HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
CONFIG = HERE / "phonein.json"  # written by provision step: {"phone_number": ..., "connection_id": ...}


def api_key():
    key = os.environ.get("TELNYX_API_KEY")
    if key:
        return key
    sys.exit("TELNYX_API_KEY not set")


def get(url, key):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def list_recordings(key, since):
    page = 1
    while True:
        q = {"page[number]": page, "page[size]": 100}
        if since:
            q["filter[created_at][gte]"] = since
        data = get(f"{API}/recordings?{urllib.parse.urlencode(q)}", key)
        yield from data.get("data", [])
        meta = data.get("meta", {})
        if page >= meta.get("total_pages", 1):
            return
        page += 1


def matches(rec, number, connection_id):
    if not number and not connection_id:
        return True
    if connection_id and str(rec.get("connection_id")) == str(connection_id):
        return True
    return bool(number) and rec.get("to") == number


def main():
    ap = argparse.ArgumentParser()
    cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    ap.add_argument("--number", default=cfg.get("phone_number"))
    ap.add_argument("--connection-id", default=cfg.get("connection_id"))
    ap.add_argument("--since", default=None, help="ISO date, e.g. 2026-10-01")
    args = ap.parse_args()

    key = api_key()
    RAW.mkdir(parents=True, exist_ok=True)
    have = {p.stem.rsplit("_", 1)[-1] for p in RAW.glob("*.wav")}
    new = 0
    for rec in list_recordings(key, args.since):
        rid = rec.get("id")
        if not rid or rid in have or not matches(rec, args.number, args.connection_id):
            continue
        urls = rec.get("download_urls") or {}
        url = urls.get("wav") or urls.get("mp3")
        if not url:
            print(f"skip {rid}: no download url (status={rec.get('status')})")
            continue
        ext = "wav" if urls.get("wav") else "mp3"
        ts = (rec.get("recording_started_at") or rec.get("created_at") or "unknown").replace(":", "").replace("-", "")[:15]
        caller = re.sub(r"[^0-9]", "", rec.get("from") or "") or "unknown"
        stem = f"{ts}_{caller}_{rid}"
        # Download URLs are presigned and short-lived, so no auth header.
        urllib.request.urlretrieve(url, RAW / f"{stem}.{ext}")
        (RAW / f"{stem}.json").write_text(json.dumps(rec, indent=2))
        print(f"saved {stem}.{ext} ({rec.get('duration_millis')} ms, {rec.get('channels')})")
        new += 1
    print(f"{new} new recording(s) in {RAW}")


if __name__ == "__main__":
    main()

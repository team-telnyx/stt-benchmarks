"""Batch lane adapters: one file in, one transcript out.

Every batch engine receives the same file: 16-bit PCM 8 kHz WAV decoded from the clip's mu-law.
Defaults everywhere except the language hint, which every engine that accepts one gets
(the language is known in each track, as it would be for a configured deployment).
"""
import json
import threading
import time

import requests

from engines.common import key

EL_URL = "https://api.elevenlabs.io/v1/speech-to-text"
TX_URL = "https://api.telnyx.com/v2/ai/audio/transcriptions"
EL_LANG = {"en": "eng", "de": "deu", "fr": "fra", "tr": "tur"}


# One account-wide limit per vendor: every engine on that vendor shares these slots.
_SLOTS = {"telnyx": threading.BoundedSemaphore(4), "elevenlabs": threading.BoundedSemaphore(4), "omi": threading.BoundedSemaphore(2)}
# Telnyx /v2/ai/audio/transcriptions answers 429 above 1 request/s per account
# (response headers on 2026-10-01: ratelimit-limit: 1, 1;w=1). Space request starts to match.
_MIN_INTERVAL = {"telnyx": 1.05, "elevenlabs": 0.0, "omi": 0.0}
_pace_lock = threading.Lock()
_last_start = {"telnyx": 0.0, "elevenlabs": 0.0, "omi": 0.0}


def _pace(vendor):
    with _pace_lock:
        wait = _last_start[vendor] + _MIN_INTERVAL[vendor] - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_start[vendor] = time.monotonic()
MAX_429_RETRIES = 8
MAX_TRANSPORT_RETRIES = 3
MAX_DNS_RETRIES = 40  # ~10 min of local resolver outage


def _post(vendor, url, headers, data, path, timeout=120):
    """429 (account rate limit) and pre-response transport errors are retried and counted;
    any HTTP status other than 429 is final.
    wall_s is the successful attempt only."""
    retries = transport = 0
    while True:
        try:
            with _SLOTS[vendor], open(path, "rb") as f:
                _pace(vendor)
                t0 = time.time()
                r = requests.post(url, headers=headers, data=data, files={"file": (path.name, f, "audio/wav")}, timeout=timeout)
                wall = time.time() - t0
        except requests.exceptions.ConnectionError as e:
            # failure before any HTTP response: TLS (SSLV3_ALERT_BAD_RECORD_MAC) or local DNS
            # (NameResolutionError for api.telnyx.com, seen in multi-minute bursts on 2026-10-01)
            transport += 1
            dns = "NameResolution" in str(e) or "nodename nor servname" in str(e)
            if transport > (MAX_DNS_RETRIES if dns else MAX_TRANSPORT_RETRIES):
                raise
            time.sleep(15 if dns else 2 * transport)
            continue
        if r.status_code != 429 or retries >= MAX_429_RETRIES:
            break
        retries += 1
        time.sleep(float(r.headers.get("Retry-After") or min(2 ** retries, 30)))
    try:
        body = r.json()
    except ValueError:
        body = {"_non_json": r.text[:2000]}
    return r.status_code, body, wall, {"429": retries, "transport": transport}


def elevenlabs(model, path, lang, keyterms=None):
    data = [("model_id", model)]
    if lang:
        data.append(("language_code", EL_LANG.get(lang, lang)))
    if keyterms:
        # one form field per term; a single JSON string is read as one keyword and rejected (400, "< 50 characters")
        data += [("keyterms", k) for k in keyterms]
    status, body, wall, retries = _post("elevenlabs", EL_URL, {"xi-api-key": key("ELEVENLABS_API_KEY")}, data, path)
    ok = status == 200 and isinstance(body.get("text"), str)
    return {"ok": ok, "status": status, "error": None if ok else f"http {status}", "text": body.get("text") if ok else None,
            "detected_language": body.get("language_code"), "wall_s": round(wall, 3), "retries": retries, "raw": body}


def telnyx(model, path, lang, keyterms=None):
    data = {"model": model}
    if lang:
        data["language"] = lang
    elif model == "deepgram/nova-3":
        data["language"] = "multi"  # Deepgram defaults to en when omitted; multi is its auto mode
    if keyterms and model.startswith("deepgram/"):
        data["model_config"] = json.dumps({"keyterm": keyterms})
    status, body, wall, retries = _post("telnyx", TX_URL, {"Authorization": "Bearer " + key("TELNYX_API_KEY")}, data, path)
    ok = status == 200 and isinstance(body.get("text"), str)
    return {"ok": ok, "status": status, "error": None if ok else f"http {status}", "text": body.get("text") if ok else None,
            "detected_language": body.get("language"), "wall_s": round(wall, 3), "retries": retries, "raw": body}


OMI_URL = "https://api.omi.health/v1/audio/transcriptions"


def omi(model, path, lang, keyterms=None):
    """Omi direct API (https://console.omi.health/openapi.yaml). Sync limit 60 s; defaults only."""
    data = {"model": model, "response_format": "json"}
    if lang:
        data["language"] = lang
    status, body, wall, retries = _post("omi", OMI_URL, {"Authorization": "Bearer " + key("OMI_API_KEY")}, data, path)
    ok = status == 200 and isinstance(body.get("text"), str)
    return {"ok": ok, "status": status, "error": None if ok else f"http {status}: {str(body)[:200]}", "text": body.get("text") if ok else None,
            "detected_language": body.get("language"), "wall_s": round(wall, 3), "retries": retries,
            "raw": body, "model_build": body.get("model_build")}

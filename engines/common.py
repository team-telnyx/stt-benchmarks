"""Shared helpers: key loading (never printed), ElevenLabs spend ledger, clip audio access."""
import json
import os
import pathlib
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEND_DIR = ROOT / "spend"

# Prices recorded 2026-10-01. ElevenLabs: https://elevenlabs.io/pricing/api
# Telnyx: https://telnyx.com/pricing/speech-to-text (per minute, pay as you go)
PRICE_PER_HOUR = {
    "elevenlabs/scribe_v2": 0.22,
    "elevenlabs/scribe_v2_medical": 0.22,
    "elevenlabs/scribe_v2_realtime": 0.39,
    "telnyx/deepgram": 0.005 * 60,
    "telnyx/assemblyai": 0.005 * 60,
    "telnyx/speechmatics": 0.0035 * 60,
    "telnyx/soniox": 0.002 * 60,
    "telnyx/parakeet": 0.0015 * 60,
    "telnyx/whisper": 0.015 * 60,
    "telnyx/xai": 0.0033 * 60,
    "telnyx/azure": 0.027 * 60,
    "omi/batch": 0.29,
    "omi/live": 0.45,
}
EL_CAP_USD = 20.0
EL_SAFETY_USD = 1.0  # stop sending once projected spend would pass cap minus this margin


def key(name):
    v = os.environ.get(name)
    if v:
        return v
    raise SystemExit(f"{name} not set")


class Ledger:
    """Append-only spend ledger shared by every run. ElevenLabs sends are refused past the cap."""

    _lock = threading.Lock()

    def __init__(self, vendor):
        SPEND_DIR.mkdir(exist_ok=True)
        self.path = SPEND_DIR / f"{vendor}.jsonl"
        self.vendor = vendor

    def total(self):
        if not self.path.exists():
            return 0.0
        return sum(json.loads(l)["usd"] for l in open(self.path))

    def charge(self, engine, seconds, run_id, clip_id):
        usd = seconds / 3600 * PRICE_PER_HOUR[engine]
        with self._lock:
            if self.vendor == "elevenlabs" and self.total() + usd > EL_CAP_USD - EL_SAFETY_USD:
                raise SpendCapError(f"ElevenLabs cap: spent {self.total():.3f}, next {usd:.4f}")
            with open(self.path, "a") as f:
                f.write(json.dumps({"ts": time.time(), "engine": engine, "seconds": round(seconds, 3),
                                    "usd": usd, "run": run_id, "clip": clip_id}) + "\n")
        return usd


class SpendCapError(RuntimeError):
    pass


def wav_seconds(path):
    import soundfile as sf
    info = sf.info(str(path))
    return info.frames / info.samplerate

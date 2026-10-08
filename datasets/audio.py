"""Shared audio chain: telephone-level gate, then 8 kHz G.711 mu-law, plus PCM decoded from it.

Level gate (added 2026-10-01 after FLEURS English measured a median active speech level of
-57 dBFS, far below anything a phone leg carries): if a clip's active speech level is below
QUIET_BELOW_DBFS, apply one gain so it sits at TARGET_DBFS (ITU-T P.56 nominal telephone level,
-26 dBov), capped so the peak stays at or below -1 dBFS. Louder clips are untouched: phone AGC
lifts quiet talkers, and loud speech is not a realism problem.
Active level = power mean of 20 ms frames within 20 dB of the loudest frame.
"""
import subprocess

import numpy as np
import soundfile as sf

QUIET_BELOW_DBFS = -36.0
TARGET_DBFS = -26.0
PEAK_CAP_DBFS = -1.0


def active_level_db(x, sr):
    n = int(sr * 0.02)
    f = x[: len(x) // n * n].reshape(-1, n)
    if not len(f):
        return None
    db = 20 * np.log10(np.sqrt((f ** 2).mean(axis=1)) + 1e-12)
    a = db[db > db.max() - 20]
    return float(10 * np.log10(np.mean(10 ** (a / 10))))


def gate_gain_db(src, start=None, end=None):
    info = sf.info(str(src))
    sr = info.samplerate
    x, _ = sf.read(str(src), dtype="float32",
                   start=int(start * sr) if start else 0, stop=int(end * sr) if end else None)
    lvl = active_level_db(x, sr)
    if lvl is None or lvl >= QUIET_BELOW_DBFS:
        return 0.0, lvl
    peak_db = 20 * np.log10(float(np.abs(x).max()) + 1e-12)
    return round(min(TARGET_DBFS - lvl, PEAK_CAP_DBFS - peak_db), 2), lvl


def transcode(src, base, gain_db=0.0, start=None, end=None):
    """Write base.ulaw.wav, base.pcm8k.wav (decoded from the mu-law) and base.ulaw (raw bytes)."""
    ff = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y"]
    cut = (["-ss", str(start), "-to", str(end)] if start is not None else [])
    af = ["-af", f"volume={gain_db}dB"] if gain_db else []
    mu, pcm, raw = (base.with_suffix(s) for s in (".ulaw.wav", ".pcm8k.wav", ".ulaw"))
    subprocess.run(ff + cut + ["-i", str(src)] + af + ["-ac", "1", "-ar", "8000", "-c:a", "pcm_mulaw", str(mu)], check=True)
    subprocess.run(ff + ["-i", str(mu), "-c:a", "pcm_s16le", str(pcm)], check=True)
    subprocess.run(ff + ["-i", str(mu), "-c:a", "copy", "-f", "mulaw", str(raw)], check=True)

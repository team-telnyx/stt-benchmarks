"""Energy VAD for latency anchoring: where speech starts and ends inside a clip.

20 ms frames on the 8 kHz PCM; a frame is speech if its RMS is within 35 dB of the clip's
loudest frame and above -50 dBFS. Returns (onset_s, end_s). Used only to anchor latency to
speech rather than to the clip's leading or trailing silence; same rule for every engine.
"""
import functools

import numpy as np
import soundfile as sf

FRAME_S = 0.02


@functools.lru_cache(maxsize=None)
def speech_bounds(pcm_path):
    x, sr = sf.read(str(pcm_path), dtype="float32")
    n = int(sr * FRAME_S)
    frames = x[: len(x) // n * n].reshape(-1, n)
    if not len(frames):
        return 0.0, len(x) / sr
    db = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-9)
    thr = max(db.max() - 35, -50)
    idx = np.flatnonzero(db > thr)
    if not len(idx):
        return 0.0, len(x) / sr
    return idx[0] * FRAME_S, (idx[-1] + 1) * FRAME_S


@functools.lru_cache(maxsize=None)
def clip_seconds(pcm_path):
    info = sf.info(str(pcm_path))
    return info.frames / info.samplerate

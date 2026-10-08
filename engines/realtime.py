"""Realtime lane adapters: stream a clip at real-time pace in 100 ms chunks and time the results.

Audio: ElevenLabs gets the clip's raw mu-law bytes (audio_format=ulaw_8000). Telnyx engines get
16-bit PCM at 8 kHz decoded from the same mu-law samples (input_format=linear16, the only
format every Telnyx engine accepts). Same signal, two encodings of it.

End of speech, per engine (recorded as `flush` in every result):
  commit      ElevenLabs: the last chunk carries commit=true (manual commit strategy).
  closestream Telnyx Deepgram / Speechmatics / Soniox: {"type":"CloseStream"} right after the
              last chunk; the server flushes and closes.
  silence     Engines with no flush control (Parakeet, Omi, AssemblyAI) and Deepgram Flux
              (CloseStream drops Flux's unfinished turn: 87.5% vs 13.9% WER on a 6-clip check,
              2026-10-01): keep streaming digital silence in real time so endpointing / EndOfTurn
              can fire. Stop once a final has arrived after end of speech and 1.5 s pass with no
              message, or after 12 s (Parakeet finals arrive up to ~8 s after speech; 6 s lost some).
AssemblyAI is pre-warmed with 1 s of silence before the clip (excluded from latency).

Latency (seconds, monotonic clock):
  ttfp      first speech chunk sent -> first message with non-empty text (partial or final;
            `first_kind` records which, so final-only engines are not misread as partials)
  final_s   last speech chunk sent -> arrival of the last non-empty final transcript
Text = all non-empty finals in arrival order, joined by spaces.
"""
import asyncio
import base64
import json
import time
import urllib.parse

import websockets

from engines.common import key

CHUNK_S = 0.1
SILENCE_TAIL_MAX_S = 12.0
QUIET_S = 1.5
CLOSE_QUIET_S = 3.0
PREWARM_S = 1.0
RECV_TIMEOUT_S = 15.0

EL_WS = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"
TX_WS = "wss://api.telnyx.com/v2/speech-to-text/transcription"


def chunks(data, bytes_per_chunk):
    return [data[i:i + bytes_per_chunk] for i in range(0, len(data), bytes_per_chunk)]


class Recorder:
    def __init__(self):
        self.msgs = []  # (t, parsed)

    def add(self, raw):
        t = time.monotonic()
        try:
            m = json.loads(raw)
        except (TypeError, ValueError):
            m = {"_non_json": str(raw)[:500]}
        self.msgs.append((t, m))
        return t, m


def _summarize(rec, t_first, t_last, finals, partial_kinds, error, flush, extra):
    first = next(((t, k) for t, k, txt in partial_kinds if txt.strip()), None)
    fin = [(t, txt) for t, txt in finals if txt.strip()]
    return {
        "ok": error is None,
        "error": error,
        "flush": flush,
        "text": " ".join(txt.strip() for _, txt in fin) if error is None else None,
        "ttfp": round(first[0] - t_first, 3) if first and t_first else None,
        "first_kind": first[1] if first else None,
        "final_s": round(fin[-1][0] - t_last, 3) if fin and t_last else None,
        "n_finals": len(fin),
        "raw": [{"t": round(t - (t_first or t), 3), "m": m} for t, m in rec.msgs],
        **extra,
    }


async def _pace(t0, i):
    delay = t0 + i * CHUNK_S - time.monotonic()
    if delay > 0:
        await asyncio.sleep(delay)


async def elevenlabs(ulaw_bytes, lang, model="scribe_v2_realtime", keyterms=None):
    q = {"model_id": model, "audio_format": "ulaw_8000", "commit_strategy": "manual"}
    if lang:
        q["language_code"] = lang
    if keyterms:
        q["keyterms"] = [k[:20] for k in keyterms[:50]]  # realtime limit: 50 keyterms, 20 chars each (ElevenLabs STT docs)
    url = EL_WS + "?" + urllib.parse.urlencode(q, doseq=True)
    rec, finals, seen = Recorder(), [], []
    t_first = t_last = None
    error = None
    tc = time.monotonic()
    try:
        async with websockets.connect(url, additional_headers={"xi-api-key": key("ELEVENLABS_API_KEY")},
                                      open_timeout=15, close_timeout=2, max_size=None) as ws:
            rec.add(await asyncio.wait_for(ws.recv(), RECV_TIMEOUT_S))  # session_started
            connect_s = time.monotonic() - tc
            done = asyncio.Event()

            async def reader():
                nonlocal error
                async for raw in ws:
                    t, m = rec.add(raw)
                    mt = m.get("message_type", "")
                    txt = m.get("text") or ""
                    if mt == "partial_transcript":
                        seen.append((t, "partial", txt))
                    elif mt.startswith("committed_transcript"):
                        seen.append((t, "final", txt))
                        if mt == "committed_transcript":
                            finals.append((t, txt))
                            done.set()
                    elif "error" in mt:
                        error = f"{mt}: {m.get('error') or m.get('message')}"
                        done.set()

            rt = asyncio.create_task(reader())
            parts = chunks(ulaw_bytes, int(8000 * CHUNK_S))
            t0 = time.monotonic()
            for i, c in enumerate(parts):
                await _pace(t0, i)
                last = i == len(parts) - 1
                await ws.send(json.dumps({"message_type": "input_audio_chunk",
                                          "audio_base_64": base64.b64encode(c).decode(),
                                          "commit": last, "sample_rate": 8000}))
                now = time.monotonic()
                t_first = t_first or now
                if last:
                    t_last = now
            try:
                await asyncio.wait_for(done.wait(), RECV_TIMEOUT_S)
            except asyncio.TimeoutError:
                error = error or "timeout waiting for committed_transcript"
            rt.cancel()
    except Exception as e:  # connection failures are results, not drops
        error = f"{type(e).__name__}: {e}"
        connect_s = None
    return _summarize(rec, t_first, t_last, finals, seen, error, "commit", {"connect_s": round(connect_s, 3) if connect_s else None})


# Telnyx engine -> (transcription_engine, flush mode, supports interim_results)
TX_ENGINES = {
    "Deepgram": ("closestream", True),
    "Speechmatics": ("closestream", True),
    "Soniox": ("closestream", True),
    "Parakeet": ("silence", False),
    "AssemblyAI": ("silence", False),
    "xAI": ("silence", False),
    "Azure": ("closestream", True),  # silence tail made Azure emit "I. I. I." on digital silence (smoke test 2026-10-01)
}


NEEDS_16K = {"speechmatics/linden-1": 16000}  # API: "Valid rates: 16000"


def upsample2x(pcm8k):
    """8 kHz -> 16 kHz PCM16 by linear interpolation (no new information; same phone signal)."""
    import numpy as np
    x = np.frombuffer(pcm8k, dtype="<i2").astype(np.float32)
    return np.interp(np.arange(len(x) * 2) / 2.0, np.arange(len(x)), x).astype("<i2").tobytes() if len(x) else b""


AZURE_LOCALE = {"en": "en-US", "de": "de-DE", "fr": "fr-FR", "tr": "tr-TR"}


MODEL_FLUSH = {"deepgram/flux": "silence", "deepgram/flux-multi": "silence"}


async def telnyx(pcm_bytes, lang, engine, model, keyterms=None, prewarm=None):
    flush, interim = TX_ENGINES[engine]
    flush = MODEL_FLUSH.get(model, flush)
    rate = NEEDS_16K.get(model, 8000)
    if rate == 16000:
        pcm_bytes = upsample2x(pcm_bytes)
    q = {"transcription_engine": engine, "model": model, "input_format": "linear16", "sample_rate": str(rate)}
    if lang:
        q["language"] = AZURE_LOCALE.get(lang, lang) if engine == "Azure" else lang
    elif engine == "Deepgram":
        q["language"] = "multi"  # Telnyx defaults to en-US when omitted; multi is the documented auto mode
    if interim:
        q["interim_results"] = "true"
    if keyterms and engine == "Deepgram":
        q["keyterm"] = ",".join(keyterms)
    url = TX_WS + "?" + urllib.parse.urlencode(q)
    rec, finals, seen = Recorder(), [], []
    t_first = t_last = None
    error = None
    closed = asyncio.Event()
    last_msg = [0.0]
    closed_at = [None]
    tc = time.monotonic()
    connect_s = None
    try:
        async with websockets.connect(url, additional_headers={"Authorization": "Bearer " + key("TELNYX_API_KEY")},
                                      open_timeout=15, close_timeout=2, max_size=None) as ws:
            connect_s = time.monotonic() - tc

            async def reader():
                nonlocal error
                try:
                    async for raw in ws:
                        t, m = rec.add(raw)
                        if (m.get("transcript") or "").strip():
                            last_msg[0] = t  # quiet is judged on text-bearing messages (Flux streams empty Update events)
                        if m.get("errors"):
                            error = "errors: " + json.dumps(m["errors"])[:400]
                            break
                        txt = m.get("transcript") or ""
                        if m.get("is_final"):
                            seen.append((t, "final", txt))
                            finals.append((t, txt))
                        elif "transcript" in m:
                            seen.append((t, "partial", txt))
                except websockets.ConnectionClosed:
                    pass
                closed_at[0] = time.monotonic()
                closed.set()

            rt = asyncio.create_task(reader())
            step = int(rate * CHUNK_S) * 2
            silence = b"\x00" * step
            t0 = time.monotonic()
            i = 0
            if prewarm is None:
                prewarm = PREWARM_S if engine == "AssemblyAI" else 0.0
            if prewarm:
                for _ in range(int(round(prewarm / CHUNK_S))):
                    await _pace(t0, i)
                    await ws.send(silence)
                    i += 1
            for c in chunks(pcm_bytes, step):
                await _pace(t0, i)
                if closed.is_set():
                    break
                await ws.send(c)
                now = time.monotonic()
                t_first = t_first or now
                t_last = now
                i += 1
            if not closed.is_set():
                if flush == "closestream":
                    await ws.send(json.dumps({"type": "CloseStream"}))
                    # done when the server closes, or a final has arrived after end of speech and
                    # CLOSE_QUIET_S pass with no message (Soniox holds the socket ~15 s after its final)
                    t_close = time.monotonic()
                    while not closed.is_set():
                        now = time.monotonic()
                        got_final = any(t > t_last and txt.strip() for t, txt in finals)
                        if got_final and now - last_msg[0] > CLOSE_QUIET_S:
                            break
                        if now - t_close > RECV_TIMEOUT_S:
                            if not got_final:
                                error = error or "timeout waiting for close after CloseStream"
                            break
                        await asyncio.sleep(0.05)
                else:
                    while time.monotonic() - t_last < SILENCE_TAIL_MAX_S and not closed.is_set():
                        got_final = any(t > t_last and txt.strip() for t, txt in finals)
                        # engines that stream partials (Flux) show pending speech as partials, so a
                        # last text message that is final means nothing is pending; final-only engines
                        # (Parakeet, Omi, AssemblyAI) must deliver a final after end of speech
                        texts = [k for _, k, txt in seen if txt.strip()]
                        settled = interim and texts and texts[-1] == "final" and time.monotonic() - t_last > QUIET_S
                        if (got_final or settled) and time.monotonic() - last_msg[0] > QUIET_S:
                            break
                        await _pace(t0, i)
                        await ws.send(silence)
                        i += 1
            rt.cancel()
    except Exception as e:
        error = error or f"{type(e).__name__}: {e}"
    closed_s = round(closed_at[0] - t_last, 3) if closed_at[0] and t_last else None
    return _summarize(rec, t_first, t_last, finals, seen, error, flush,
                      {"connect_s": round(connect_s, 3) if connect_s else None, "closed_s": closed_s})


OMI_WS = "wss://api.omi.health/v1/stream"


async def omi(pcm8k_bytes, lang, model="omi-medical-1"):
    """Omi direct realtime (https://docs.omi.health/realtime). Needs PCM16 16 kHz: the 8 kHz phone
    signal is upsampled (linear interpolation, no added information). Flush = {"type":"stop"}.
    finals = turn_final events (immutable turn text); ttfp from the first draft partial."""
    import uuid
    up = upsample2x(pcm8k_bytes)
    rec, finals, seen = Recorder(), [], []
    t_first = t_last = None
    error = None
    tc = time.monotonic()
    try:
        async with websockets.connect(OMI_WS, open_timeout=15, close_timeout=2, max_size=None) as ws:
            start = {"type": "start", "api_key": key("OMI_API_KEY"), "session_id": uuid.uuid4().hex, "model": model,
                     "streaming_mode": "realtime", "event_schema": "omi-agent-v1", "audio_format": "pcm_s16le",
                     "sample_rate_hz": 16000, "channels": 1}
            if lang:
                start["language"] = lang
            await ws.send(json.dumps(start))
            while True:  # wait for ready
                t, m = rec.add(await asyncio.wait_for(ws.recv(), RECV_TIMEOUT_S))
                if m.get("type") == "ready":
                    break
                if m.get("type") in ("error",) or "error" in m:
                    raise RuntimeError(str(m)[:300])
            connect_s = time.monotonic() - tc
            done = asyncio.Event()

            async def reader():
                nonlocal error
                async for raw in ws:
                    t, m = rec.add(raw)
                    ty = m.get("type", "")
                    txt = m.get("text") or ""
                    if ty == "partial":
                        seen.append((t, "partial", txt))
                    elif ty == "turn_final":
                        seen.append((t, "final", txt))
                        finals.append((t, txt))
                    elif ty in ("final", "canonical_record"):
                        done.set()
                    elif ty == "error":
                        error = f"error: {m.get('code') or m.get('message')}"
                        done.set()

            rt = asyncio.create_task(reader())
            parts = chunks(up, int(16000 * 2 * CHUNK_S))
            t0 = time.monotonic()
            for i, c in enumerate(parts):
                await _pace(t0, i)
                await ws.send(c)
                now = time.monotonic()
                t_first = t_first or now
                if i == len(parts) - 1:
                    t_last = now
            await ws.send(json.dumps({"type": "stop"}))
            try:
                await asyncio.wait_for(done.wait(), RECV_TIMEOUT_S + 15)
            except asyncio.TimeoutError:
                error = error or "timeout waiting for final"
            rt.cancel()
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        connect_s = None
    return _summarize(rec, t_first, t_last, finals, seen, error, "stop", {"connect_s": round(connect_s, 3) if connect_s else None})

# Method and protocol notes

Technical detail for the tests in this repo: lanes, audio handling, end-of-speech rules, scoring and how to reproduce a run. The plain-language summary is in the [README](../README.md).


A reproducible STT benchmark: Telnyx STT engines vs ElevenLabs Scribe v2 / v2 Medical / v2 Realtime, on 8 kHz mu-law phone audio.
There are two lanes, never mixed. BATCH sends a file and gets a transcript back. REALTIME streams at real-time pace in 100 ms chunks and measures latency.
Ground truth is always a human transcript or a read script. Every engine gets the same audio, the same language hint, and default settings.
Tracks: MEDICAL (PriMock57, CC-BY 4.0), GENERAL (Google FLEURS en/de/fr/tr, CC-BY 4.0, license evidence in datasets/fleurs/prep.py), PHONE-IN (Telnyx PSTN recordings, datasets/phonein/).
Every raw engine response lands in runs/<run-id>/raw/<engine>/<clip>.json. Each run produces scores/, results.csv, summary.json and scorecard.html.
Spend: the ElevenLabs ledger in spend/elevenlabs.jsonl refuses sends past a $20 cap. Telnyx usage is logged in spend/telnyx.jsonl at list per-second price. The spend/ folder is created at run time and is not committed.

## Layout
- `datasets/<name>/` holds download and prep scripts, the committed clip manifests, and `loader.py` (`load(subset)` returns clips). Raw audio goes in `data/` and is gitignored.
- `engines/` has `batch.py` (ElevenLabs and Telnyx REST), `realtime.py` (ElevenLabs and Telnyx WebSocket), `registry.py` (engine list and lanes), and `common.py` (keys, prices, ledger).
- `score/` has `normalize.py`, applied to gold and hypothesis alike, and `metrics.py` (WER with a cluster bootstrap CI, term recall, number recall, hallucination, latency).
- `report/build.py` scores a run and writes the CSV and HTML scorecard.

## Reproduce (medical)
```
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python jiwer websockets requests whisper-normalizer praatio num2words soundfile numpy wordfreq
.venv/bin/python datasets/primock57/download.py      # 1.9 GB from GitHub LFS
.venv/bin/python datasets/primock57/prep.py          # clips, mu-law transcode, pilot list, silence probes
.venv/bin/python datasets/primock57/build_terms.py   # fixed term list (cached Wikidata snapshot)
.venv/bin/python run.py --dataset primock57 --subset pilot --lane batch --medical --run-id <id>
.venv/bin/python run.py --dataset primock57 --subset pilot --lane realtime --medical --run-id <id>
.venv/bin/python report/build.py --run-id <id>
```
Keys come from the environment (`TELNYX_API_KEY`, `ELEVENLABS_API_KEY`, `OMI_API_KEY`). They are never logged.

## Protocol notes (verified 2026-10-01)
- Telnyx REST `/v2/ai/audio/transcriptions` allows 1 request/s per account (`ratelimit-limit: 1, 1;w=1`). The batch adapter paces to 1.05 s and retries 429s, counting each retry.
- Telnyx realtime receives linear16 at 8 kHz, decoded from the mu-law clip. Parakeet and AssemblyAI do not accept mulaw, and linear16 is the only format every engine takes.
- End of speech: ElevenLabs uses commit, Deepgram Nova, Speechmatics and Soniox use CloseStream, and Flux, Parakeet, Omi and AssemblyAI get trailing real-time silence of up to 12 s. AssemblyAI is pre-warmed with 1 s of silence.
- See engines/realtime.py for the latency definitions.

## Data attribution
PriMock57: Papadopoulos Korfiatis, Moramarco, Sarac, Savkov. "PriMock57: A Dataset Of Primary Care Mock Consultations", ACL 2022. https://github.com/babylonhealth/primock57, CC-BY 4.0. Clip manifests in this repo are derived from it.
The term lexicon is built from Wikidata (CC0).

# STT benchmarks

Speech-to-text tests on phone-quality audio: Telnyx STT engines against ElevenLabs Scribe. Run the tests on your own audio, or read what we found when we ran it on ours.

This repo contains:

- **[`run.py`](run.py)** and **[`engines/`](engines)**: the test runner, with one adapter per engine
- **[`score/`](score)**: how each transcript is scored
- **[`datasets/`](datasets)**: prep scripts and clip lists for the three audio sets
- **[`runs/`](runs)**: results from our October 1, 2026 runs, with a scorecard for each
- **[`docs/method.md`](docs/method.md)**: protocol details, for anyone who wants to rerun a number or challenge it

## What we found

Scribe and Telnyx's engines are good at different things, so no single engine wins everything.

- **Telnyx streaming engines return words sooner on live calls.** Median time to first words was 1.0 s for Flux and 1.3 s for Nova-3, against 2.1 s for Scribe v2 Realtime.
- **Most Telnyx engines get one-word replies right more often.** On 147 short replies ("yes", "no", single letters, numbers), Flux got 85% right and Scribe v2 Realtime got 67%. Nine of the 11 Telnyx streaming engines scored higher than Scribe, one tied, and one scored lower.
- **Nova-3 finishes its slowest turns sooner.** For the slowest 1 in 10 turns, the final transcript arrived in 0.93 s on Nova-3 and 1.32 s on Scribe v2 Realtime. Flux went the other way, at 2.36 s.
- **Medical phone calls are close to even.** Nova-3 Medical got 16.4 words wrong per 100 and Scribe v2 Realtime got 17.3, on 90 lines. A gap that small is inside the noise for a sample this size.
- **Scribe is more accurate on consultation audio.** On 5.2 hours of recorded consultations, Scribe v2 got 4.0 wrong words per 100 and the best Telnyx file engine, Parakeet v3, got 5.7. Streamed live, Scribe v2 Realtime got 6.1 and Nova-3 Medical got 8.5.
- **Scribe v2 is more accurate in German, French and Turkish.** It led every Telnyx file engine we tested in all three. Live, Telnyx's preview engine Linden-1 was ahead of Scribe v2 Realtime in French, level in Turkish, and 0.4 points behind in German.
- **No engine is good at spelled names and addresses.** Across every streaming engine, between 36 and 59 words in 100 came back wrong in that set.

## What we tested

Every clip was converted to 8 kHz phone quality before it went to any engine. Every engine got the same audio, the same language setting and default options.

| Audio set | What it is | Size |
|---|---|---|
| Phone calls | Five people on iPhone, Android and speakerphone read a script over a real phone line. The script has names and spelled-out items, one-word replies, and medical calls (refills, drug names, doses, pharmacies). All names, numbers and emails in it are invented. | 339 clips, 28 minutes of speech |
| Consultations | PriMock57, mock primary-care visits between a doctor and a patient. | 5.2 hours for the file test, a 93-minute slice for the live test |
| Read speech | Google FLEURS sentences in English, German, French and Turkish. | 400 clips, 77 minutes |

The tests run in two lanes that are never mixed. **File** sends a whole recording and waits for the transcript. **Streaming** plays the audio at real speed, in 100 ms pieces, the way a live call would, and times each result.

## How to read the numbers

- **Wrong words per 100** is the word error rate. A 6.1 means about 6 words in every 100 were wrong. Lower is better. The 95% range next to some numbers shows how far a result could move on a different sample.
- **Time to first words** is how long after the audio starts streaming until the engine returns any text. Lower is better.
- **Time to final transcript, slowest 10%** is how long after the speaker stops until the finished transcript arrives, for the slowest 1 in 10 turns. This is the number that decides how long a caller waits in bad cases.
- **One-word replies right** is the share of 147 short replies where the whole line matched the script. We allowed one stray extra word at the start.

Scoring compares every transcript to a human transcript or to the read script, and no AI model judges accuracy.

## Results

Every engine here runs on Telnyx except the rows marked ElevenLabs. Linden-1 is in preview and is not in Telnyx's public model list yet. Parakeet v3 and Omi Med STT v1 return only finished transcripts, so their time to first words is the time the finished text arrives.

### Live phone calls

| Engine | Time to first words, median (s) | Time to final transcript, slowest 10% (s) | One-word replies right | Wrong words per 100, medical calls |
|---|---|---|---|---|
| Flux (Deepgram) | 1.0 | 2.36 | 85% | 20.3 |
| Azure Fast | 4.0 | 1.56 | 83% | 17.4 |
| Grok STT (xAI) | 3.8 | 1.47 | 82% | 21.0 |
| Universal 3.5 Pro (AssemblyAI) | 3.3 | 1.61 | 81% | 23.5 |
| Nova-3 (Deepgram) | 1.3 | 0.93 | 80% | 17.7 |
| Soniox stt-rt-v4 | 1.3 | 1.51 | 77% | 19.4 |
| Nova-3 Medical (Deepgram) | 1.3 | 0.97 | 73% | 16.4 |
| Speechmatics Standard | 1.3 | 1.17 | 73% | 28.1 |
| Omi Med STT v1 | 6.7 | 4.68 | 71% | 21.8 |
| Linden-1 (Speechmatics, preview) | 1.3 | 0.77 | 67% | 15.7 |
| **Scribe v2 Realtime (ElevenLabs)** | 2.1 | 1.32 | 67% | 17.3 |
| Parakeet v3 (NVIDIA) | 6.7 | 4.55 | 51% | 26.6 |

Nova-3, Nova-3 Medical, Linden-1, Soniox and Speechmatics all return first words at about 1.3 s. Flux is fastest to start and slowest to finish, because it waits for its own end-of-turn signal before it sends the final text.

### Consultations, streamed live

| Engine | Wrong words per 100 (95% range) | Time to first words, median (s) | Time to final transcript, slowest 10% (s) |
|---|---|---|---|
| **Scribe v2 Realtime (ElevenLabs)** | 6.1 (5.2 to 6.9) | 1.7 | 0.70 |
| Parakeet v3 (NVIDIA) | 7.5 (6.5 to 8.5) | 4.8 | 4.15 |
| Nova-3 Medical (Deepgram) | 8.5 (7.7 to 9.4) | 1.0 | 0.71 |
| Omi Med STT v1 | 8.6 (7.7 to 9.5) | 4.8 | 4.00 |
| Nova-3 (Deepgram) | 8.8 (7.9 to 9.8) | 1.0 | 0.71 |
| Grok STT (xAI) | 8.9 (7.8 to 9.9) | 3.2 | 1.38 |
| Soniox stt-rt-v4 | 10.0 (8.9 to 11.0) | 1.2 | 0.85 |
| Linden-1 (Speechmatics, preview) | 10.0 (8.0 to 12.8) | 1.0 | 0.88 |
| Flux (Deepgram) | 10.4 (9.1 to 11.6) | 0.8 | 1.43 |
| Azure Fast | 11.1 (10.0 to 12.4) | 2.9 | 1.31 |
| Universal 3.5 Pro (AssemblyAI) | 14.6 (13.6 to 15.6) | 2.7 | 1.27 |
| Speechmatics Standard | 14.7 (12.6 to 17.4) | 1.1 | 1.00 |

Scribe v2 Realtime has the lowest error rate here. Its range (5.2 to 6.9) does not overlap Nova-3 Medical's (7.7 to 9.4). Parakeet v3 comes closest on accuracy but takes 4.8 s to return first words.

### Consultations, recorded files

| Engine | Wrong words per 100 (95% range) |
|---|---|
| **Scribe v2 (ElevenLabs)** | 4.0 (3.6 to 4.4) |
| **Scribe v2 Medical (ElevenLabs)** | 4.8 (4.3 to 5.3) |
| Parakeet v3 (NVIDIA) | 5.7 (5.0 to 6.4) |
| Omi Med STT v1 | 5.8 (5.1 to 6.6) |
| Nova-3 Medical (Deepgram) | 5.9 (5.2 to 6.7) |
| Nova-3 (Deepgram) | 6.0 (5.2 to 6.8) |
| Whisper large-v3-turbo (OpenAI) | 9.9 (8.8 to 11.1) |

Scribe v2 Medical was tested on files only, so it has no streaming row above.

### Read speech by language, wrong words per 100

| Language | Scribe v2 | Scribe v2 Realtime | Best Telnyx file engine | Best Telnyx streaming engine |
|---|---|---|---|---|
| English | 4.6 | 5.3 | Parakeet v3 (NVIDIA), 5.2 | Linden-1 (Speechmatics, preview), 5.6 |
| German | 4.7 | 6.5 | Whisper large-v3-turbo (OpenAI), 7.6 | Linden-1 (Speechmatics, preview), 6.9 |
| French | 5.5 | 9.4 | Parakeet v3 (NVIDIA), 7.9 | Linden-1 (Speechmatics, preview), 7.1 |
| Turkish | 5.7 | 9.6 | Whisper large-v3-turbo (OpenAI), 9.8 | Linden-1 (Speechmatics, preview), 9.5 |

## Run it yourself

You need a Telnyx API key and an ElevenLabs API key in your environment. The consultation set is a 1.9 GB download. Commands are copied from our test notes and have not been rerun for this README.

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python jiwer websockets requests whisper-normalizer praatio num2words soundfile numpy wordfreq
export TELNYX_API_KEY=... ELEVENLABS_API_KEY=...

.venv/bin/python datasets/primock57/download.py
.venv/bin/python datasets/primock57/prep.py
.venv/bin/python datasets/primock57/build_terms.py
.venv/bin/python run.py --dataset primock57 --subset pilot --lane batch --medical --run-id my-run
.venv/bin/python run.py --dataset primock57 --subset pilot --lane realtime --medical --run-id my-run
.venv/bin/python report/build.py --run-id my-run
```

Each run writes `results.csv`, `summary.json` and a `scorecard.html` under `runs/<run-id>/`.

## What this test does not show

- It is one set of runs, from October 1, 2026. Engines change, so rerun it before you quote it.
- The samples are small in places, with five callers, 90 medical lines and 147 short replies. Treat gaps of a point or two as ties.
- 339 of the 375 phone lines were scored. The other 36 were set aside for a human listen.
- The phone recordings are not published, so the phone-call track cannot be rerun from this repo. The script and scoring code are here so the method can be checked.
- Telnyx's model docs list Nova-3 Medical as REST only. It returned live results over WebSocket in our runs, so read its streaming rows as a test result, not as a statement of supported use.
- Prices are not in these tables.
- Omi's direct API was also tested. It is left out of the tables because it does not run on Telnyx.

## Data and licenses

PriMock57 (Papadopoulos Korfiatis, Moramarco, Sarac, Savkov, ACL 2022) is licensed CC BY 4.0, and Google FLEURS is licensed CC BY 4.0, per our test notes. The term list comes from Wikidata (CC0). The clip lists in this repo are derived from these sets.

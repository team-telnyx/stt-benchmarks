# Phone-in dataset (real PSTN, 8 kHz, script ground truth)
Teammates call a Telnyx number and read a numbered script. Recordings are real PSTN phone audio with a known transcript.
Script (ground truth): `phonein-script.md` in this folder, 75 lines in packs N (names, alphanumerics), S (short turns), M (medical phone).
The recording line itself is internal, so the phone-in recordings are not published and this track cannot be rerun from this repo. The scripts and scoring are here so the method can be checked.
`phonein.xml` is the TeXML the line answers with: greeting, beep, `<Record maxLength="900" timeout="0" channels="single" format="wav">`.
`fetch_recordings.py` downloads new recordings into `raw/` as `<UTC ts>_<caller digits>_<recording id>.wav` plus a `.json` sidecar.
Segmentation uses the spoken line ids ("N one", "S twelve"), not timestamps.

## Fetch

```bash
python3 datasets/phonein/fetch_recordings.py            # uses phonein.json for number + connection id
python3 datasets/phonein/fetch_recordings.py --since 2026-10-01
```

Re-running skips recording ids already in `raw/`. The `.json` sidecar keeps the full Telnyx recording object.
API: `GET https://api.telnyx.com/v2/recordings` (https://developers.telnyx.com/api-reference/call-recordings/list-all-call-recordings).

## Segmentation

Each caller says a line id before each line, then pauses about 2 s. To cut one recording into per-line clips:

1. Split on silence using energy only (pause of 1.2 s or longer, native 8 kHz, no resampling). No ASR engine places boundaries, so clip edges carry no bias toward any engine under test.
2. Each line yields two speech regions, the spoken id and then the line text. Pair them in order and check the count against the pack (25 N, 30 S, 20 M). If the count is off, listen to the file and fix the boundaries by hand. Do not reach for an ASR to fix the count.
3. Each clip runs from the start of the line-text region to its end, plus 150 ms of padding on each side. The spoken id is trimmed off, so engines are never scored on it.
4. Ground truth for the clip is the script line text for that id. If the caller said "again", keep only the last attempt.
5. Spot-check by listening. Drop clips where the caller deviated from the script, and log them in `raw/<stem>.deviations.txt`.
6. If an ASR ever has to locate boundaries, it must not be an engine under test (Scribe, or anything served through the Telnyx STT providers list, which includes the Whisper models). The engine used goes in a `# boundary_engine: <name>` line at the top of `script.txt`.

## Loader contract (owned by stt-harness, do not edit loader.py)

Put each segmented pack in `~/Projects/stt-scribe-bench/data/phonein/<pack>/`, where `<pack>` is `N-<caller>`, `S-<caller>`, or `M-<caller>`. The folder holds one wav per line plus `script.txt`, one line per clip: `<wav stem><TAB><lang><TAB><exact script text>`. A silence probe is a stem with empty text. Lines that start with `#` are ignored. Run it with `.venv/bin/python -m datasets.phonein.loader <pack>`. The loader transcodes once to 8 kHz mu-law.

`raw/`, `*.wav`, and `*.ulaw` are in `.gitignore`, so teammate voice recordings never get committed.

The first 10 s of each call holds the caller's name, native language, and phone type. Keep it as metadata, never as a scored clip.

## Caveats

- `fetch_recordings.py` field names are UNVERIFIED until the first live recording; the sidecar shows the real schema.
- Telnyx stores recordings on the account; download URLs in the API response are short-lived, so fetch soon after calls.

## Segmentation as actually run (2026-10-01)
Boundaries were NOT from silence detection alone. `segment.py` transcribes channel 0 with faster-whisper small.en (local, not a scored engine; the scored Whisper is large-v3-turbo on Telnyx), aligns its words to the script with spoken line IDs (difflib), and cuts from the end of each spoken ID to the start of the next. 339 of 375 lines scored, 36 held for a human listen (see data/phonein/segment_report.json). Recordings were fetched with dial_live.py + the Telnyx recordings API, not fetch_recordings.py (unused).

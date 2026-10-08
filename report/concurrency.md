# Telnyx realtime STT under concurrent sessions (diagnostic, 2026-10-01)
Diagnostic only, never mixed into accuracy scorecards. It is an internal reliability finding for Telnyx and not sales collateral.
Setup: one Telnyx account, 24 PriMock57 clips (day2_consultation03, clips over 1.5 s), each streamed at real-time pace through wss://api.telnyx.com/v2/speech-to-text/transcription, linear16 at 8 kHz, language en. Concurrency N means N sessions of the same engine open at once.
Result: Speechmatics, Parakeet and Soniox lose accuracy sharply as concurrency rises. AssemblyAI degrades moderately. Deepgram Nova-3 is unaffected.
Caveat: the AssemblyAI and Parakeet rows ran while the 1-session pilot also held one session per engine on the same account. Their concurrency-1 rows therefore had about 2 extra sessions of other Telnyx engines open.
Consequence for the benchmark: accuracy runs use 1 session per engine, and no two realtime processes ever overlap.
Script: scratchpad conc_diag.py (logic mirrors engines/realtime.py). To reproduce, run it with `<Engine> <model> 1,8`.

| Engine / model | WER at 1 session | WER at 4 | WER at 8 | Failed sessions at 8 (of 24) |
| --- | --- | --- | --- | --- |
| Speechmatics speechmatics/standard | 14.6% | 47.6% | 73.3% | 11 |
| Parakeet nvidia/parakeet-v3 | 10.8% | not run | 59.4% | 0 |
| Soniox soniox/stt-rt-v4 | 5.4% | not run | 14.3% | 0 |
| AssemblyAI assemblyai/universal-3-5-pro | 11.4% | not run | 19.4% | 0 |
| Deepgram deepgram/nova-3 | 8.3% | not run | 8.3% | 0 |

What failure looks like: for Speechmatics, a session receives no partials and no finals at all and never closes after CloseStream. Other sessions return only the last word or two of the clip ("Day." for an 11-word utterance). This is consistent with audio being dropped before the upstream session is ready. A 1 to 2 s silence pre-warm did not help when serial (WER 15.3% without pre-warm vs 22.2% with), so the trigger is concurrency, not cold start.
Open question for Telnyx engineering: is there a per-account or per-pod session limit for Speechmatics, Parakeet and Soniox on the WebSocket STT gateway? Production voice traffic runs many concurrent calls, so this needs an owner.

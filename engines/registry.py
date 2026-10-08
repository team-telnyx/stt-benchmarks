"""Engine registry. Lanes are never mixed: a batch engine is only compared with batch engines.

langs = languages each engine is run on. Telnyx sets come from the live
GET /v2/speech-to-text/providers listing (2026-10-01): Speechmatics standard lists en/es but not
de/fr/tr; Flux is en only, Flux-multi adds de/fr; Parakeet lists only "auto", so its de/fr come
from the NVIDIA parakeet-tdt-0.6b-v3 model card (25 European languages, no Turkish), UNVERIFIED on Telnyx.
"""

ENGINES = {
    # ---- batch lane ----
    "el-scribe_v2_medical": dict(lane="batch", vendor="elevenlabs", model="scribe_v2_medical", price="elevenlabs/scribe_v2_medical", langs={"en", "de", "fr", "tr"}, medical=True),
    "el-scribe_v2": dict(lane="batch", vendor="elevenlabs", model="scribe_v2", price="elevenlabs/scribe_v2", langs={"en", "de", "fr", "tr"}),
    "tx-whisper-large-v3-turbo": dict(lane="batch", vendor="telnyx", model="openai/whisper-large-v3-turbo", price="telnyx/whisper", langs={"en", "de", "fr", "tr"}),
    "tx-nova-3-medical": dict(lane="batch", vendor="telnyx", model="deepgram/nova-3-medical", price="telnyx/deepgram", langs={"en"}, medical=True),
    "tx-nova-3": dict(lane="batch", vendor="telnyx", model="deepgram/nova-3", price="telnyx/deepgram", langs={"en", "de", "fr", "tr"}),
    "tx-parakeet-v3": dict(lane="batch", vendor="telnyx", model="nvidia/parakeet-v3", price="telnyx/parakeet", langs={"en", "de", "fr"}),
    "tx-omi-med-stt-v1": dict(lane="batch", vendor="telnyx", model="omi-health/omi-med-stt-v1", price="telnyx/parakeet", langs={"en"}, medical=True),
    # ---- realtime lane ----
    "el-scribe_v2_realtime": dict(lane="realtime", vendor="elevenlabs", model="scribe_v2_realtime", price="elevenlabs/scribe_v2_realtime", langs={"en", "de", "fr", "tr"}),
    "txrt-nova-3-medical": dict(lane="realtime", vendor="telnyx", engine="Deepgram", model="deepgram/nova-3-medical", price="telnyx/deepgram", langs={"en"}, medical=True),
    "txrt-nova-3": dict(lane="realtime", vendor="telnyx", engine="Deepgram", model="deepgram/nova-3", price="telnyx/deepgram", langs={"en", "de", "fr", "tr"}),
    "txrt-flux": dict(lane="realtime", vendor="telnyx", engine="Deepgram", model="deepgram/flux", price="telnyx/deepgram", langs={"en"}),
    "txrt-flux-multi": dict(lane="realtime", vendor="telnyx", engine="Deepgram", model="deepgram/flux-multi", price="telnyx/deepgram", langs={"en", "de", "fr"}, general_only=True),
    "txrt-omi-med-stt-v1": dict(lane="realtime", vendor="telnyx", engine="Parakeet", model="omi-health/omi-med-stt-v1", price="telnyx/parakeet", langs={"en"}, medical=True),
    "txrt-parakeet-v3": dict(lane="realtime", vendor="telnyx", engine="Parakeet", model="nvidia/parakeet-v3", price="telnyx/parakeet", langs={"en", "de", "fr"}),
    "txrt-universal-3-5-pro": dict(lane="realtime", vendor="telnyx", engine="AssemblyAI", model="assemblyai/universal-3-5-pro", price="telnyx/assemblyai", langs={"en", "de", "fr", "tr"}),
    "txrt-speechmatics-standard": dict(lane="realtime", vendor="telnyx", engine="Speechmatics", model="speechmatics/standard", price="telnyx/speechmatics", langs={"en"}),
    "txrt-soniox-stt-rt-v4": dict(lane="realtime", vendor="telnyx", engine="Soniox", model="soniox/stt-rt-v4", price="telnyx/soniox", langs={"en", "de", "fr", "tr"}),
    # ---- added 2026-10-01 evening (lead session) ----
    "omi-medical-1": dict(lane="batch", vendor="omi", model="omi-medical-1", price="omi/batch", langs={"en"}, medical=True, note="Omi direct API (Frankfurt); pending on Telnyx"),
    "omi-medical-edge-1": dict(lane="batch", vendor="omi", model="omi-medical-edge-1", price="omi/batch", langs={"en"}, medical=True, note="Omi-hosted copy of the open model Telnyx runs as omi-med-stt-v1"),
    "omirt-medical-1": dict(lane="realtime", vendor="omi", model="omi-medical-1", price="omi/live", langs={"en"}, medical=True, note="Omi direct API (Frankfurt); latency includes transatlantic RTT"),
    "txrt-grok-stt": dict(lane="realtime", vendor="telnyx", engine="xAI", model="xai/grok-stt", price="telnyx/xai", langs={"en", "de", "fr", "tr"}),
    "txrt-azure-fast": dict(lane="realtime", vendor="telnyx", engine="Azure", model="azure/fast", price="telnyx/azure", langs={"en", "de", "fr", "tr"}),
    "txrt-linden-1": dict(lane="realtime", vendor="telnyx", engine="Speechmatics", model="speechmatics/linden-1", price="telnyx/speechmatics", langs={"en", "de", "fr", "tr"}, note="preview, hosted=false"),
}

CONCURRENCY = {("batch", "elevenlabs"): 4, ("batch", "telnyx"): 6, ("realtime", "elevenlabs"): 1, ("realtime", "telnyx"): 1, ("batch", "omi"): 2, ("realtime", "omi"): 1}
# Realtime accuracy runs use 1 session per engine: on 2026-10-01 Telnyx Speechmatics went from 14.6% WER
# (1 session) to 73.3% (8 sessions) and Soniox from 5.4% to 14.3% on the same 24 clips; Nova-3 was flat.
# The concurrency effect is reported separately (report/concurrency.md), never mixed into accuracy.

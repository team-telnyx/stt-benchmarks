import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from score import metrics  # noqa: E402
from score.normalize import normalize  # noqa: E402


def test_units_and_numbers_match_both_ways():
    assert normalize("Take 25mg twice a day") == normalize("take twenty-five milligrams twice a day")
    assert normalize("400 mg") == normalize("four hundred milligrams")
    assert normalize("5 ml") == normalize("five millilitres")


def test_spelling_and_fillers():
    assert normalize("Diarrhoea, um, OK?") == normalize("diarrhea okay")
    assert normalize("All right, mm-hmm.") == "alright"
    assert normalize("Ohh, I live alone") == "i live alone"


def test_oh_kept_next_to_numbers():
    assert normalize("five oh two") == normalize("502")


def test_markup_stripped():
    assert normalize("<UNSURE>Hello how</UNSURE> um") == "hello how"


def test_non_english_digits_to_words():
    assert normalize("Ich habe 25 Euro", "de") == normalize("ich habe fünfundzwanzig euro", "de")
    assert normalize("Il a 3 ans", "fr") == normalize("il a trois ans", "fr")
    assert normalize("Saat 7", "tr") == normalize("saat yedi", "tr")


def test_abbreviations_and_separators():
    assert normalize("120 km bis 1.000 v. Chr.", "de") == normalize("hundertzwanzig Kilometer bis tausend vor Christus", "de")
    assert normalize("Il y a 1 000 ans, 300 av. J.-C.", "fr") == normalize("il y a mille ans trois cents avant Jésus-Christ", "fr")
    assert normalize("Meydanı'ndaki 20'nci yüzyıl", "tr") == normalize("meydanındaki yirminci yüzyıl", "tr")


def _clip(gold, kind="speech"):
    return {"id": "c", "group": "g", "kind": kind, "lang": "en", "gold": gold, "dur": 1.0}


def test_failure_counts_as_full_deletion():
    row = metrics.score_clip(_clip("the patient has asthma"), {"ok": False, "error": "http 502"}, None)
    assert (row["S"], row["D"], row["I"], row["N"]) == (0, 4, 0, 4)


def test_term_recall_longest_match_and_counts():
    idx = metrics.term_index([{"term": "chest pain", "category": "condition"}, {"term": "pain", "category": "condition"},
                              {"term": "paracetamol", "category": "drug"}])
    row = metrics.score_clip(_clip("chest pain and paracetamol and paracetamol"),
                             {"ok": True, "text": "chest pain and paracetamol"}, idx)
    assert row["terms_total"] == {"condition": 1, "drug": 2}
    assert row["terms_hit"] == {"condition": 1, "drug": 1}


def test_silence_hallucination():
    assert metrics.score_clip(_clip("", "silence"), {"ok": True, "text": "Thank you."}, None)["hallucinated"]
    assert not metrics.score_clip(_clip("", "silence"), {"ok": True, "text": ""}, None)["hallucinated"]


def test_level_gate(tmp_path):
    import numpy as np
    import soundfile as sf
    from datasets.audio import gate_gain_db
    sr = 16000
    t = np.arange(sr * 2) / sr
    tone = np.sin(2 * np.pi * 300 * t).astype("float32")
    sf.write(tmp_path / "quiet.wav", tone * 10 ** (-57 / 20), sr)   # like FLEURS en median
    sf.write(tmp_path / "normal.wav", tone * 10 ** (-20 / 20), sr)  # like PriMock
    gain, lvl = gate_gain_db(tmp_path / "quiet.wav")
    assert lvl < -36 and abs((lvl + gain) - (-26)) < 0.5
    assert gate_gain_db(tmp_path / "normal.wav")[0] == 0.0

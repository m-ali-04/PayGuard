import pandas as pd

from get_complaints import DEST as SLICE, NARRATIVE
from run_triage import INJECTION_CASES, compose, injected

BASE = "The bank froze my account. I can't pay rent. Please release my funds."


def test_injection_lands_where_asked_and_keeps_the_complaint_whole():
    assert compose(BASE, "ATTACK.", "start") == f"ATTACK. {BASE}"
    assert compose(BASE, "ATTACK.", "end") == f"{BASE} ATTACK."
    middle = compose(BASE, "ATTACK.", "middle")
    assert middle == "The bank froze my account. ATTACK. I can't pay rent. Please release my funds."  # nearest break to the middle
    assert middle.replace("ATTACK. ", "") == BASE


def test_middle_without_a_sentence_break_appends():
    assert compose("no punctuation here", "ATTACK.", "middle") == "no punctuation here ATTACK."


def test_every_case_is_built_from_its_real_base_complaint():
    slice_ = pd.read_csv(SLICE, dtype=str, keep_default_na=False)
    cases = pd.read_csv(INJECTION_CASES, dtype=str, keep_default_na=False)
    built = injected(slice_)
    base = slice_.set_index("Complaint ID").loc[cases.base_complaint_id]
    assert list(built["Complaint ID"]) == list(cases.case_id)
    for text, original, attack in zip(built[NARRATIVE], base[NARRATIVE], cases.injection):
        assert attack in text and text.replace(attack, "").split() == original.split()

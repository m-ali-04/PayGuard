import pandas as pd
from rich.console import Console

from payguard.triage.pipeline import COLUMNS
from payguard.triage.taxonomy import Flag
from run_triage import INJECTION_OUTPUT, OUTPUT, injection_output, output_path, select
from triage_panel import TriagePanel

NO_FLAGS = {flag: "n" for flag in Flag}
GOLD = pd.DataFrame([
    {"complaint_id": "1", "narrative": "My car loan servicer took me to court today.", "tags": "",
     "category": "lending", "urgency": "high", **NO_FLAGS, "legal_threat": "y"},
    {"complaint_id": "2", "narrative": "A monthly fee was added to my checking account.", "tags": "",
     "category": "banking_payments", "urgency": "medium", **NO_FLAGS},
])


def row(cid: str, **values) -> dict:
    base = dict.fromkeys(COLUMNS, "") | {"complaint_id": cid, "attempts": 1, "prompt_tokens": 1000,
                                         "output_tokens": 200, "latency_s": 4.0, "requires_human": "n"}
    return base | values


def render(rows: list[dict]) -> str:
    console = Console(record=True, width=140)
    console.print(TriagePanel(rows, 3, GOLD, "Triage · test"))
    return console.export_text()


def test_empty_panel_renders():
    assert "0 / 3 triaged" in render([])


def test_panel_shows_a_missed_sensitive_case_a_match_and_a_failure():
    text = render([
        row("1", category="lending", urgency="medium", **NO_FLAGS),  # gold needs a human (high, legal): missed
        row("2", category="banking_payments", urgency="medium", **NO_FLAGS),
        row("3", attempts=2, error="invalid answer (1 validation errors)", requires_human="y"),
    ])
    assert "3 / 3 triaged" in text and "MISSED sensitive" in text
    assert "✓ cat ✓ urg" in text and "failed: invalid answer" in text


def test_limit_takes_gold_complaints_in_gold_order():
    complaints = pd.DataFrame({"Complaint ID": ["9", "b", "a", "c"], "x": [0, 1, 2, 3]})
    gold = pd.DataFrame({"complaint_id": ["a", "b", "c"]})
    assert list(select(complaints, gold, 2)["Complaint ID"]) == ["a", "b"]
    assert len(select(complaints, gold, None)) == 4


def test_trial_runs_never_write_the_committed_file():
    assert output_path("qwen3.5:4b", None) == OUTPUT
    assert output_path("qwen3.5:4b", 20).name == "trial_qwen3.5_4b.csv"


def test_injection_runs_on_another_model_never_write_the_committed_file():
    assert injection_output("granite4.2:3b") == INJECTION_OUTPUT
    assert injection_output("qwen3.5:4b").name == "trial_injection_qwen3.5_4b.csv"

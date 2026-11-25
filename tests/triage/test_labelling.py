import pandas as pd

from get_complaints import NARRATIVE
from make_labelling_file import COLUMNS, SPLITS, check_rows, draw_gold


def slice_with_templates() -> pd.DataFrame:
    """200 complaints where every narrative appears twice under different IDs, like CFPB's template filings."""
    return pd.DataFrame({
        "Complaint ID": [str(i) for i in range(200)],
        "Product": "Debt collection",
        "Tags": "",
        NARRATIVE: [f"template text {i % 100}" for i in range(200)],
    })


def test_gold_split_sizes_and_no_narrative_on_both_sides():
    gold = draw_gold(slice_with_templates())
    assert gold["split"].value_counts().to_dict() == SPLITS
    assert gold["narrative"].is_unique
    assert list(gold.columns) == COLUMNS and "Product" not in gold.columns  # labelling stays blind


def labelled_row(**changes) -> dict[str, str]:
    row = {column: "" for column in COLUMNS} | {"complaint_id": "1", "split": "dev", "category": "Lending",
                                                 "urgency": "high", "fraud_allegation": "N", "legal_threat": "n",
                                                 "vulnerable_customer": "y", "safety_risk": "n",
                                                 "discrimination": "n"}
    return row | changes


def test_check_accepts_a_complete_row_case_insensitively():
    assert check_rows([labelled_row()]) == []


def test_check_reports_each_blank_or_invalid_cell():
    problems = check_rows([labelled_row(category="loans", urgency="urgent", safety_risk="")])
    assert len(problems) == 3
    assert any("category" in p and "'loans'" in p for p in problems)
    assert any("safety_risk: blank" in p for p in problems)

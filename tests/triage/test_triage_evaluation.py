import pytest

from payguard.triage.evaluation import gold_reasons, sentence_count, summary_issues, wilson
from payguard.triage.policy import Assessment, review_reasons
from payguard.triage.taxonomy import Category, Flag, Urgency

NARRATIVE = "I was charged {$1500.00} on XX/XX/XXXX and again 3 days later by U.S. Bank."


def test_amount_in_the_complaint_passes_in_any_format():
    assert summary_issues(NARRATIVE, "U.S. Bank charged the consumer $1,500 twice, 3 days apart.") == []


def test_invented_amount_is_flagged():
    assert summary_issues(NARRATIVE, "The bank charged $2,000.") == ["numbers not in the complaint: 2000"]


def test_more_than_two_sentences_is_flagged():
    assert summary_issues(NARRATIVE, "One thing. Another thing. A third thing.") == ["3 sentences"]
    assert sentence_count("The consumer says U.S. Bank kept the money. They want it back.") == 2


def test_empty_summary_is_flagged():
    assert summary_issues(NARRATIVE, "  ") == ["empty"]


def test_gold_uses_the_same_policy_as_the_model():
    gold = {"category": "lending", "urgency": "high"} | {flag: "n" for flag in Flag} | {"legal_threat": "y"}
    expected = review_reasons(NARRATIVE, "Servicemember",
                              Assessment(Category.LENDING, Urgency.HIGH, frozenset({Flag.LEGAL_THREAT})))
    assert gold_reasons(NARRATIVE, "Servicemember", gold) == expected
    assert expected == ["tag: Servicemember", "high urgency", "flag: legal_threat"]


def test_gold_ignores_the_legal_words_backstop():
    gold = {"category": "lending", "urgency": "medium"} | {flag: "n" for flag in Flag}
    assert gold_reasons("I reported this to the state attorney general last week.", "", gold) == []


def test_wilson_matches_published_values():
    # Reference values from statsmodels' proportion_confint(method="wilson").
    assert wilson(20, 22) == pytest.approx((0.7219, 0.9747), abs=1e-4)
    assert wilson(0, 10) == pytest.approx((0.0, 0.2775), abs=1e-4)
    assert wilson(0, 0) == (0.0, 1.0)

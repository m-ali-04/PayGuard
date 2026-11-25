import pytest

from payguard.triage.policy import Assessment, review_reasons
from payguard.triage.taxonomy import Category, Flag, Urgency

TEXT = "I was charged a monthly fee I never agreed to."


def assessment(category=Category.BANKING_PAYMENTS, urgency=Urgency.LOW, flags=()) -> Assessment:
    return Assessment(category, urgency, frozenset(flags))


def test_tag_survives_empty_narrative():
    reasons = review_reasons("", "Older American, Servicemember", None)
    assert reasons == ["tag: Older American", "tag: Servicemember", "no usable narrative"]


def test_tag_survives_failed_triage():
    assert review_reasons(TEXT, "Servicemember", None) == ["tag: Servicemember", "triage failed"]


def test_tag_alone_forces_review_of_a_minor_complaint():
    assert review_reasons(TEXT, "Servicemember", assessment()) == ["tag: Servicemember"]


def test_clean_untagged_complaint_needs_no_human():
    assert review_reasons(TEXT, "", assessment()) == []


@pytest.mark.parametrize("flag", list(Flag))
def test_each_flag_is_its_own_reason(flag):
    assert review_reasons(TEXT, "", assessment(flags={flag})) == [f"flag: {flag}"]


def test_unclear_category_and_high_urgency_are_reasons():
    reasons = review_reasons(TEXT, "", assessment(Category.OTHER, Urgency.HIGH, {Flag.LEGAL_THREAT}))
    assert reasons == ["unclear category", "high urgency", "flag: legal_threat"]


def test_too_short_narrative_is_a_reason_even_when_triage_ran():
    assert review_reasons("this is fraud", "", assessment()) == ["no usable narrative"]


def test_legal_words_send_a_complaint_to_a_human_whatever_the_model_says():
    assert review_reasons("They served me court papers for a debt I paid off.", "", assessment()) == ["legal words"]
    assert review_reasons("My attorney will contact you about these charges.", "", assessment()) == ["legal words"]


def test_words_containing_legal_terms_dont_match():
    assert review_reasons("I have an issue with a courtesy fee on my account.", "", assessment()) == []


def test_failed_triage_keeps_the_legal_reason():
    assert review_reasons("I am filing a lawsuit over these unauthorized fees.", "", None) == ["legal words", "triage failed"]

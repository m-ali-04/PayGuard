import httpx

from payguard.triage.llm import OLLAMA_URL
from payguard.triage.pipeline import COLUMNS, to_row, triage_complaint
from payguard.triage.taxonomy import Flag

from ollama_fakes import VALID, client_replying, ollama_reply

TEXT = "My car loan servicer is about to repossess my car."


def test_short_narrative_skips_the_model_and_keeps_the_tag():
    def no_call(request):
        raise AssertionError("the model must not be called")

    http = httpx.Client(base_url=OLLAMA_URL, transport=httpx.MockTransport(no_call))
    record = triage_complaint(http, "1", "fraud", "Servicemember", "m")
    assert record.reasons == ("tag: Servicemember", "no usable narrative", "triage failed") and record.requires_human
    row = to_row(record, "m", "d")
    assert row["attempts"] == "" and row["category"] == "" and row["requires_human"] == "y"


def test_failed_call_goes_to_a_human_with_the_error_and_the_tag():
    http, _ = client_replying(httpx.Response(404, json={"error": "model not found"}))
    row = to_row(triage_complaint(http, "2", TEXT, "Older American", "m"), "m", "d")
    assert row["review_reasons"] == "tag: Older American; triage failed" and row["requires_human"] == "y"
    assert "request failed" in row["error"] and row["category"] == ""


def test_answer_fills_every_column():
    http, _ = client_replying(ollama_reply(VALID))
    row = to_row(triage_complaint(http, "3", TEXT, "", "qwen"), "qwen", "sha")
    assert list(row) == COLUMNS
    assert (row["category"], row["urgency"], row["legal_threat"], row["fraud_allegation"]) == ("lending", "high", "y", "n")
    assert row["review_reasons"] == "high urgency; flag: legal_threat" and row["requires_human"] == "y"
    assert (row["prompt_tokens"], row["output_tokens"], row["model_digest"]) == (900, 80, "sha")


def test_clean_complaint_is_routed_without_a_human():
    calm = VALID | {"category": "banking_payments", "urgency": "low"} | {flag: False for flag in Flag}
    http, _ = client_replying(ollama_reply(calm))
    row = to_row(triage_complaint(http, "4", TEXT, "", "m"), "m", "d")
    assert row["requires_human"] == "n" and row["review_reasons"] == ""

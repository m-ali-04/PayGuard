"""One complaint in, one triage record out: the model's judgement plus every review reason.

The batch runner writes records with `to_row` and the evaluation reads the same COLUMNS, so the two
can't drift apart.
"""
from dataclasses import dataclass

import httpx

from payguard.triage.llm import Result, to_assessment, triage
from payguard.triage.policy import is_usable, review_reasons
from payguard.triage.taxonomy import Flag

COLUMNS = ["complaint_id", "category", "urgency", *Flag, "summary", "confidence_note", "requires_human",
           "review_reasons", "attempts", "error", "prompt_tokens", "output_tokens", "latency_s", "model",
           "model_digest"]


@dataclass(frozen=True)
class Record:
    complaint_id: str
    reasons: tuple[str, ...]
    result: Result | None  # None when the narrative was too short to send to the model

    @property
    def requires_human(self) -> bool:
        return bool(self.reasons)


def triage_complaint(http: httpx.Client, complaint_id: str, narrative: str, tags: str, model: str) -> Record:
    result = triage(http, narrative, model) if is_usable(narrative) else None
    output = result.output if result else None
    assessment = to_assessment(output) if output else None
    return Record(complaint_id, tuple(review_reasons(narrative, tags, assessment)), result)


def _yn(value: bool) -> str:
    return "y" if value else "n"


def to_row(record: Record, model: str, digest: str) -> dict:
    """One CSV row; the judgement and call columns stay blank when there was no call or no valid answer."""
    result = record.result
    output = result.output if result else None
    judgement = {"category": output.category, "urgency": output.urgency,
                 **{flag: _yn(getattr(output, flag)) for flag in Flag},
                 "summary": output.summary, "confidence_note": output.confidence_note} if output else {}
    call = {"attempts": result.attempts, "error": result.error or "", "prompt_tokens": result.prompt_tokens,
            "output_tokens": result.output_tokens, "latency_s": round(result.latency_s, 2)} if result else {}
    return ({column: "" for column in COLUMNS} | judgement | call
            | {"complaint_id": record.complaint_id, "requires_human": _yn(record.requires_human),
               "review_reasons": "; ".join(record.reasons), "model": model, "model_digest": digest})

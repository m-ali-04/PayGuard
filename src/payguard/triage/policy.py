"""Decide which complaints need a human, with every reason that applies.

Every check runs on every complaint and none stops the others, so a CFPB tag is never lost
behind an empty narrative or a failed LLM call. The policy never changes urgency: a tagged
complaint about a minor issue is reviewed, at the urgency its content justifies.
"""
from dataclasses import dataclass

from payguard.triage.taxonomy import Category, Flag, Urgency

MIN_WORDS = 5  # assumption: shorter narratives can't be triaged, so they skip the LLM and go to a human


@dataclass(frozen=True)
class Assessment:
    """What the LLM judged from the text; None in its place means the call failed."""
    category: Category
    urgency: Urgency
    flags: frozenset[Flag]


def is_usable(narrative: str) -> bool:
    return len(narrative.split()) >= MIN_WORDS


def review_reasons(narrative: str, tags: str, assessment: Assessment | None) -> list[str]:
    """Why this complaint needs a human; empty means it can be routed automatically."""
    reasons = [f"tag: {tag.strip()}" for tag in tags.split(",") if tag.strip()]
    if not is_usable(narrative):
        reasons.append("no usable narrative")
    if assessment is None:
        if is_usable(narrative):  # a skipped narrative never reached the model, so nothing failed
            reasons.append("triage failed")
    else:
        if assessment.category == Category.OTHER:
            reasons.append("unclear category")
        if assessment.urgency == Urgency.HIGH:
            reasons.append("high urgency")
        reasons += [f"flag: {flag}" for flag in Flag if flag in assessment.flags]
    return reasons

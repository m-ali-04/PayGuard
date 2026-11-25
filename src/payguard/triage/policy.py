"""Decide which complaints need a human, with every reason that applies.

Every check runs on every complaint and none stops the others, so a CFPB tag is never lost
behind an empty narrative or a failed LLM call. The policy never changes urgency: a tagged
complaint about a minor issue is reviewed, at the urgency its content justifies.
"""
import re
from dataclasses import dataclass

from payguard.triage.taxonomy import Category, Flag, Urgency

MIN_WORDS = 5  # assumption: shorter narratives can't be triaged, so they skip the LLM and go to a human
# Backstop for legal threats, which the brief says must never be auto-closed: the 3B model caught none of
# the 5 in the gold set (court papers, a lawsuit threat), so legal language sends a complaint to a human
# whatever the model says. Word boundaries keep "issue" and "courtesy" out.
LEGAL_WORDS = re.compile(r"\b(?:attorneys?|lawyers?|lawsuits?|sue|suing|sued|courts?|small claims|litigation|legal action)\b",
                         re.IGNORECASE)


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
    if LEGAL_WORDS.search(narrative):
        reasons.append("legal words")
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

"""Scoring helpers for the triage evaluation: the gold policy and the automatic summary checks."""
import re

from payguard.triage.policy import Assessment, review_reasons
from payguard.triage.taxonomy import Category, Flag, Urgency

# "$1,500.00", "1500", "180", "3.5": commas and trailing zero decimals are dropped before comparing.
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
# A sentence ends at . ! or ? followed by a capital or the end, except after a single capital letter,
# so "U.S. Bank" doesn't count as two sentences.
SENTENCE_END = re.compile(r"(?<!\b[A-Z])[.!?](?=\s+[A-Z\"']|\s*$)")
MAX_SENTENCES = 2


def gold_reasons(narrative: str, tags: str, gold: dict[str, str]) -> list[str]:
    """The review policy applied to the gold labels, so gold and model are judged by the same rule."""
    flags = frozenset(flag for flag in Flag if gold[flag] == "y")
    return review_reasons(narrative, tags, Assessment(Category(gold["category"]), Urgency(gold["urgency"]), flags))


def _numbers(text: str) -> set[float]:
    return {float(match.replace(",", "")) for match in NUMBER.findall(text)}


def sentence_count(text: str) -> int:
    return len(SENTENCE_END.findall(text.strip())) or (1 if text.strip() else 0)


def summary_issues(narrative: str, summary: str) -> list[str]:
    """Cheap, mechanical signs of an unfaithful or overlong summary; meaning is left to the spot-check."""
    if not summary.strip():
        return ["empty"]
    issues = []
    if (sentences := sentence_count(summary)) > MAX_SENTENCES:
        issues.append(f"{sentences} sentences")
    invented = sorted(_numbers(summary) - _numbers(narrative))
    if invented:
        issues.append("numbers not in the complaint: " + ", ".join(f"{n:g}" for n in invented))
    return issues

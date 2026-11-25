"""Scoring helpers for the triage evaluation: the gold policy, the summary checks and the intervals."""
import math
import re

from payguard.triage.policy import LEGAL_REASON, Assessment, review_reasons
from payguard.triage.taxonomy import Category, Flag, Urgency

# "$1,500.00", "1500", "180", "3.5": commas and trailing zero decimals are dropped before comparing.
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
# A sentence ends at . ! or ? followed by a capital or the end, except after a single capital letter,
# so "U.S. Bank" doesn't count as two sentences.
SENTENCE_END = re.compile(r"(?<!\b[A-Z])[.!?](?=\s+[A-Z\"']|\s*$)")
MAX_SENTENCES = 2
Z_95 = 1.959964


def wilson(k: int, n: int) -> tuple[float, float]:
    """95% Wilson score interval for k successes in n.

    Wilson rather than the textbook p ± 1.96·SE because that one breaks at small n and at rates near 0 or
    1 (20 of 22 would reach past 100%), which is exactly where the test set's numbers sit.
    """
    if n == 0:
        return 0.0, 1.0
    p = k / n
    centre = (p + Z_95**2 / (2 * n)) / (1 + Z_95**2 / n)
    half = Z_95 * math.sqrt(p * (1 - p) / n + Z_95**2 / (4 * n**2)) / (1 + Z_95**2 / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def gold_reasons(narrative: str, tags: str, gold: dict[str, str]) -> list[str]:
    """The review policy applied to the gold labels, so gold and model are judged by the same rule.

    The legal-words backstop is left out: gold should reflect what the labeller decided (and the tags),
    or the keyword rule would score its own matches as correct.
    """
    flags = frozenset(flag for flag in Flag if gold[flag] == "y")
    reasons = review_reasons(narrative, tags, Assessment(Category(gold["category"]), Urgency(gold["urgency"]), flags))
    return [reason for reason in reasons if reason != LEGAL_REASON]


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

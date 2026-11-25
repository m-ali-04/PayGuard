"""Score the committed triage outputs and write reports/triage/evaluation_report.md.

Usage: uv run scripts/triage/evaluate_triage.py

Needs no model: it reads data/triage/triage_sample.csv (from run_triage.py), the gold labels and the
slice. On the first run it also draws 10 test summaries into data/triage/summary_spotcheck.csv for a
human to mark faithful y/n; the report shows "pending" until that's done.
"""
import sys

import numpy as np
import pandas as pd

from get_complaints import DEST as SLICE, NARRATIVE, SEED
from make_labelling_file import LABELS
from payguard.reporting import pct, table
from payguard.triage.evaluation import gold_reasons, summary_issues
from payguard.triage.pipeline import COLUMNS
from payguard.triage.taxonomy import Category, Flag, Urgency, reference_category
from run_triage import OUTPUT

REPORT = SLICE.parents[2] / "reports" / "triage" / "evaluation_report.md"
SPOTCHECK = SLICE.with_name("summary_spotcheck.csv")
SPOTCHECK_SIZE = 10
MONTHLY_VOLUME = 50_000  # the client's figure
# Claude Haiku 5.5, $ per million input / output tokens (checked 2026-11-25), as a hosted comparison.
HOSTED_MODEL, HOSTED_IN, HOSTED_OUT = "Claude Haiku 5.5", 0.10, 0.50
FAILED = "failed"


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    """All 500 outputs joined to their complaint, and the 80 gold rows joined to their output."""
    out = pd.read_csv(OUTPUT, dtype=str, keep_default_na=False)
    if list(out.columns) != COLUMNS:
        raise SystemExit(f"{OUTPUT} doesn't have the expected columns; rerun run_triage.py.")
    complaints = pd.read_csv(SLICE, dtype=str, keep_default_na=False).rename(columns={
        "Complaint ID": "complaint_id", NARRATIVE: "narrative", "Tags": "tags", "Product": "product",
        "Issue": "issue"})[["complaint_id", "narrative", "tags", "product", "issue"]]
    gold = pd.read_csv(LABELS, dtype=str, keep_default_na=False).drop(columns=["narrative", "tags"])
    out = out.merge(complaints, on="complaint_id", validate="one_to_one")
    out["category"] = out.category.replace("", FAILED)
    out["split"] = out.complaint_id.map(gold.set_index("complaint_id").split).fillna("")
    graded = gold.merge(out, on="complaint_id", suffixes=("_gold", ""), validate="one_to_one")
    labels = ["category", "urgency", *Flag]
    graded["gold_reasons"] = [gold_reasons(r.narrative, r.tags, {c: r[f"{c}_gold"] for c in labels})
                              for _, r in graded.iterrows()]
    return out, graded


def run_section(out: pd.DataFrame) -> str:
    attempts = pd.to_numeric(out.attempts, errors="coerce")
    reasons = out.review_reasons[out.review_reasons != ""].str.split("; ").explode().value_counts()
    return "\n\n".join([
        "## 1. Run",
        table(["Complaints", "Valid answers", "Failed calls", "Needed a re-ask", "Skipped (too short)",
               "Need a human"],
              [[len(out), (out.category != FAILED).sum(), (out.error != "").sum(), (attempts > 1).sum(),
                attempts.isna().sum(), f"{(out.requires_human == 'y').sum()} ({pct((out.requires_human == 'y').mean())})"]]),
        "Why complaints go to a human (a complaint can have several reasons):",
        table(["Reason", "Complaints"], [[reason, n] for reason, n in reasons.items()]),
    ])


def confusion(gold: pd.Series, model: pd.Series, labels: list[str]) -> str:
    counts = pd.crosstab(gold, model).reindex(index=labels, columns=labels + [FAILED], fill_value=0)
    counts = counts.loc[:, (counts.sum() > 0) | counts.columns.isin(labels)]
    return table(["Gold \\ model", *counts.columns], [[label, *row] for label, row in counts.iterrows()])


def gold_section(graded: pd.DataFrame, split: str) -> str:
    g = graded[graded.split == split]
    model_human, gold_human = g.requires_human == "y", g.gold_reasons.str.len() > 0
    caught = (model_human & gold_human).sum()
    flag_rows = [[flag, (g[f"{flag}_gold"] == "y").sum(), ((g[f"{flag}_gold"] == "y") & (g[flag] == "y")).sum(),
                  ((g[f"{flag}_gold"] == "y") & (g[flag] != "y")).sum(), ((g[f"{flag}_gold"] == "n") & (g[flag] == "y")).sum()]
                 for flag in Flag]
    return "\n\n".join([
        f"### {split} ({len(g)} complaints)",
        f"Category accuracy **{pct((g.category == g.category_gold).mean())}**, urgency accuracy "
        f"**{pct((g.urgency == g.urgency_gold).mean())}**. A failed call counts as wrong.",
        confusion(g.category_gold, g.category, list(Category)),
        confusion(g.urgency_gold, g.urgency.replace("", FAILED), list(Urgency)),
        "Flags, as counts (too few cases for a meaningful rate):",
        table(["Flag", "Gold cases", "Caught", "Missed", "False alerts"], flag_rows),
        f"`requires_human`: the gold labels send {gold_human.sum()} to a human; the pipeline catches "
        f"{caught} (recall {pct(caught / gold_human.sum()) if gold_human.sum() else 'n/a'}) and sends "
        f"{model_human.sum()} in all (precision {pct(caught / model_human.sum()) if model_human.sum() else 'n/a'}).",
    ])


def sensitive_section(graded: pd.DataFrame) -> str:
    missed = graded[(graded.gold_reasons.str.len() > 0) & (graded.requires_human == "n")]
    if missed.empty:
        return "## 3. Sensitive cases routed without a human\n\nNone: every gold case needing a human was sent to one."
    return "\n\n".join([
        "## 3. Sensitive cases routed without a human",
        f"{len(missed)} gold complaints that need a human would have been routed automatically:",
        table(["Complaint", "Split", "Gold reasons", "Model category", "Model urgency"],
              [[r.complaint_id, r.split, "; ".join(r.gold_reasons), r.category, r.urgency] for r in missed.itertuples()]),
    ])


def cfpb_section(out: pd.DataFrame, graded: pd.DataFrame) -> str:
    valid = out[out.category != FAILED]
    reference = [reference_category(p, i) for p, i in zip(valid["product"], valid.issue)]
    gold_reference = [reference_category(p, i) for p, i in zip(graded["product"], graded.issue)]
    return "\n\n".join([
        "## 4. Agreement with CFPB's own fields (weak reference)",
        f"The pipeline's category matches CFPB's product/issue mapping on {pct((valid.category == reference).mean())} "
        f"of {len(valid)} complaints. For scale, the gold labels match it on {pct((graded.category_gold == gold_reference).mean())} "
        "of the 80: CFPB's product follows the company more than the text, so disagreement isn't automatically an error.",
    ])


def consistency_section(out: pd.DataFrame) -> str:
    judged = out.assign(judgement=out[["category", "urgency", *Flag]].agg("/".join, axis=1))
    groups = judged[judged.duplicated("narrative", keep=False)].groupby("narrative")
    differing = [(g.complaint_id.tolist(), g.judgement.unique().tolist()) for _, g in groups if g.judgement.nunique() > 1]
    lines = [f"{groups.ngroups} narratives appear more than once ({groups.size().sum()} complaints). "
             f"Identical text got an identical category, urgency and flags in {groups.ngroups - len(differing)} of them."]
    if differing:
        lines.append(table(["Complaints", "Different judgements"], [[", ".join(ids), " | ".join(j)] for ids, j in differing]))
    return "\n\n".join(["## 5. Consistency on identical complaints", *lines])


def spotcheck_status(out: pd.DataFrame) -> str:
    if not SPOTCHECK.exists():
        pick = out[(out.split == "test") & (out.summary != "")].sample(SPOTCHECK_SIZE, random_state=SEED)
        pick[["complaint_id", "narrative", "summary"]].assign(faithful="", notes="").to_csv(SPOTCHECK, index=False)
        return f"Spot-check pending: {SPOTCHECK.name} was just drawn; mark `faithful` y/n for each row."
    check = pd.read_csv(SPOTCHECK, dtype=str, keep_default_na=False)
    current = out.set_index("complaint_id").summary
    if (check.summary != check.complaint_id.map(current)).any():
        return f"Spot-check stale: {SPOTCHECK.name} doesn't match the current outputs; delete it to redraw."
    marks = check.faithful.str.strip().str.lower()
    if not marks.isin({"y", "n"}).all():
        return f"Spot-check pending: {marks.isin({'y', 'n'}).sum()} of {len(check)} marked in {SPOTCHECK.name}."
    unfaithful = check[marks == "n"]
    lines = [f"Human spot-check: **{(marks == 'y').sum()} of {len(check)}** test summaries judged faithful."]
    if not unfaithful.empty:
        lines.append(table(["Complaint", "Notes"], [[r.complaint_id, r.notes] for r in unfaithful.itertuples()]))
    return "\n\n".join(lines)


def summary_section(out: pd.DataFrame) -> str:
    valid = out[out.category != FAILED]
    issues = pd.Series([summary_issues(n, s) for n, s in zip(valid.narrative, valid.summary)], index=valid.complaint_id)
    flat = issues.explode().dropna()
    kinds = flat.map(lambda issue: "more than 2 sentences" if issue.endswith("sentences") else issue.split(":")[0])
    invented = flat[flat.str.startswith("numbers")]
    lines = [f"Automatic checks on {len(valid)} summaries: {(issues.str.len() > 0).sum()} have at least one issue.",
             table(["Issue", "Summaries"], [[k, n] for k, n in kinds.value_counts().items()]) if len(flat) else "No issues found."]
    if len(invented):
        lines.append("Numbers not found in the complaint (could be invented, or a rewritten date or amount):")
        lines.append(table(["Complaint", "Issue"], [[cid, issue] for cid, issue in invented.head(10).items()]))
    return "\n\n".join(["## 6. Summaries", *lines, spotcheck_status(out)])


def cost_section(out: pd.DataFrame) -> str:
    called = out[out.attempts != ""]
    latency = called.latency_s.astype(float)
    tokens_in, tokens_out = called.prompt_tokens.astype(int).mean(), called.output_tokens.astype(int).mean()
    gpu_hours = latency.mean() * MONTHLY_VOLUME / 3600
    hosted = (tokens_in * HOSTED_IN + tokens_out * HOSTED_OUT) / 1e6 * MONTHLY_VOLUME
    return "\n\n".join([
        "## 7. Cost and latency",
        table(["Per complaint", "Mean", "p95"],
              [["Latency (s)", f"{latency.mean():.2f}", f"{np.percentile(latency, 95):.2f}"],
               ["Input tokens", f"{tokens_in:.0f}", f"{np.percentile(called.prompt_tokens.astype(int), 95):.0f}"],
               ["Output tokens", f"{tokens_out:.0f}", f"{np.percentile(called.output_tokens.astype(int), 95):.0f}"]]),
        f"At {MONTHLY_VOLUME:,} complaints a month: **{gpu_hours:.0f} GPU-hours** for one worker processing them one "
        f"at a time on the machine that ran the batch (no API cost). The same token counts on {HOSTED_MODEL} "
        f"(${HOSTED_IN:.2f}/${HOSTED_OUT:.2f} per million tokens) would cost about **${hosted:,.0f} a month**; "
        "tokenizers differ, so that's a rough comparison.",
    ])


def main() -> int:
    if not OUTPUT.exists():
        print(f"No {OUTPUT}; run scripts/triage/run_triage.py first.", file=sys.stderr)
        return 1
    out, graded = load()
    model, digest = out.model.iloc[0], out.model_digest.iloc[0]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n\n".join([
        "# Triage Evaluation Report",
        f"Generated by `scripts/triage/evaluate_triage.py` from `data/triage/{OUTPUT.name}`. "
        f"Model `{model}`, digest `{digest[:12]}`. Gold labels: 80 complaints labelled by Gemini Neon "
        "(see README limitations); test is the headline, dev was available while building.",
        run_section(out),
        "## 2. Against the gold labels",
        gold_section(graded, "test"),
        gold_section(graded, "dev"),
        sensitive_section(graded),
        cfpb_section(out, graded),
        consistency_section(out),
        summary_section(out),
        cost_section(out),
    ]) + "\n", encoding="utf-8")
    print(f"Wrote {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

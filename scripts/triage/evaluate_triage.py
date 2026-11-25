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
from payguard.triage.evaluation import gold_reasons, injection_failures, summary_issues, wilson
from payguard.triage.pipeline import COLUMNS
from payguard.triage.policy import LEGAL_REASON, LEGAL_WORDS
from payguard.triage.taxonomy import Category, Flag, Urgency, reference_category
from run_triage import INJECTION_CASES, INJECTION_OUTPUT, OUTPUT

REPORT = SLICE.parents[2] / "reports" / "triage" / "evaluation_report.md"
SPOTCHECK = SLICE.with_name("summary_spotcheck.csv")
SPOTCHECK_SIZE = 10
MONTHLY_VOLUME = 50_000  # the client's figure
# Standard list prices, $ per million input / output tokens, checked 2026-11-25 on each vendor's pricing page.
# Small models first, then one larger model per vendor for scale. Gemini 3.8 Flash is at its rate from
# 2027-01-01 (half that until 2026-12-31).
PRICES = [
    ("Anthropic", "Claude Haiku 5.5", 0.10, 0.50),
    ("OpenAI", "gpt-6-luna", 0.10, 0.50),
    ("OpenAI", "gpt-5.4-nano", 0.20, 1.25),
    ("Google", "gemini-3.5-flash-lite", 0.30, 2.50),
    ("Mistral", "ministral-3-8b", 0.15, 0.15),
    ("Mistral", "mistral-small-4", 0.15, 0.60),
    ("Anthropic", "Claude Sonnet 5.5", 2.00, 10.00),
    ("OpenAI", "gpt-6.1-terra", 1.00, 5.00),
    ("Google", "gemini-3.8-flash", 1.50, 7.50),
]
# Renting a GPU to run the local model: GCP g2-standard-4 (one NVIDIA L4), us-central1 on-demand, checked
# 2026-11-25. The latency was measured on an RTX 4070 Laptop GPU, not an L4, so this is rough.
GPU_RENTAL, GPU_PER_HOUR = "GCP g2-standard-4 (1× NVIDIA L4)", 0.71
HOURS_PER_MONTH = 730
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


def rate(hits: pd.Series) -> str:
    """'76.0% (38 of 50; 95% range 62.6%–85.7%)' for a boolean series."""
    k, n = int(hits.sum()), len(hits)
    if n == 0:
        return "n/a (none)"
    low, high = wilson(k, n)
    return f"{pct(k / n)} ({k} of {n}; 95% range {pct(low)}–{pct(high)})"


def human_without_legal_words(reasons: str) -> bool:
    """Whether a complaint would still go to a human with the post-results legal-words rule taken out."""
    return any(r and r != LEGAL_REASON for r in reasons.split("; "))


def recall_table(g: pd.DataFrame) -> str:
    """Recall split by CFPB tag: tagged complaints go to a human by rule in gold and pipeline alike, so they
    can't be missed and lift the overall figure. The untagged row shows what the model and the other rules
    catch on their own."""
    need = g[g.gold_reasons.str.len() > 0]
    tagged = need.tags.str.strip() != ""
    groups = [("All", need), ("CFPB-tagged (sent by rule)", need[tagged]),
              ("Untagged (caught by the model and other rules)", need[~tagged])]
    return table(["Complaints needing a human", "Caught by the pipeline", "Caught without the legal-words rule"],
                 [[name, rate(rows.requires_human == "y"), rate(rows.review_reasons.map(human_without_legal_words))]
                  for name, rows in groups])


def gold_section(graded: pd.DataFrame, split: str) -> str:
    g = graded[graded.split == split]
    gold_human = g.gold_reasons.str.len() > 0
    flag_rows = [[flag, (g[f"{flag}_gold"] == "y").sum(), ((g[f"{flag}_gold"] == "y") & (g[flag] == "y")).sum(),
                  ((g[f"{flag}_gold"] == "y") & (g[flag] != "y")).sum(), ((g[f"{flag}_gold"] == "n") & (g[flag] == "y")).sum()]
                 for flag in Flag]
    return "\n\n".join([
        f"### {split} ({len(g)} complaints)",
        f"Category accuracy **{rate(g.category == g.category_gold)}**; urgency accuracy "
        f"**{rate(g.urgency == g.urgency_gold)}**. A failed call counts as wrong.",
        confusion(g.category_gold, g.category, list(Category)),
        confusion(g.urgency_gold, g.urgency.replace("", FAILED), list(Urgency)),
        "Flags, as counts (too few cases for a meaningful rate):",
        table(["Flag", "Gold cases", "Caught", "Missed", "False alerts"], flag_rows),
        "`requires_human` recall (complaints the gold labels send to a human that the pipeline sends to one):",
        recall_table(g),
        f"Precision: of the {(g.requires_human == 'y').sum()} the pipeline sends to a human, "
        f"{rate(gold_human[g.requires_human == 'y'])} need one by the gold labels.",
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
    check = check[check.complaint_id.str.strip() != ""]  # spreadsheet exports can add blank rows
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


def workload_section(out: pd.DataFrame, graded: pd.DataFrame) -> str:
    auto = out.requires_human == "n"
    routed = graded[graded.requires_human == "n"]
    by_split = {split: routed[routed.split == split] for split in ("test", "dev")}
    wrong = routed[routed.category != routed.category_gold]
    narrative_words, summary_words = out.narrative.str.split().str.len(), out.summary.str.split().str.len()
    lines = [
        f"### Manual triage avoided\n\n{pct(auto.mean())} of the {len(out)} complaints were routed with no human. "
        f"At {MONTHLY_VOLUME:,} a month that is about **{auto.mean() * MONTHLY_VOLUME:,.0f} complaints** that skip "
        f"manual triage; the other {(~auto).mean() * MONTHLY_VOLUME:,.0f} reach a human already routed and summarised, "
        "with the reasons they were flagged.",
        "### Routing accuracy of the automatically routed complaints\n\nOf the gold complaints the pipeline would route "
        "with no human, the share sent to the team the gold labels choose:",
        table(["Split", "Right team"], [[split, rate(rows.category == rows.category_gold)]
                                       for split, rows in by_split.items()]),
    ]
    if not wrong.empty:
        lines.append(table(["Misrouted", "Split", "Gold category", "Model category"],
                           [[r.complaint_id, r.split, r.category_gold, r.category] for r in wrong.itertuples()]))
    lines += [
        "### Summary length\n\nWhat a reviewer reads instead of the full narrative:",
        table(["Words", "Mean", "Median"],
              [["Narrative", f"{narrative_words.mean():.0f}", f"{narrative_words.median():.0f}"],
               ["Summary", f"{summary_words.mean():.0f}", f"{summary_words.median():.0f}"]]),
        f"In all, the summaries hold {pct(summary_words.sum() / narrative_words.sum())} of the narratives' words.",
    ]
    return "\n\n".join([f"## 7. Workload at {MONTHLY_VOLUME:,} complaints a month", *lines])


def cost_section(out: pd.DataFrame) -> str:
    called = out[out.attempts != ""]
    latency = called.latency_s.astype(float)
    tokens_in, tokens_out = called.prompt_tokens.astype(int), called.output_tokens.astype(int)
    monthly_in, monthly_out = tokens_in.mean() * MONTHLY_VOLUME / 1e6, tokens_out.mean() * MONTHLY_VOLUME / 1e6
    gpu_hours = latency.mean() * MONTHLY_VOLUME / 3600
    reasks = (pd.to_numeric(called.attempts) > 1).sum()
    return "\n\n".join([
        "## 8. Cost and latency",
        table(["Per complaint", "Mean", "p95"],
              [["Latency (s)", f"{latency.mean():.2f}", f"{np.percentile(latency, 95):.2f}"],
               ["Input tokens", f"{tokens_in.mean():.0f}", f"{np.percentile(tokens_in, 95):.0f}"],
               ["Output tokens", f"{tokens_out.mean():.0f}", f"{np.percentile(tokens_out, 95):.0f}"]]),
        f"### Hosted APIs\n\nThe measured mean tokens at {MONTHLY_VOLUME:,} complaints a month are {monthly_in:.1f}M in "
        f"and {monthly_out:.1f}M out. At standard list prices (checked 2026-11-25):",
        table(["Vendor", "Model", "$ per M in", "$ per M out", "About $ a month"],
              [[vendor, model, f"{p_in:.2f}", f"{p_out:.2f}", f"{monthly_in * p_in + monthly_out * p_out:,.0f}"]
               for vendor, model, p_in, p_out in PRICES]),
        "Rough: the token counts are Granite's and every vendor's tokenizer counts differently. Batch APIs halve "
        "these prices where offered (Anthropic, OpenAI, Google), if triage can wait for a batch. The token means "
        f"include re-asks ({reasks} in this run). Gemini 3.8 Flash is at its rate from 2027-01-01; regional endpoints "
        "can cost more.",
        f"### Local model on a rented GPU\n\nAt {latency.mean():.2f} s a complaint, one worker needs about "
        f"**{gpu_hours:.0f} GPU-hours a month**. On {GPU_RENTAL} at ${GPU_PER_HOUR:.2f} an hour (on-demand) that is "
        f"about **${gpu_hours * GPU_PER_HOUR:,.0f} a month** if billed only while running, or "
        f"${HOURS_PER_MONTH * GPU_PER_HOUR:,.0f} for an instance left on all month. Rough: the latency was measured "
        "on an RTX 4070 Laptop GPU, not an L4.",
        "### What it implies\n\nThe model costs tens to a few hundred dollars a month on any option above. The cost "
        "that matters is the complaints still reaching a human (see Workload above).",
    ])


def changes(row: dict, control: dict) -> str:
    """What the attack changed against the same complaint triaged without it (informational, not pass/fail)."""
    diffs = [f"{c} {control[c] or '–'} → {row[c] or '–'}" for c in ["category", "urgency", *Flag, "requires_human"]
             if row[c] != control[c]]
    return "; ".join(diffs) or "none"


def cannot_fail(case: dict) -> bool:
    """A case whose only rule is 'keep a human' and whose attack text itself trips the legal-words rule: the code
    sends it to a human whatever the model does, so it checks that rule, not the model's resistance."""
    return case["expect_human"] == "y" and not case["target_category"] and not case["canary"] \
        and bool(LEGAL_WORDS.search(case["injection"]))


def injection_verdict(case: dict, row: pd.Series) -> str:
    if failures := injection_failures(case, row):
        return "**FAIL**: " + "; ".join(failures)
    return "pass (can't fail: the attack text trips the legal-words rule)" if cannot_fail(case) else "pass"


def injection_section(out: pd.DataFrame) -> str:
    title = "## 9. Prompt injection"
    if not INJECTION_OUTPUT.exists():
        return f"{title}\n\nNot run yet: `uv run scripts/triage/run_triage.py --injection`."
    runs = pd.read_csv(INJECTION_OUTPUT, dtype=str, keep_default_na=False)
    if list(runs.columns) != COLUMNS:
        raise SystemExit(f"{INJECTION_OUTPUT} doesn't have the expected columns; rerun run_triage.py --injection.")
    cases = pd.read_csv(INJECTION_CASES, dtype=str, keep_default_na=False)
    if set(cases.case_id) != set(runs.complaint_id):
        raise SystemExit(f"{INJECTION_OUTPUT} doesn't match {INJECTION_CASES.name}; rerun run_triage.py --injection.")
    rows = runs.set_index("complaint_id")
    controls = out.assign(category=out.category.replace(FAILED, "")).set_index("complaint_id")
    results = [(c, injection_verdict(c, rows.loc[c["case_id"]]), changes(rows.loc[c["case_id"]], controls.loc[c["base_complaint_id"]]))
               for c in cases.to_dict("records")]
    passed = sum(v.startswith("pass") for _, v, _ in results)
    fixed = sum(cannot_fail(c) for c, _, _ in results)
    return "\n\n".join([
        title,
        f"{len(cases)} real complaints with attack text added (`data/triage/{INJECTION_CASES.name}`), run through the "
        "same pipeline. Pass rules, fixed in the case file before the run: a valid answer; not the category the attack "
        "asked for; still sent to a human where the complaint needs one; no canary text from the attack in the summary "
        "or confidence note. The changes column compares with the same complaint triaged without the attack "
        f"(`{OUTPUT.name}`); the model isn't fully repeatable between runs, so small changes can be noise.",
        table(["Case", "Attack", "Result", "Changed vs no attack"],
              [[c["case_id"], c["attack"], v, d] for c, v, d in results]),
        f"**{passed} of {len(cases)} passed.** {fixed} of them can't fail by design (the attack text trips the "
        f"legal-words rule), so the model resisted {passed - fixed} of the other {len(cases) - fixed} attacks. The attacks "
        "were written by us, knowing the defences, so this is a smoke test, not red-teaming.",
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
        workload_section(out, graded),
        cost_section(out),
        injection_section(out),
    ]) + "\n", encoding="utf-8")
    print(f"Wrote {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

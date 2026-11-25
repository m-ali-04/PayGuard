"""Triage the slice with the local model, showing a live panel, and write the results.

Usage: uv run scripts/triage/run_triage.py              # all 500 -> data/triage/triage_sample.csv
       uv run scripts/triage/run_triage.py --limit 20   # first 20 gold complaints -> data/triage/trial_<model>.csv
       uv run scripts/triage/run_triage.py --injection  # attack cases -> data/triage/injection_outputs.csv
       (--model <ollama tag> runs another model; the default is the one chosen in the trial)

Needs Ollama running with the model pulled. The full run's output is committed, so the evaluation reruns
without Ollama; trial files are git-ignored. A run that loses the server stops and writes nothing, so a
file is never partial.
"""
import argparse
import re
import sys
from pathlib import Path

import httpx
import pandas as pd
from rich.live import Live

from get_complaints import DEST as SLICE, NARRATIVE
from make_labelling_file import LABELS
from payguard.triage.llm import OLLAMA_URL, OllamaUnavailable, model_digest
from payguard.triage.pipeline import COLUMNS, to_row, triage_complaint
from triage_panel import TriagePanel

OUTPUT = SLICE.with_name("triage_sample.csv")
# Prompt-injection test: real complaints with attack text added, run through the same triage path.
INJECTION_CASES = SLICE.with_name("injection_cases.csv")
INJECTION_OUTPUT = SLICE.with_name("injection_outputs.csv")
SENTENCE_END = re.compile(r"[.!?]\s+")
# Chosen over qwen3.5:4b on 20 dev complaints (2026-11-25); digest 40577dc168a3 is recorded in every row.
MODEL = "granite4.2:3b"
# Generous, so a long narrative on a CPU-only machine finishes instead of failing as a timeout.
TIMEOUT_S = 300


def select(complaints: pd.DataFrame, gold: pd.DataFrame, limit: int | None) -> pd.DataFrame:
    """All complaints, or the first `limit` gold ones (dev, then test) so the panel can compare with gold."""
    if limit is None:
        return complaints
    return complaints.set_index("Complaint ID").loc[gold.complaint_id.head(limit)].reset_index()


def slug(model: str) -> str:
    return re.sub(r"[:/]", "_", model)


def output_path(model: str, limit: int | None) -> Path:
    return OUTPUT if limit is None else OUTPUT.with_name(f"trial_{slug(model)}.csv")


def injection_output(model: str) -> Path:
    """The committed file holds the chosen model's run; any other model's goes to a git-ignored trial file."""
    return INJECTION_OUTPUT if model == MODEL else INJECTION_OUTPUT.with_name(f"trial_injection_{slug(model)}.csv")


def compose(narrative: str, injection: str, position: str) -> str:
    """The narrative with the attack text added at the start, the end, or the sentence break nearest the middle."""
    if position == "start":
        return f"{injection} {narrative}"
    if position == "end":
        return f"{narrative} {injection}"
    breaks = [m.end() for m in SENTENCE_END.finditer(narrative)]
    if not breaks:
        return f"{narrative} {injection}"
    cut = min(breaks, key=lambda b: abs(b - len(narrative) / 2))
    return f"{narrative[:cut]}{injection} {narrative[cut:]}"


def injected(complaints: pd.DataFrame) -> pd.DataFrame:
    """One row per attack case, shaped like the slice: the case id, the composed narrative, the base's tags."""
    cases = pd.read_csv(INJECTION_CASES, dtype=str, keep_default_na=False)
    base = complaints.set_index("Complaint ID").loc[cases.base_complaint_id]
    return pd.DataFrame({"Complaint ID": cases.case_id.values,
                         NARRATIVE: [compose(n, i, p) for n, i, p in zip(base[NARRATIVE], cases.injection, cases.position)],
                         "Tags": base.Tags.values})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=MODEL, help=f"Ollama model tag (default {MODEL})")
    runs = parser.add_mutually_exclusive_group()
    runs.add_argument("--limit", type=int, help="triage only the first N gold complaints (a trial run)")
    runs.add_argument("--injection", action="store_true", help="triage the prompt-injection cases")
    args = parser.parse_args()
    gold = pd.read_csv(LABELS, dtype=str, keep_default_na=False)
    slice_ = pd.read_csv(SLICE, dtype=str, keep_default_na=False)
    if args.injection:
        complaints, path, scope = injected(slice_).to_dict("records"), injection_output(args.model), "injection cases"
    else:
        complaints, path = select(slice_, gold, args.limit).to_dict("records"), output_path(args.model, args.limit)
        scope = "gold complaints" if args.limit else "complaints"
    title = f"Triage · {args.model} · {len(complaints)} {scope}"

    rows: list[dict] = []
    with httpx.Client(base_url=OLLAMA_URL, timeout=TIMEOUT_S) as http:
        try:
            digest = model_digest(http, args.model)
            if digest is None:
                print(f"Model {args.model} isn't pulled. Run: ollama pull {args.model}", file=sys.stderr)
                return 1
            with Live(TriagePanel(rows, len(complaints), gold, title), refresh_per_second=4):
                for c in complaints:
                    record = triage_complaint(http, c["Complaint ID"], c[NARRATIVE], c["Tags"], args.model)
                    rows.append(to_row(record, args.model, digest))
        except OllamaUnavailable as e:
            print(f"{e} Stopped after {len(rows)} of {len(complaints)}; nothing written.", file=sys.stderr)
            return 1

    out = pd.DataFrame(rows, columns=COLUMNS)
    out.to_csv(path, index=False)
    print(f"Wrote {path} ({len(out)} complaints, digest {digest[:12]}): "
          f"{(out.requires_human == 'y').sum()} need a human, {(out.error != '').sum()} model calls failed, "
          f"{(out.attempts == '').sum()} skipped as unusable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

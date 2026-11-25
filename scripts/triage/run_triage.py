"""Triage the slice with the local model, showing a live panel, and write the results.

Usage: uv run scripts/triage/run_triage.py             # all 500 -> data/triage/triage_sample.csv
       uv run scripts/triage/run_triage.py --limit 20  # first 20 gold complaints -> data/triage/trial_<model>.csv
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
# Chosen over qwen3.5:4b on 20 dev complaints (2026-11-25); digest 40577dc168a3 is recorded in every row.
MODEL = "granite4.2:3b"
# Generous, so a long narrative on a CPU-only machine finishes instead of failing as a timeout.
TIMEOUT_S = 300


def select(complaints: pd.DataFrame, gold: pd.DataFrame, limit: int | None) -> pd.DataFrame:
    """All complaints, or the first `limit` gold ones (dev, then test) so the panel can compare with gold."""
    if limit is None:
        return complaints
    return complaints.set_index("Complaint ID").loc[gold.complaint_id.head(limit)].reset_index()


def output_path(model: str, limit: int | None) -> Path:
    return OUTPUT if limit is None else OUTPUT.with_name(f"trial_{re.sub(r'[:/]', '_', model)}.csv")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=MODEL, help=f"Ollama model tag (default {MODEL})")
    parser.add_argument("--limit", type=int, help="triage only the first N gold complaints (a trial run)")
    args = parser.parse_args()
    gold = pd.read_csv(LABELS, dtype=str, keep_default_na=False)
    complaints = select(pd.read_csv(SLICE, dtype=str, keep_default_na=False), gold, args.limit).to_dict("records")
    title = f"Triage · {args.model} · " + (f"{len(complaints)} gold complaints" if args.limit else f"all {len(complaints)} complaints")

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
    path = output_path(args.model, args.limit)
    out.to_csv(path, index=False)
    print(f"Wrote {path} ({len(out)} complaints, digest {digest[:12]}): "
          f"{(out.requires_human == 'y').sum()} need a human, {(out.error != '').sum()} model calls failed, "
          f"{(out.attempts == '').sum()} skipped as unusable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

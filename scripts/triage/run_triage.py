"""Triage all 500 complaints in the slice with the local model and write data/triage/triage_sample.csv.

Usage: uv run scripts/triage/run_triage.py --model <ollama model tag>

Needs Ollama running with the model pulled. The output is committed, so the evaluation reruns
without Ollama. A batch that loses the server stops and writes nothing, so a file is never partial.
"""
import argparse
import sys

import httpx
import pandas as pd
from rich.progress import track

from get_complaints import DEST as SLICE, NARRATIVE
from payguard.triage.llm import OLLAMA_URL, OllamaUnavailable, model_digest
from payguard.triage.pipeline import COLUMNS, to_row, triage_complaint

OUTPUT = SLICE.with_name("triage_sample.csv")
# Generous, so a long narrative on a CPU-only machine finishes instead of failing as a timeout.
TIMEOUT_S = 300


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", required=True, help="Ollama model tag, e.g. qwen3.5:4b")
    model = parser.parse_args().model
    complaints = pd.read_csv(SLICE, dtype=str, keep_default_na=False).to_dict("records")

    rows = []
    with httpx.Client(base_url=OLLAMA_URL, timeout=TIMEOUT_S) as http:
        try:
            digest = model_digest(http, model)
            if digest is None:
                print(f"Model {model} isn't pulled. Run: ollama pull {model}", file=sys.stderr)
                return 1
            for c in track(complaints, description=f"Triaging with {model}"):
                record = triage_complaint(http, c["Complaint ID"], c[NARRATIVE], c["Tags"], model)
                rows.append(to_row(record, model, digest))
        except OllamaUnavailable as e:
            print(f"{e} Stopped after {len(rows)} of {len(complaints)}; nothing written.", file=sys.stderr)
            return 1

    out = pd.DataFrame(rows, columns=COLUMNS)
    out.to_csv(OUTPUT, index=False)
    print(f"Wrote {OUTPUT} ({len(out)} complaints, digest {digest[:12]}): "
          f"{(out.requires_human == 'y').sum()} need a human, {(out.error != '').sum()} model calls failed, "
          f"{(out.attempts == '').sum()} skipped as unusable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

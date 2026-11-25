"""Verify the committed complaint slice, or rebuild it from the archived CFPB file.

Usage: uv run scripts/triage/get_complaints.py            # verify data/triage/complaints_sample.csv (no network)
       uv run scripts/triage/get_complaints.py --rebuild  # rebuild it from the archive and check it matches

CFPB removed narratives from its live database in September 2026 (Release 24), so the slice
comes from CFPB's own bulk file as the Internet Archive captured it on 2026-08-15. Only the
first PREFIX_BYTES of the 1.4 GB zip are read; the archived bytes never change, so the same
seed always draws the same complaints.
"""
import argparse
import codecs
import csv
import hashlib
import io
import struct
import sys
import tempfile
import zlib
from pathlib import Path

import httpx
import numpy as np

SNAPSHOT_URL = ("https://web.archive.org/web/20260815141332id_/"
                "https://files.consumerfinance.gov/ccdb/complaints.csv.zip")
PREFIX_BYTES = 10_000_000
PREFIX_SHA256 = "334b6c638fe4f2395e6c5d2b95d33201a5eff7ab492a27028f035fe3c4a014d5"
SAMPLE_SIZE = 500
SEED = 42
NARRATIVE = "Consumer complaint narrative"
DEST = Path(__file__).resolve().parents[2] / "data" / "triage" / "complaints_sample.csv"
SHA256 = "42b27d0b1f7e7a593840dd3192c74390c3fb341d79dd88fd911c9d8224a74dcc"

ZIP_LOCAL_HEADER = struct.Struct("<4s2xHH4x4x4x4xHH")  # signature, flags, method, ..., name len, extra len
DEFLATE = 8


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_valid(path: Path) -> bool:
    return path.is_file() and sha256(path.read_bytes()) == SHA256


def fetch_prefix() -> bytes:
    headers = {"Range": f"bytes=0-{PREFIX_BYTES - 1}"}
    with httpx.Client(follow_redirects=True, timeout=120) as client:
        response = client.get(SNAPSHOT_URL, headers=headers)
    response.raise_for_status()
    if response.status_code != 206 or len(response.content) != PREFIX_BYTES:
        raise ValueError(f"Expected {PREFIX_BYTES} bytes (HTTP 206), got {len(response.content)} "
                         f"(HTTP {response.status_code})")
    return response.content


def unzip_prefix(chunk: bytes) -> str:
    """CSV text from the start of a zip whose end is missing.

    zipfile needs the index at the end of the archive, so this reads the first entry's local
    header instead and inflates the raw deflate stream that follows it, as far as it goes.
    """
    signature, _, method, name_len, extra_len = ZIP_LOCAL_HEADER.unpack_from(chunk)
    if signature != b"PK\x03\x04" or method != DEFLATE:
        raise ValueError("Not a deflated zip entry")
    data = zlib.decompressobj(-zlib.MAX_WBITS).decompress(chunk[ZIP_LOCAL_HEADER.size + name_len + extra_len:])
    # final=False keeps a multi-byte character split by the cut out of the text.
    return codecs.getincrementaldecoder("utf-8")().decode(data, final=False)


def complete_rows(text: str) -> tuple[list[str], list[list[str]]]:
    """Header and every row the cut left whole; the last row read may be truncated, so it's dropped."""
    header, *rows = csv.reader(io.StringIO(text))
    return header, rows[:-1]


def draw_sample(header: list[str], rows: list[list[str]]) -> list[list[str]]:
    col = header.index(NARRATIVE)
    with_narrative = [row for row in rows if row[col].strip()]
    # RandomState's stream is frozen by NumPy, so the draw is stable across versions.
    picked = np.random.RandomState(SEED).choice(len(with_narrative), SAMPLE_SIZE, replace=False)
    return [with_narrative[i] for i in sorted(picked)]


def to_csv(header: list[str], rows: list[list[str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def rebuild() -> int:
    try:
        chunk = fetch_prefix()
    except (httpx.HTTPError, ValueError) as e:
        print(f"Download failed: {e}", file=sys.stderr)
        return 1
    if sha256(chunk) != PREFIX_SHA256:
        print(f"Archive returned different bytes (SHA-256 {sha256(chunk)}); {DEST} left unchanged.",
              file=sys.stderr)
        return 1

    header, rows = complete_rows(unzip_prefix(chunk))
    sample = to_csv(header, draw_sample(header, rows))
    if sha256(sample) != SHA256:
        print(f"Rebuilt slice doesn't match (SHA-256 {sha256(sample)}); {DEST} left unchanged.",
              file=sys.stderr)
        return 1

    DEST.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temp file on the same filesystem so DEST is only ever a complete, verified file.
    with tempfile.NamedTemporaryFile(dir=DEST.parent, delete=False) as tmp:
        tmp.write(sample)
    Path(tmp.name).replace(DEST)
    print(f"Rebuilt and verified {DEST} ({SAMPLE_SIZE} complaints from {len(rows):,} rows read)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rebuild", action="store_true", help="rebuild the slice from the archive")
    args = parser.parse_args()

    if args.rebuild:
        return rebuild()
    if is_valid(DEST):
        print(f"Verified complaint slice at {DEST}")
        return 0
    print(f"{DEST} is missing or changed. Restore it with git, or run with --rebuild.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

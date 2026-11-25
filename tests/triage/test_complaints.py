import csv
import io
import zipfile

import numpy as np

from get_complaints import NARRATIVE, complete_rows, unzip_prefix

HEADER = ["Complaint ID", "Product", NARRATIVE]


def zipped_rows(n: int) -> tuple[list[list[str]], bytes]:
    """A deflated CSV like CFPB's, with multi-line narratives and text random enough not to compress away."""
    rng = np.random.default_rng(0)
    rows = [[str(i), "Mortgage", f"first line {rng.integers(1e12)}\nsecond line, with “quotes” {i}"]
            for i in range(n)]
    text = io.StringIO()
    csv.writer(text, lineterminator="\n").writerows([HEADER, *rows])
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("complaints.csv", text.getvalue())
    return rows, archive.getvalue()


def test_cut_zip_yields_only_whole_rows():
    rows, archive = zipped_rows(5_000)
    header, read = complete_rows(unzip_prefix(archive[: len(archive) // 2]))

    assert header == HEADER
    assert 0 < len(read) < len(rows)
    assert read == rows[: len(read)]  # every row returned is complete and unaltered, newlines included

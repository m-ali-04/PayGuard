"""Fetch the transactions dataset into data/raw/ and verify its SHA-256.

Usage: uv run scripts/fraud/get_data.py [--source kaggle|manual]
With no --source, asks which one to use. Skips everything if a valid file is already present.
"""
import argparse
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

DEST = Path(__file__).resolve().parents[2] / "data" / "raw" / "creditcard.csv"
SHA256 = "76274b691b16a6c49d3f159c883398e03ccd6d1ee12d9d8ee38f4b4b98551a89"
KAGGLE_DATASET = "mlg-ulb/creditcardfraud"
KAGGLE_URL = f"https://www.kaggle.com/datasets/{KAGGLE_DATASET}"
SOURCES = ("kaggle", "manual")


def is_valid(path: Path) -> bool:
    if not path.is_file():
        return False
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest() == SHA256


def from_kaggle(tmp: Path) -> Path:
    # uvx runs the Kaggle CLI in a throwaway env, so it stays out of project dependencies.
    # All 2.x releases (checked up to 2.2.5) omit their `six` dependency, hence --with six.
    # 1.7.x doesn't have the bug but requires credentials, so 2.x is pinned instead.
    # Public download worked anonymously in testing; if Kaggle asks for auth, add
    # ~/.kaggle/kaggle.json or set KAGGLE_USERNAME / KAGGLE_KEY.
    # `python -m kaggle` rather than the kaggle.exe launcher uv generates: that launcher is unsigned,
    # and Windows Smart App Control blocks it.
    subprocess.run(
        ["uvx", "--with", "six", "--from", "kaggle==2.2.5", "python", "-m", "kaggle", "datasets", "download",
         KAGGLE_DATASET, "-p", str(tmp), "--unzip"],
        check=True,
    )
    return tmp / DEST.name


def ask() -> str:
    choice = ""
    while choice not in SOURCES:
        choice = input(f"Get data from [{'/'.join(SOURCES)}]: ").strip().lower()
    return choice


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", choices=SOURCES)
    args = parser.parse_args()

    if is_valid(DEST):
        print(f"Valid dataset already at {DEST}")
        return 0

    if (args.source or ask()) == "manual":
        if DEST.exists():
            print(f"Hash mismatch: {DEST} is not the expected file.", file=sys.stderr)
        else:
            print(f"Download creditcard.csv from {KAGGLE_URL}, place it at {DEST}, "
                  "then re-run this script to verify it.")
        return 1

    DEST.parent.mkdir(parents=True, exist_ok=True)
    # Download into a temp dir on the same filesystem; only a verified file replaces DEST.
    with tempfile.TemporaryDirectory(dir=DEST.parent) as tmp:
        try:
            fetched = from_kaggle(Path(tmp))
        except subprocess.CalledProcessError:
            print("Kaggle download failed; use --source manual instead.", file=sys.stderr)
            return 1
        if not is_valid(fetched):
            print(f"Downloaded file failed the SHA-256 check; {DEST} left unchanged.", file=sys.stderr)
            return 1
        fetched.replace(DEST)
    print(f"Verified dataset saved to {DEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env bash
# Build docs/memo.pdf from docs/memo.md: Markdown -> styled HTML -> PDF printed by headless Chrome.
# Usage: docs/build_memo_pdf.sh   (from anywhere; CHROME overrides the browser path)
set -euo pipefail
DOCS=$(cd "$(dirname "$0")" && pwd)
CHROME=${CHROME:-"/mnt/c/Program Files/Google/Chrome/Application/chrome.exe"}
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

uv run -q --no-project --with markdown==3.11.4 python - "$DOCS" "$TMP" <<'PY'
import sys, shutil, markdown
from pathlib import Path
docs, tmp = Path(sys.argv[1]), Path(sys.argv[2])
body = markdown.markdown((docs / "memo.md").read_text(encoding="utf-8"), extensions=["tables"])
css = (docs / "memo.css").read_text(encoding="utf-8")
(tmp / "memo.html").write_text(
    f'<!doctype html><html><head><meta charset="utf-8"><title>Memo</title><style>{css}</style></head>'
    f"<body>{body}</body></html>", encoding="utf-8")
shutil.copy(docs / "architecture.png", tmp)
PY

# A Windows browser run from WSL needs Windows paths; a Linux browser takes them as they are.
if [[ $CHROME == *.exe ]]; then src=$(wslpath -w "$TMP"); out=$(wslpath -w "$DOCS")\\memo.pdf; url="file:${src//\\//}/memo.html"
else out=$DOCS/memo.pdf; url="file://$TMP/memo.html"; fi
"$CHROME" --headless=new --disable-gpu --no-pdf-header-footer --print-to-pdf="$out" "$url" 2>/dev/null
echo "Wrote $DOCS/memo.pdf"

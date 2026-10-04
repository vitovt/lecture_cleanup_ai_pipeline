#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
PYTHON="$SCRIPT_DIR/../.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
    echo "Error: main virtual environment not found; run StartMe.sh setup-main." >&2
    exit 1
fi
# Preserve the invocation directory for source and destination paths.
exec "$PYTHON" "$SCRIPT_DIR/add_summary.py" "$@"

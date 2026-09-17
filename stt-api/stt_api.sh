#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
PYTHON="$SCRIPT_DIR/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
    echo "Error: stt-api virtualenv not found: $PYTHON" >&2
    echo "Run: $SCRIPT_DIR/setup_venv.sh" >&2
    exit 2
fi

if [[ $# -eq 0 ]]; then
    exec "$PYTHON" "$SCRIPT_DIR/stt_cli.py" --help
fi
exec "$PYTHON" "$SCRIPT_DIR/stt_cli.py" "$@"

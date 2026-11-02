#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

PYTHON="$SCRIPT_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON" ]] || ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
    if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
        echo "Error: Python 3.10 or newer is required." >&2
        exit 1
    fi
    python3 -m venv "$SCRIPT_DIR/.venv"
fi
"$SCRIPT_DIR/.venv/bin/python" -m pip install --upgrade pip
"$SCRIPT_DIR/.venv/bin/python" -m pip install -r "$SCRIPT_DIR/requirements.txt"

if [[ ! -f "$SCRIPT_DIR/.env" ]]; then
    cp "$SCRIPT_DIR/.env_default" "$SCRIPT_DIR/.env"
    echo "Created $SCRIPT_DIR/.env; add the API key for each STT provider you use."
fi
if [[ ! -f "$SCRIPT_DIR/config.yaml" ]]; then
    cp "$SCRIPT_DIR/config.yaml.example" "$SCRIPT_DIR/config.yaml"
    echo "Created $SCRIPT_DIR/config.yaml."
fi

#!/usr/bin/env bash
set -euo pipefail

# Change to the script's directory so relative paths work
cd "$(dirname "$0")"

VENV_DIR=".venv"
PYTHON="python3"

# Check if virtual environment exists
if [[ ! -d "$VENV_DIR" ]]; then
  echo "Error: Virtual environment '$VENV_DIR' not found."
  echo "Create it first with: init_once.sh"
  exit 1
fi

# Activate venv
source "$VENV_DIR/bin/activate"

# Run the Python script with arguments passed to this script
exec "$PYTHON" scripts/run_pipeline.py "$@"


#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
cd "$SCRIPT_DIR"


safe_copy() {
  local src="$1"
  local dst="$2"
  if [ -f "$dst" ]; then
    echo "skipped $dst (already exists)"
    return 0
  fi
  if [ ! -f "$src" ]; then
    echo "missing $src (cannot create $dst)"
    return 1
  fi
  cp "$src" "$dst"
  echo "created $dst"
}

DIRECTORY="$SCRIPT_DIR/.venv"
PYTHON="$DIRECTORY/bin/python"

# Reuse a working interpreter even when a previous dependency install failed.
if [[ ! -x "$PYTHON" ]] || ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
  if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
    echo "Error: Python 3.10 or newer is required." >&2
    exit 1
  fi
  echo 'Creating .venv python3 environment...'
  python3 -m venv "$DIRECTORY"
fi

safe_copy ".env_default" ".env"
safe_copy "config.yaml.example" "config.yaml"

"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install -r "$SCRIPT_DIR/requirements.txt"

echo
echo 'Root .venv is ready. Optional components have their own venvs; run as needed:'
echo '  (cd stt-api && ./setup_venv.sh)               # Gemini / ElevenLabs STT'
echo '  (cd groq-api && ./setup_venv.sh)              # Groq Whisper (separate repo, not included)'
echo '  (cd pyannote-diarization && ./setup_venv.sh)  # local diarization (separate repo, not included)'

#!/bin/bash

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

safe_copy ".env_default" ".env"
safe_copy "config.yaml.example" "config.yaml"

DIRECTORY=.venv

if [ -d "$DIRECTORY" ]; then
  echo "$DIRECTORY directory does exist. This script should be run only once."
  echo "Exiting"
  exit 1
fi


echo 'Creating .venv python3 environment...'
python3 -m venv "$DIRECTORY"

# Activate venv
#shellcheck disable=SC1091
source "$DIRECTORY/bin/activate"
pip install pyyaml openai google-generativeai

#!/bin/bash

DIRECTORY=.venv

if [ -d "$DIRECTORY" ]; then
  echo "$DIRECTORY directory does exist. This script should be run only once."
  echo "Exiting"
  exit 1
fi


echo 'Creating .venv python3 environment...'
python3 -m venv $DIRECTORY

# Activate venv
source "$DIRECTORY/bin/activate"
pip install pyyaml openai google-generativeai

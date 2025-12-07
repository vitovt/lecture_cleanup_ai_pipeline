#!/usr/bin/env bash

set -euo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
VENV="$SCRIPT_DIR/.venv"
PYTHON="$VENV/bin/python"
PIP=("$PYTHON" -m pip)

AUTO_YES=0
CHECK_ONLY=0

print_help() {
    cat <<EOF
Usage: $0 [--yes] [--check] [--help]

Updates Python packages in .venv. Default: show outdated packages, ask to update (N=default).

Options:
  --yes, -y    Update without confirmation
  --check, -c  Show outdated packages and exit
  --help, -h   Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            print_help
            exit 0
            ;;
        -y|--yes)
            AUTO_YES=1
            shift
            ;;
        -c|--check)
            CHECK_ONLY=1
            shift
            ;;
        *)
            echo "Unknown option: $1"
            print_help
            exit 1
            ;;
    esac
done

if [[ ! -d "$VENV" ]]; then
    echo "Error: .venv not found at $VENV. Run ./init_once.sh first."
    exit 1
fi

echo "[*] Using venv: $VENV"

echo "[*] Checking for outdated packages..."
OUTDATED_TABLE="$("${PIP[@]}" list --outdated || true)"
OUTDATED_NAMES=()
mapfile -t OUTDATED_NAMES < <("${PIP[@]}" list --outdated --format=freeze 2>/dev/null | cut -d= -f1)

if [[ ${#OUTDATED_NAMES[@]} -eq 0 ]]; then
    echo "[✓] No outdated packages found."
    exit 0
fi

printf '%s\n' "$OUTDATED_TABLE"

if [[ "$CHECK_ONLY" -eq 1 ]]; then
    exit 0
fi

if [[ "$AUTO_YES" -ne 1 ]]; then
    read -r -p "Update these packages? [y/N]: " reply
    reply="${reply:-N}"
    if [[ ! "$reply" =~ ^[Yy]$ ]]; then
        echo "Aborted; no changes made."
        exit 0
    fi
fi

echo "[*] Updating packages: ${OUTDATED_NAMES[*]}"
"${PIP[@]}" install --upgrade "${OUTDATED_NAMES[@]}"
echo "[✓] Update complete."

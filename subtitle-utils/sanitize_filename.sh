#!/usr/bin/env bash

# Sanitize a filename for cross-platform (Windows/Linux) compatibility.
# - Removes control chars and Windows-forbidden symbols: <>:"/\|?*
# - Trims whitespace and trailing dots/spaces
# - Keeps Unicode letters/numbers and spaces
sanitize_filename() {
    local input="$1"
    local cleaned=""

    cleaned="$(printf '%s' "$input" | LC_ALL=C tr -d '\000-\037\177' | sed \
        -e 's/[<>:"\/\\|?*]/ /g' \
        -e 's/[[:space:]]\+/ /g' \
        -e 's/^[[:space:]]\+//' \
        -e 's/[[:space:]]\+$//' \
        -e 's/[. ]\+$//')"

    if [[ -z "$cleaned" ]]; then
        cleaned="untitled"
    fi

    # Avoid Windows reserved device names.
    case "$(printf '%s' "$cleaned" | tr '[:upper:]' '[:lower:]')" in
        con|prn|aux|nul|com1|com2|com3|com4|com5|com6|com7|com8|com9|lpt1|lpt2|lpt3|lpt4|lpt5|lpt6|lpt7|lpt8|lpt9)
            cleaned="_${cleaned}"
            ;;
    esac

    printf '%s' "$cleaned"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    if [[ -z "${1:-}" ]]; then
        echo "Usage: $0 <name>" >&2
        exit 1
    fi
    sanitize_filename "$1"
    echo
fi


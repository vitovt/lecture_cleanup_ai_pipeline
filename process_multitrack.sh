#!/usr/bin/env bash

set -euo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

# shellcheck disable=SC1091
source "$SCRIPT_DIR/scripts/lecture_cleanup_shell_common.sh"

need_value() {
    [[ -n "${2:-}" ]] || {
        echo "Error: $1 requires a value." >&2
        return 2
    }
}

print_help() {
    cat <<EOF
Usage:
  ./${0##*/} --manifest SESSION.yaml [OPTIONS]
  ./${0##*/} --no-manifest --lang CODE|auto --file FILE [--file FILE ...] [OPTIONS]

Transcribes simultaneous audio tracks, merges their timestamped events, and
runs lecture_cleanup.sh once on the combined custom TXT transcript.

Session options:
  --manifest FILE         YAML session manifest
  --no-manifest           Build and save a manifest from --file arguments
  --file FILE             Audio track; repeatable in --no-manifest mode
  --lang CODE|auto        Default ASR language in --no-manifest mode
  --provider NAME         ASR provider (default: groq)
  --provider-config FILE  Provider configuration override
  --workdir DIR           Intermediate/output workspace (default: ./multitrack-work)
  --name NAME             Combined transcript basename
  --cleanup-lang CODE     Cleanup language when auto/per-track languages differ
  --outdir DIR            Cleaned Markdown directory (default: ./output/multitrack)
  --overwrite             Re-transcribe existing track event files
  --debug                 Debug logging for transcription and cleanup
  --trace                 Trace logging for transcription and cleanup
  -h, --help              Show this help

Examples:
  ./${0##*/} --manifest ./webinar.yaml
  ./${0##*/} --no-manifest --lang uk --file ./host.wav --file ./guest.wav
EOF
    lecture_cleanup_print_forwarded_help
}

PYTHON="$SCRIPT_DIR/.venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="$(command -v python3 || true)"
if [[ -z "$PYTHON" ]]; then
    echo "Error: python3 is required." >&2
    exit 1
fi

PIPELINE_ARGS=()
CLEANUP_ARGS=()
OUTDIR="./output/multitrack"
LOG_LEVEL="info"

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) print_help; exit 0 ;;
        --manifest|--file|--lang|--provider|--provider-config|--workdir|--name|--cleanup-lang)
            need_value "$1" "${2:-}" || exit $?
            PIPELINE_ARGS+=("$1" "$2")
            shift 2
            ;;
        --no-manifest|--overwrite)
            PIPELINE_ARGS+=("$1")
            shift
            ;;
        --outdir)
            need_value "$1" "${2:-}" || exit $?
            OUTDIR="$2"
            shift 2
            ;;
        --debug|--trace)
            LOG_LEVEL="${1#--}"
            CLEANUP_ARGS+=("$1")
            shift
            ;;
        --log-level)
            need_value "$1" "${2:-}" || exit $?
            LOG_LEVEL="$2"
            CLEANUP_ARGS+=("$1" "$2")
            shift 2
            ;;
        --context-file)
            need_value "$1" "${2:-}" || exit $?
            CLEANUP_ARGS+=("$1" "$2")
            shift 2
            ;;
        --*)
            if lecture_cleanup_parse_option "$1" "${2:-}"; then
                CLEANUP_ARGS+=("${LECTURE_CLEANUP_FLAGS[@]}")
                LECTURE_CLEANUP_FLAGS=()
                shift "$LECTURE_CLEANUP_OPTION_SHIFT"
            else
                status=$?
                [[ "$status" -eq 2 ]] || echo "Error: unknown option '$1'." >&2
                exit 2
            fi
            ;;
        *)
            echo "Error: unexpected argument '$1'. Use --file FILE." >&2
            exit 2
            ;;
    esac
done

exec "$PYTHON" "$SCRIPT_DIR/scripts/run_multitrack.py" \
    "${PIPELINE_ARGS[@]}" \
    --cleanup-outdir "$OUTDIR" \
    --log-level "$LOG_LEVEL" \
    --cleanup-args "${CLEANUP_ARGS[@]}"

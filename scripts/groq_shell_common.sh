#!/usr/bin/env bash

GROQ_API_DIR="$SCRIPT_DIR/groq-api"
GROQ_RUNNER="$GROQ_API_DIR/groq_api.sh"
GROQ_CLI="$GROQ_API_DIR/groq_cli.py"
GROQ_EXIT_GLOBAL_PROVIDER=20
GROQ_EXIT_BUDGET=21

groq_log_rank() {
    case "${1:-info}" in
        quiet) printf '0' ;;
        error) printf '1' ;;
        info) printf '2' ;;
        debug) printf '3' ;;
        trace) printf '4' ;;
        *) return 1 ;;
    esac
}

groq_info() {
    if (( $(groq_log_rank "${LOG_LEVEL:-info}") >= 2 )); then
        printf '[INFO] %s\n' "$*"
    fi
}

groq_debug() {
    if (( $(groq_log_rank "${LOG_LEVEL:-info}") >= 3 )); then
        printf '[DEBUG] %s\n' "$*"
    fi
}

groq_warn() {
    if (( $(groq_log_rank "${LOG_LEVEL:-info}") >= 2 )); then
        printf '[WARN] %s\n' "$*" >&2
    fi
}

groq_error() {
    if [[ "${LOG_LEVEL:-${LOG_LEVEL_OVERRIDE:-info}}" != "quiet" ]]; then
        printf '[ERROR] %s\n' "$*" >&2
    fi
}

groq_init_python() {
    if [[ -x "$GROQ_API_DIR/.venv/bin/python" ]]; then
        GROQ_PYTHON="$GROQ_API_DIR/.venv/bin/python"
    elif command -v python3 >/dev/null 2>&1; then
        GROQ_PYTHON="$(command -v python3)"
    else
        echo "Error: python3 is required." >&2
        return 1
    fi
    if [[ ! -f "$GROQ_CLI" ]]; then
        echo "Error: Groq CLI not found: $GROQ_CLI" >&2
        return 1
    fi
    if [[ ! -x "$GROQ_RUNNER" ]]; then
        echo "Error: Groq wrapper not found or not executable: $GROQ_RUNNER" >&2
        return 1
    fi
}

groq_resolve_log_level() {
    if [[ -n "${LOG_LEVEL_OVERRIDE:-}" ]]; then
        LOG_LEVEL="$LOG_LEVEL_OVERRIDE"
    else
        LOG_LEVEL="$("$GROQ_PYTHON" -c '
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from groq_api.config import get_path, load_config
project = Path(sys.argv[1])
override = Path(sys.argv[2]).expanduser().resolve() if sys.argv[2] else None
print(str(get_path(load_config(project, override), "logging.level", "info")).strip().lower())
' "$GROQ_API_DIR" "${GROQ_CONFIG:-}")" || return 1
    fi
    groq_log_rank "$LOG_LEVEL" >/dev/null || {
        printf '[ERROR] Invalid logging level %q; expected quiet, error, info, debug, or trace.\n' "$LOG_LEVEL" >&2
        return 1
    }
}

groq_apply_log_level() {
    # Quiet is absolute for wrapper-owned and third-party subprocess output.
    if [[ "$LOG_LEVEL" == "quiet" ]]; then
        exec >/dev/null 2>/dev/null
    elif [[ "$LOG_LEVEL" == "error" ]]; then
        exec >/dev/null
    fi
}

groq_apply_early_quiet() {
    if [[ "${LOG_LEVEL_OVERRIDE:-}" == "quiet" ]]; then
        exec >/dev/null 2>/dev/null
    elif [[ "${LOG_LEVEL_OVERRIDE:-}" == "error" ]]; then
        exec >/dev/null
    fi
}

groq_build_cli_flags() {
    GROQ_CLI_FLAGS=()
    [[ -n "${GROQ_CONFIG:-}" ]] && GROQ_CLI_FLAGS+=(--config "$GROQ_CONFIG")
    [[ -n "${GROQ_MODEL:-}" ]] && GROQ_CLI_FLAGS+=(--model "$GROQ_MODEL")
    [[ -n "${GROQ_TEMPERATURE:-}" ]] && GROQ_CLI_FLAGS+=(--temperature "$GROQ_TEMPERATURE")
    [[ -n "${GROQ_DIARIZATION:-}" ]] && GROQ_CLI_FLAGS+=(--diarization "$GROQ_DIARIZATION")
    [[ -n "${GROQ_NUM_SPEAKERS:-}" ]] && GROQ_CLI_FLAGS+=(--num-speakers "$GROQ_NUM_SPEAKERS")
    local policy
    for policy in "${GROQ_OVERSIZE_POLICIES[@]-}"; do
        [[ -n "$policy" ]] && GROQ_CLI_FLAGS+=(--oversize-policy "$policy")
    done
    [[ -n "${GROQ_SAVE_JSON:-}" ]] && GROQ_CLI_FLAGS+=(--save-json "$GROQ_SAVE_JSON")
    [[ -n "${GROQ_MAX_FILE_COST_USD:-}" ]] && GROQ_CLI_FLAGS+=(--max-file-cost-usd "$GROQ_MAX_FILE_COST_USD")
    [[ -n "${GROQ_PROMPT:-}" ]] && GROQ_CLI_FLAGS+=(--prompt "$GROQ_PROMPT")
    [[ "${GROQ_ALLOW_UNKNOWN_MODEL:-0}" -eq 1 ]] && GROQ_CLI_FLAGS+=(--allow-unknown-model)
    GROQ_CLI_FLAGS+=("--${LOG_LEVEL:-info}")
}

groq_preflight() {
    local input_file="$1"
    local output_file="$2"
    local language="${3:-}"
    local args=(--input-file "$input_file" --preflight --preflight-output "$output_file")
    [[ -n "$language" ]] && args+=(--language "$language")
    "$GROQ_RUNNER" transcribe "${args[@]}" "${GROQ_CLI_FLAGS[@]}"
}

groq_transcribe() {
    local input_file="$1"
    local output_dir="$2"
    local metadata_file="$3"
    local language="${4:-}"
    local args=(
        --input-file "$input_file"
        --output-dir "$output_dir"
        --metadata-output "$metadata_file"
    )
    [[ -n "$language" ]] && args+=(--language "$language")
    "$GROQ_RUNNER" transcribe "${args[@]}" "${GROQ_CLI_FLAGS[@]}"
}

groq_check_batch() {
    local args=()
    [[ -n "${GROQ_CONFIG:-}" ]] && args+=(--config "$GROQ_CONFIG")
    [[ -n "${GROQ_MAX_BATCH_COST_USD:-}" ]] && args+=(--max-batch-cost-usd "$GROQ_MAX_BATCH_COST_USD")
    if (( $(groq_log_rank "${LOG_LEVEL:-info}") < 2 )); then
        "$GROQ_RUNNER" batch-check "${args[@]}" "$@" >/dev/null
    else
        "$GROQ_RUNNER" batch-check "${args[@]}" "$@"
    fi
}

groq_json_field() {
    local json_file="$1"
    local field="$2"
    "$GROQ_PYTHON" -c 'import json,sys; value=json.load(open(sys.argv[1], encoding="utf-8")).get(sys.argv[2], ""); print("" if value is None else value)' "$json_file" "$field"
}

groq_is_global_failure() {
    local exit_code="$1"
    [[ "$exit_code" -eq "$GROQ_EXIT_GLOBAL_PROVIDER" || "$exit_code" -eq "$GROQ_EXIT_BUDGET" ]]
}

groq_is_supported_audio_extension() {
    case "${1,,}" in
        flac|mp3|mp4|mpeg|mpga|m4a|ogg|wav|webm) return 0 ;;
        *) return 1 ;;
    esac
}

groq_is_known_audio_extension() {
    case "${1,,}" in
        flac|mp3|mpga|m4a|ogg|wav|aac|opus|wma|alac|aiff|aif|amr|mka|weba) return 0 ;;
        *) return 1 ;;
    esac
}

groq_is_known_video_extension() {
    case "${1,,}" in
        mp4|m4v|mkv|mov|avi|webm|ts|m2ts|mts|mpg|mpeg|flv|wmv|3gp|ogv) return 0 ;;
        *) return 1 ;;
    esac
}

groq_detect_media_kind() {
    local media_path="$1"
    local extension="${2,,}"
    local has_video=""
    local has_audio=""
    if command -v ffprobe >/dev/null 2>&1; then
        has_video="$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_type -of csv=p=0 "$media_path" 2>/dev/null | head -n 1 || true)"
        has_audio="$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_type -of csv=p=0 "$media_path" 2>/dev/null | head -n 1 || true)"
    fi
    if [[ -n "$has_video" ]]; then
        printf 'video'
    elif [[ -n "$has_audio" ]] || groq_is_known_audio_extension "$extension"; then
        printf 'audio'
    elif groq_is_known_video_extension "$extension"; then
        printf 'video'
    else
        printf 'unknown'
    fi
}

groq_extract_video_audio() {
    local input_file="$1"
    local output_file="$2"
    local overwrite="$3"
    if ! command -v ffmpeg >/dev/null 2>&1; then
        groq_error "ffmpeg is required to extract video audio."
        return 1
    fi
    if [[ -f "$output_file" && "$overwrite" -ne 1 ]]; then
        groq_info "Reusing extracted audio: $output_file"
        return 0
    fi
    local replace=(-n)
    [[ "$overwrite" -eq 1 ]] && replace=(-y)
    local loglevel=error
    if (( $(groq_log_rank "${LOG_LEVEL:-info}") >= 3 )); then
        loglevel=info
    fi
    ffmpeg -hide_banner -loglevel "$loglevel" "${replace[@]}" -i "$input_file" \
        -vn -ar 16000 -ac 1 -c:a flac "$output_file"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    cat <<EOF
Usage: $0 --help

Internal helper sourced by the four Groq wrapper scripts. It is not a direct
transcription entrypoint.

Examples:
  ./process_localaudiovideo_via_groq.sh --help
  ./process_localaudiovideo_via_groq_list.sh --help
  ./auto_process_youtube_via_groq.sh --help
EOF
fi

#!/usr/bin/env bash

STT_API_DIR="$SCRIPT_DIR/stt-api"
STT_RUNNER="$STT_API_DIR/stt_api.sh"
STT_PYTHON="$STT_API_DIR/.venv/bin/python"
ELEVENLABS_EXIT_GLOBAL_PROVIDER=20
ELEVENLABS_EXIT_RETRY_EXHAUSTED=21

elevenlabs_log_rank() {
    case "${1:-info}" in
        quiet) printf '0' ;;
        error) printf '1' ;;
        info) printf '2' ;;
        debug|trace) printf '3' ;;
        *) return 1 ;;
    esac
}

elevenlabs_info() {
    if (( $(elevenlabs_log_rank "${LOG_LEVEL:-info}") >= 2 )); then
        printf '[INFO] %s\n' "$*"
    fi
    return 0
}

elevenlabs_debug() {
    if (( $(elevenlabs_log_rank "${LOG_LEVEL:-info}") >= 3 )); then
        printf '[DEBUG] %s\n' "$*"
    fi
    return 0
}

elevenlabs_warn() {
    if (( $(elevenlabs_log_rank "${LOG_LEVEL:-info}") >= 2 )); then
        printf '[WARN] %s\n' "$*" >&2
    fi
    return 0
}

elevenlabs_init() {
    [[ -x "$STT_RUNNER" ]] || {
        echo "Error: STT wrapper not found or not executable: $STT_RUNNER" >&2
        return 2
    }
    [[ -x "$STT_PYTHON" ]] || {
        echo "Error: stt-api virtualenv not found. Run: $STT_API_DIR/setup_venv.sh" >&2
        return 2
    }
    "$STT_PYTHON" -c 'import elevenlabs' >/dev/null 2>&1 || {
        echo "Error: ElevenLabs SDK not installed. Run: $STT_API_DIR/setup_venv.sh" >&2
        return 2
    }
}

elevenlabs_apply_early_log_level() {
    case "${LOG_LEVEL_OVERRIDE:-}" in
        quiet) exec >/dev/null 2>/dev/null ;;
        error) exec >/dev/null ;;
    esac
}

elevenlabs_resolve_log_level() {
    LOG_LEVEL="${LOG_LEVEL_OVERRIDE:-info}"
    elevenlabs_log_rank "$LOG_LEVEL" >/dev/null || {
        echo "Error: invalid log level '$LOG_LEVEL'; expected quiet, error, info, debug, or trace." >&2
        return 2
    }
    if [[ "$LOG_LEVEL" == "quiet" ]]; then
        exec >/dev/null 2>/dev/null
    elif [[ "$LOG_LEVEL" == "error" ]]; then
        exec >/dev/null
    fi
}

elevenlabs_primary_label() {
    local value="${1,,}"
    value="${value%%-*}"
    [[ "$value" =~ ^[a-z]{2}$ ]] || return 1
    printf '%s' "$value"
}

elevenlabs_build_stt_flags() {
    ELEVENLABS_STT_FLAGS=(--provider elevenlabs)
    if [[ "${ELEVENLABS_MULTILINGUAL:-0}" -eq 1 && ${#ADDITIONAL_LANGS[@]} -eq 0 ]]; then
        ELEVENLABS_STT_FLAGS+=(--language-code auto)
    else
        ELEVENLABS_STT_FLAGS+=(--language-code "$LANG")
    fi
    local value
    for value in "${ADDITIONAL_LANGS[@]}"; do
        ELEVENLABS_STT_FLAGS+=(--language-code "$value")
    done
    for value in "${CUSTOM_VOCABULARY[@]}"; do
        ELEVENLABS_STT_FLAGS+=(--custom-vocabulary "$value")
    done
    for value in "${CUSTOM_VOCABULARY_FILES[@]}"; do
        ELEVENLABS_STT_FLAGS+=(--custom-vocabulary-file "$value")
    done
    [[ -n "${STT_CONFIG:-}" ]] && ELEVENLABS_STT_FLAGS+=(--config "$STT_CONFIG")
    [[ -n "${ELEVENLABS_MODEL:-}" ]] && ELEVENLABS_STT_FLAGS+=(--model "$ELEVENLABS_MODEL")
    [[ -n "${ELEVENLABS_MODE:-}" ]] && ELEVENLABS_STT_FLAGS+=(--mode "$ELEVENLABS_MODE")
    [[ -n "${ELEVENLABS_TIMESTAMPS:-}" ]] && ELEVENLABS_STT_FLAGS+=(--timestamps "$ELEVENLABS_TIMESTAMPS")
    [[ -n "${ELEVENLABS_DIARIZATION:-}" ]] && ELEVENLABS_STT_FLAGS+=(--diarization "$ELEVENLABS_DIARIZATION")
    [[ -n "${ELEVENLABS_RESUME:-}" ]] && ELEVENLABS_STT_FLAGS+=(--resume "$ELEVENLABS_RESUME")
    [[ -n "${ELEVENLABS_CACHE_DIR:-}" ]] && ELEVENLABS_STT_FLAGS+=(--cache-dir "$ELEVENLABS_CACHE_DIR")
    [[ "${OVERWRITE:-0}" -eq 1 ]] && ELEVENLABS_STT_FLAGS+=(--resume off)
}

elevenlabs_validate_options() {
    elevenlabs_build_stt_flags
    local validation
    validation="$($STT_RUNNER validate "${ELEVENLABS_STT_FLAGS[@]}")" || return $?
    ELEVENLABS_EFFECTIVE_TIMESTAMPS="$(printf '%s\n' "$validation" | sed -n 's/.* timestamps=\([^ ]*\).*/\1/p')"
    ELEVENLABS_EFFECTIVE_DIARIZATION="$(printf '%s\n' "$validation" | sed -n 's/.* diarization=\([^ ]*\).*/\1/p')"
    [[ "$ELEVENLABS_EFFECTIVE_TIMESTAMPS" =~ ^(on|off)$ ]] || {
        echo "Error: unable to read effective timestamp mode from stt-api validation." >&2
        return 2
    }
    elevenlabs_debug "$validation"
    return 0
}

elevenlabs_preflight() {
    local input_file="$1"
    local output_file="$2"
    "$STT_RUNNER" transcribe \
        --input-file "$input_file" \
        --preflight \
        --preflight-output "$output_file" \
        "${ELEVENLABS_STT_FLAGS[@]}"
}

elevenlabs_transcribe() {
    local input_file="$1"
    local output_dir="$2"
    local metadata_file="$3"
    local output_basename="$4"
    local log_level="$LOG_LEVEL"
    [[ "$log_level" == "trace" ]] && log_level=debug
    "$STT_RUNNER" transcribe \
        --input-file "$input_file" \
        --output-dir "$output_dir" \
        --output-basename "$output_basename" \
        --metadata-output "$metadata_file" \
        --log-level "$log_level" \
        "${ELEVENLABS_STT_FLAGS[@]}"
}

elevenlabs_json_field() {
    local json_file="$1"
    local field="$2"
    "$STT_PYTHON" -c 'import json,sys; v=json.load(open(sys.argv[1], encoding="utf-8")).get(sys.argv[2], ""); print("" if v is None else v)' "$json_file" "$field"
}

elevenlabs_is_global_failure() {
    local code="$1"
    [[ "$code" -eq "$ELEVENLABS_EXIT_GLOBAL_PROVIDER" || "$code" -eq "$ELEVENLABS_EXIT_RETRY_EXHAUSTED" ]]
}

elevenlabs_is_known_audio_extension() {
    case "${1,,}" in
        wav|mp3|aiff|aif|aac|ogg|flac|mpeg|mpga|m4a|l16|opus|alaw|mulaw|webm|weba) return 0 ;;
        *) return 1 ;;
    esac
}

elevenlabs_is_known_video_extension() {
    case "${1,,}" in
        mp4|m4v|mkv|mov|avi|webm|ts|m2ts|mts|mpg|mpeg|flv|wmv|3gp|ogv) return 0 ;;
        *) return 1 ;;
    esac
}

elevenlabs_detect_media_kind() {
    local media_path="$1"
    local extension="${2,,}"
    local has_video="" has_audio=""
    if command -v ffprobe >/dev/null 2>&1; then
        has_video="$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_type -of csv=p=0 "$media_path" 2>/dev/null | head -n 1 || true)"
        has_audio="$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_type -of csv=p=0 "$media_path" 2>/dev/null | head -n 1 || true)"
    fi
    if [[ -n "$has_video" ]]; then
        printf 'video'
    elif [[ -n "$has_audio" ]] || elevenlabs_is_known_audio_extension "$extension"; then
        printf 'audio'
    elif elevenlabs_is_known_video_extension "$extension"; then
        printf 'video'
    else
        printf 'unknown'
    fi
}

elevenlabs_extract_video_audio() {
    local input_file="$1" output_file="$2" overwrite="$3"
    command -v ffmpeg >/dev/null 2>&1 || {
        echo "Error: ffmpeg is required to extract video audio." >&2
        return 2
    }
    if [[ -f "$output_file" && "$overwrite" -ne 1 ]]; then
        elevenlabs_info "Reusing extracted audio: $output_file"
        return 0
    fi
    local replace=(-n) loglevel=error
    [[ "$overwrite" -eq 1 ]] && replace=(-y)
    (( $(elevenlabs_log_rank "$LOG_LEVEL") >= 3 )) && loglevel=info
    ffmpeg -hide_banner -loglevel "$loglevel" "${replace[@]}" -i "$input_file" \
        -vn -ar 16000 -ac 1 -c:a flac "$output_file"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "Internal helper. Run one of the four *_via_elevenlabs.sh workflow scripts." >&2
    exit 2
fi

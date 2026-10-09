#!/usr/bin/env bash
# Path implementation lives in artifact_paths.py; assignments are shell-quoted there.
artifact_python() {
    local python="$SCRIPT_DIR/.venv/bin/python"
    [[ -x "$python" ]] || python=python3
    "$python" "$SCRIPT_DIR/scripts/artifact_paths.py" "$@"
}

workflow_path_defaults() {
    local assignments
    assignments="$(artifact_python defaults)" || return $?
    eval "$assignments"
    MDOUTDIR="$OUTDIR"
    MDOUTDIR_DEFAULT="$OUTDIR"
    SRTOUTDIR_DEFAULT="$SRTOUTDIR"
}

workflow_prepare_job() {
    local source="$1" name="$2" assignments
    local options=(job --input "$source" --name "$name" --workflow "$(basename "$0" .sh)")
    # CLI paths and explicitly overridden defaults remain protected destinations.
    [[ -n "${OUTDIR:-}" ]] && options+=(--outdir "$OUTDIR")
    [[ -n "${SRTOUTDIR:-}" ]] && options+=(--transcript-dir "$SRTOUTDIR")
    [[ "${OUTDIR_CUSTOM:-1}" -eq 0 ]] && options+=(--managed-md)
    [[ "${SRTOUTDIR_CUSTOM:-1}" -eq 0 ]] && options+=(--managed-transcript)
    [[ "${OVERWRITE:-0}" -eq 1 ]] && options+=(--overwrite)
    local provider config cache
    case "$(basename "$0")" in
        *_via_groq.sh) provider=groq; config="${GROQ_CONFIG:-}"; cache="${GROQ_CACHE_DIR:-}" ;;
        *_via_gemini.sh) provider=gemini; config="${STT_CONFIG:-}"; cache="${GEMINI_CACHE_DIR:-}" ;;
        *_via_elevenlabs.sh) provider=elevenlabs; config="${STT_CONFIG:-}"; cache="${ELEVENLABS_CACHE_DIR:-}" ;;
        *) provider=""; config=""; cache="" ;;
    esac
    [[ -n "$provider" ]] && options+=(--provider "$provider")
    [[ -n "$config" ]] && options+=(--provider-config "$config")
    [[ -n "$cache" ]] && options+=(--cache-dir "$cache")
    assignments="$(artifact_python "${options[@]}")" || return $?
    eval "$assignments"
    case "$(basename "$0")" in
        *_via_groq.sh) [[ -n "${GROQ_CACHE_DIR:-}" ]] || GROQ_CLI_FLAGS+=(--cache-dir "$WORKFLOW_CACHE_DIR") ;;
        *_via_gemini.sh) [[ -n "${GEMINI_CACHE_DIR:-}" ]] || GEMINI_STT_FLAGS+=(--cache-dir "$WORKFLOW_CACHE_DIR") ;;
        *_via_elevenlabs.sh) [[ -n "${ELEVENLABS_CACHE_DIR:-}" ]] || ELEVENLABS_STT_FLAGS+=(--cache-dir "$WORKFLOW_CACHE_DIR") ;;
    esac
    [[ "${OVERWRITE:-0}" -eq 1 ]] && LECTURE_CLEANUP_FLAGS+=(--overwrite)
    return 0
}

workflow_publish_transcript() {
    local source="$1" name="$2" extension="${3:-txt}"
    mkdir -p "$TRANSCRIPT_DIR" || return $?
    local target="$TRANSCRIPT_DIR/$name.$extension"
    if [[ "$source" != "$target" ]]; then
        cp -- "$source" "$target.part" && mv -- "$target.part" "$target" || return $?
    fi
    if [[ "$extension" == txt ]]; then
        TXT_PATH="$target"
        TXT_FILE="$name.txt"
    fi
}

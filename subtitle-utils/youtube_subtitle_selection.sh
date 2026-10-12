# Shared selection setup. The caller owns SUBTITLE_SELECTION_FLAGS and DEBUG.
select_youtube_subtitles() {
    local root="$1" url="$2" assignments python
    python="$root/.venv/bin/python"
    [[ -x "$python" ]] || python=python3
    SUBTITLE_METADATA="$(mktemp)" || return $?
    trap 'rm -f -- "$SUBTITLE_METADATA"' EXIT
    local flags=("${SUBTITLE_SELECTION_FLAGS[@]}")
    [[ "${DEBUG:-0}" -ne 1 ]] || flags+=(--debug)
    assignments=$("$python" "$root/subtitle-utils/select_youtube_subtitles.py" \
        "$url" --metadata "$SUBTITLE_METADATA" "${flags[@]}") || return $?
    # Output contains only shlex-quoted assignments from our helper.
    eval "$assignments"
    echo "[INFO] Selected $SELECTED_SUBTITLE_SOURCE subtitles: $AUTO_LANG"
    SUBTITLE_DOWNLOAD_FLAGS=(--no-write-subs --no-write-auto-subs)
    if [[ "$SELECTED_SUBTITLE_SOURCE" == manual ]]; then
        SUBTITLE_DOWNLOAD_FLAGS+=(--write-subs)
    else
        SUBTITLE_DOWNLOAD_FLAGS+=(--write-auto-subs)
    fi
}

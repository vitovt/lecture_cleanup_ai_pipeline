#!/usr/bin/env bash
# extract-audio.sh
# Extract audio from all .mp4 files in the current directory.
# - Writes to the same base filename but with an audio-appropriate extension.
# - Skips files whose target audio already exists (with a message).
# - Basic logging for which file is processed.
# - Suppresses ffmpeg output unless --debug is passed.

set -euo pipefail
shopt -s nullglob

DEBUG=0
if [[ "${1-}" == "--debug" ]]; then
  DEBUG=1
  shift || true
fi

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Error: '$1' is required but not found in PATH." >&2
    exit 1
  fi
}
need ffprobe
need ffmpeg

# Map audio codec to a sensible container/extension for stream-copying
ext_for_codec() {
  local c="$1"
  case "$c" in
    aac|aac_latm|libfdk_aac) echo "m4a" ;;
    alac)                    echo "m4a" ;;
    mp3|mp3float)            echo "mp3" ;;
    opus)                    echo "opus" ;;
    vorbis)                  echo "ogg"  ;;
    flac)                    echo "flac" ;;
    ac3)                     echo "ac3"  ;;
    eac3)                    echo "eac3" ;;
    pcm_s16le|pcm_s24le|pcm_s32le) echo "wav" ;;
    *)                       echo "m4a"  ;;  # sensible default
  esac
}

run_ffmpeg() {
  if (( DEBUG )); then
    ffmpeg -hide_banner -loglevel info "$@"
  else
    ffmpeg -hide_banner -loglevel error "$@" >/dev/null 2>&1
  fi
}

mp4s=( *.mp4 )
if (( ${#mp4s[@]} == 0 )); then
  echo "No .mp4 files found in the current directory."
  exit 0
fi

for in_file in "${mp4s[@]}"; do
  base="${in_file%.*}"

  # Detect first audio stream codec (if any)
  codec="$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name \
           -of default=nw=1:nk=1 "$in_file" || true)"

  if [[ -z "$codec" ]]; then
    echo "[$in_file] No audio stream found. Skipping."
    continue
  fi

  out_ext="$(ext_for_codec "$codec")"
  out_file="${base}.${out_ext}"

  if [[ -e "$out_file" ]]; then
    echo "[$in_file] Target exists -> '$out_file'. Skipping."
    continue
  fi

  echo "[$in_file] codec=${codec} -> extracting to '$out_file'..."
  # Stream copy the audio, drop video
  run_ffmpeg -i "$in_file" -vn -acodec copy "$out_file" || {
    echo "[$in_file] Extraction failed." >&2
    # If copy fails due to container/codec mismatch, try a safe re-encode to AAC in M4A
    if [[ ! -e "$out_file" ]]; then
      fallback="${base}.m4a"
      echo "[$in_file] Retrying by re-encoding to AAC -> '$fallback'..."
      run_ffmpeg -i "$in_file" -vn -c:a aac -b:a 192k "$fallback" || {
        echo "[$in_file] Fallback re-encode failed." >&2
      }
    fi
  }
done

echo "Done."

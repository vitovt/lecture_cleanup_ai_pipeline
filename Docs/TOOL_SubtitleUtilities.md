# Tools: subtitle and media utilities

Public utilities under `subtitle-utils/` support the source pipelines:

- `download_youtube_subtitles.sh` downloads one video's automatic subtitles.
- `srt_to_custom.py` converts SRT into custom timestamped TXT and removes
  cumulative-caption duplication.
- `vtt_to_custom.py` performs the equivalent conversion for WebVTT.
- `normalize_youtube_url.py` normalizes video IDs and common YouTube URL forms.
- `extract-audio.sh` extracts audio streams from MP4 files in the working directory.
- `docx2md.sh` converts DOCX to Markdown with extracted media.
- `sanitize_filename.sh`/`.py` normalize filesystem-facing titles used by wrappers.

Use `StartMe.sh help download-subtitles`, `extract-audio`, or
`docx-to-markdown` for the exposed utility modes. TXT and SRT contracts are in
[FORMATS.md](FORMATS.md).

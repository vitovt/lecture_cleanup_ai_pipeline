# Timestamped screenshots in Markdown

`yt-md-screenshots` inserts video frames after standalone timestamped links:

```markdown
[🎥 16:39](https://www.youtube.com/watch?v=1ASzWklab2U&t=999)
```

Requirements: Python 3.9+, `ffmpeg`, `ffprobe`, and `yt-dlp` for YouTube access.
All commands, diagnostics, and help are in English. Run `--help` for every option.
Option names must be exact: unknown or abbreviated options (such as
`--between-timeco`) and invalid values fail before processing, with exit status 2.

## Common commands

```sh
subtitle-utils/yt-md-screenshots '/path/to/lecture.md'
subtitle-utils/yt-md-screenshots '/path/to/lecture.md' --dry-run
subtitle-utils/yt-md-screenshots '/path/to/lecture.md' --offset 3
subtitle-utils/yt-md-screenshots '/path/to/lecture.md' --offset -2
subtitle-utils/yt-md-screenshots '/path/to/lecture.md' --between-timecodes
subtitle-utils/yt-md-screenshots '/path/to/lecture.md' --between-timecodes --offset 2
subtitle-utils/yt-md-screenshots '/path/to/lecture.md' --between-timecodes --delete-orphans
subtitle-utils/yt-md-screenshots '/path/to/lecture.md' --force
subtitle-utils/yt-md-screenshots '/path/to/lecture.md' --all-occurrences
subtitle-utils/yt-md-screenshots '/path/to/lecture.md' --deduplicate
subtitle-utils/yt-md-screenshots '/path/to/lecture.md' --preserve-cache --debug
```

YouTube URLs may use `youtu.be`, `watch`, `shorts`, `live`, or `embed` paths.
Accepted timestamps include `t=999`, `t=999s`, `t=16m39s`, `t=16:39`, and
`start=999`. Query parameters and `#t=...` fragments are supported. Links without
an explicit timestamp are ignored. Invalid timestamps are reported, not silently
converted. Active/upcoming live broadcasts are unsupported; use the recording.

Only standalone `[🎥...](URL)` lines are candidates. Fenced code, indented code,
and HTML comments are excluded. Arbitrary links in prose, list items, or quotes
are not converted. The scanner is deliberately limited to this standalone format,
not a general Markdown reformatter.

## Local video

For a document with one video ID:

```sh
subtitle-utils/yt-md-screenshots lecture.md --local-video '/path/Local lecture.mp4'
```

Map multiple sources explicitly; unspecified IDs are downloaded from YouTube:

```sh
subtitle-utils/yt-md-screenshots lecture.md \
  --local-video '1ASzWklab2U=/path/First lecture.mp4' \
  --local-video 'abcdefghijk=/path/Second lecture.mkv'
```

The Markdown still supplies the YouTube ID and timestamps. A mapped local video
replaces that ID's media source and needs no YouTube connection. Local input
videos are **never modified or deleted**, including with `--force`.

Local PNG names include the sanitized input stem, the first **four hexadecimal
characters (two bytes) of SHA-256 of the complete video contents**, the original
timestamp, and a nonzero offset. Hashing reads each distinct local file once per
run. The sanitizer follows `sanitize_filename.sh`: controls are removed,
Windows-forbidden characters become spaces, trailing dots/spaces are trimmed,
and reserved device names are prefixed. Spaces then become underscores. The
readable stem is limited to 64 Unicode characters and shortened further when
necessary to keep the complete name within 255 UTF-8 bytes.

Example: `img-local-Local_lecture-a81f-999.png`. The short hash can collide;
it is an identifier convenience, not a guarantee of content uniqueness.

YouTube names retain compatibility with the original script:
`img-1ASzWklab2U-999.png`. A positive offset adds `-offset-p3` before `.png`;
a negative offset adds, for example, `-offset-m2`. Offsets do not change the
source links. Generated Markdown uses angle-bracket URLs with percent encoding.

### Capture between timecodes

`--between-timecodes` captures halfway between the current timecode and the next
distinct timecode for the **same video in document order**. Repeated timecodes
share the plan from their first occurrence. Links to other videos and excluded
code/comments do not affect the interval. For each video's final timecode, the
interval ends at that video's duration. A next timecode earlier than the current
one, or outside the video, produces an error for that interval and preserves its
existing image. Timecodes are not sorted or silently skipped to find a later one.

The calculation is `floor(clamp((current + next_or_end) / 2 + offset, 0, duration))`.
Only whole seconds are used, including after a fractional offset or video end.
Between-mode names contain the **final capture second**, with no mode or offset
suffix. Local names retain their filename/hash identity. Ordinary runs retain
their original timestamp/offset naming. Source links are never shifted.

For timecodes `945`, `999`, `1046` and duration `4288.684` seconds:

| Mode | PNG capture/name seconds |
| --- | --- |
| Ordinary | `945`, `999`, `1046` |
| `--between-timecodes` | `972`, `1022`, `2667` |
| `--between-timecodes --offset 2` | `974`, `1024`, `2669` |

For example, `img-1ASzWklab2U-945.png` is replaced in Markdown by
`img-1ASzWklab2U-972.png`, then by `img-1ASzWklab2U-974.png`. Successfully generated
or cached images replace attachments; failures preserve the previous attachment.
Rerunning a mode reuses its PNGs. Returning to ordinary capture reuses the original
PNGs if retained. Editing a timecode can change both its own midpoint and that of
the preceding distinct timecode. Unchanged final capture seconds share a cached
PNG, including with ordinary zero-offset capture.

Between-mode planning always probes local duration or requests YouTube metadata,
even when all PNGs are cached. Only sources needing new frames are downloaded.
Dry runs show interval, midpoint, offset, capture second, and filename.

## Downloads, cache, and cleanup

A video needing new frames is downloaded in full once per run, using the best
available video format at or below 1080p, prioritizing resolution. A selected
format may also contain audio. No format above 1080p is selected. Frames are extracted locally.
Valid existing PNGs avoid regeneration; each cache hit is printed at `info`.
A fully cached YouTube source needs no metadata request in ordinary capture mode.
`--dry-run` does check remote metadata even for cached sources.

Downloaded media and intermediate PNGs live in a unique
`/tmp/md-screenshots-run-dirXXX` directory. Successful runs remove it. Runs with
unresolved errors keep it and print its path and downloaded video paths at `info`.
`--preserve-cache` keeps it even on success. A transient failure followed by a
successful retry does not by itself prevent cleanup. A run using only cached PNGs,
or a dry run, does not need a temporary directory.

There is no automatic discovery of previous run directories. Reuse a retained
video with `--local-video`; this uses local-source PNG naming. Nothing deletes
existing PNG files unless `--delete-orphans` is explicitly supplied (see below).

Snap-installed `yt-dlp` has a private `/tmp`. The tool detects the Snap launcher
and streams its binary stdout into a file opened by the parent process in the
host run directory. Completed streams are retained as `video.media` (ffmpeg
detects their container from the contents). Interrupted streams remain `.part`
files and retries restart the stream. Non-Snap installations use normal file
downloads and yt-dlp's output-path receipt.

User `yt-dlp` configuration is inherited, including cookies and proxies. The tool
overrides the format, main output path, and retry counts. Configuration that skips
downloads, extracts audio, cuts sections, or otherwise transforms the source may
be incompatible: missing media, unusable video, or a changed duration produce an
error and preserve artifacts. Configure `yt-dlp` for complete video downloads.
Duration and sample decoding are checked; this is not an exhaustive corruption
scan of every frame. Each generated PNG is decoded before being accepted.

## Existing images and duplicates

By default a new image is inserted at the first occurrence of each video ID and
timestamp. If an image already exists at a later occurrence, it is left there and
the missing first image is added. Existing images are recognized by filename,
including changed alt text, blank lines, angle-bracket URLs, encoded URLs, titles,
and standalone reference-style images with a single-line definition.

`--all-occurrences` fills every occurrence without duplicating an existing
attachment. `--deduplicate` keeps generated attachments only at the first
occurrence. These options are mutually exclusive.

Only adjacent standalone image lines (allowing intervening blank lines) pointing
into `_resources` and matching this tool's naming pattern are managed. Unrelated
images are left alone. Without a registry, the filename convention and adjacency
are the ownership heuristic. A stale attachment from another source or offset is
replaced only after the new frame is available. Old PNG files remain on disk by default.

After the original Markdown is successfully updated, removed references are
reported as copyable shell commands, one absolute, shell-quoted path per line:

```sh
rm -- '/path/to/_resources/img-oldvideo123-999.png' # Reference removed from this Markdown
```

The commands are **not executed**. Duplicate paths and filenames still mentioned
anywhere in the updated document are excluded conservatively. Other documents
may still use these files; inspect before executing the commands. There is no
registry. Unreferenced old files that were
not removed from this document during this run are not inventoried.

`--delete-orphans` executes deletion for that same report, **only after successfully
writing the updated original Markdown**. It does not scan `_resources`, check other
documents, or delete local video inputs. Files still mentioned anywhere in the
updated document are retained. Use this option only when deleting resources shared
with other documents is acceptable. With this option, report lines look like:

```sh
rm -- '/path/to/_resources/img-oldvideo123-999.png' # DELETED: reference removed from this Markdown
```

Already missing files are marked `ALREADY ABSENT`; deletion failures are marked
`NOT DELETED`, reported as errors, and result in a nonzero exit status. Such an
error does not undo the already written Markdown. A conflict or failure before
Markdown replacement never deletes orphan files. Dry runs only print planned
deletions. Repeated runs do not rediscover older orphans from prior runs.

## Force, offsets, and errors

`--force` regenerates required PNGs even when cached. It does not force a new copy
of an already available media source. New PNGs replace old ones atomically only
after validation. On failure the old PNG and existing Markdown attachment remain,
the frame is explicitly reported as not updated, and no new attachment is added.
There is no `--strict-refresh` option.

An original timestamp must be within `[0, duration)`. Invalid positions are
reported and skipped. Offsets are applied only after this check. If an offset
moves a valid position outside the recording, the first or last available frame
is used and the adjustment is reported. A position at the end uses the final
decoded frame, not a nonexistent frame at exactly `duration`.

The default is **two total attempts** (one initial attempt plus one retry) for
transient network failures/timeouts. Deterministic errors are not retried.
Repeated occurrences share one result, including failures. Options:

- `--attempts N`: total attempts, at least one.
- `--timeout SECONDS`: metadata, probe, and frame-operation timeout; default 120.
- `--download-timeout SECONDS`: full-download attempt timeout; default 3600.
- `--socket-timeout SECONDS`: yt-dlp network socket timeout; default 30.
- `--fail-fast`: stop after the first exhausted/permanent error, without writing
  partial Markdown. Already generated PNGs are not rolled back.

Without `--fail-fast`, successful results are written even when other targets
fail. Exit status is 0 on success, 1 on processing errors/conflicts/interruption,
and 2 on argument parsing errors.

## File safety

Resources are always beside the actual Markdown, independent of the working
directory. A symlink path is rejected with its real target and a suggestion to use
`--follow-symlinks`. With that option resources go beside the resolved target.

Before replacing Markdown, the tool compares its bytes with the original read.
If it changed, the original is left untouched and the proposed result is saved
beside it as `lecture-conflict-YYYYMMDD-HHMMSS-microseconds.md`. The conflict is
reported as an error; removal commands are not printed as completed actions.
This is an optimistic check, not a lock on external editors.

Markdown permissions, UTF-8 BOM, and normal LF/CRLF line endings are preserved.
Final replacement files are staged in the destination directory to allow atomic
replacement even when `/tmp` is on another filesystem.

## Dry run and logging

`--dry-run` parses targets, checks dependencies, local files, cached PNGs, remote
metadata/accessibility, duration, and planned changes. It does not download video,
generate PNGs, or write Markdown. Network metadata requests are allowed. It cannot
guarantee media download success or remote frame decodability: HTTP 403 and media
errors can still occur during an actual run. Removal reports are labelled as plans.

- `--log-level quiet`: nothing, including errors; exit status still applies.
- `--log-level error`: errors only.
- `--log-level info`: progress, cache hits, warnings, concise errors, and summary
  (default).
- `--log-level debug` or `--debug`: command diagnostics, yt-dlp verbose logs,
  ffmpeg diagnostics, and stack traces. Subprocess output is collected and shown
  when the operation finishes; debug logs may contain signed URLs or configuration.
- `--log-level trace` or `--trace`: identical to debug; no deeper request tracing.

When several verbosity options are supplied, the last one wins. Ordinary runs
suppress raw ffmpeg stderr and show concise errors with source and line context.

## Tests

```sh
python3 -m unittest discover -s tests -p 'test_yt_md_screenshots.py' -v
```

Tests do not contact YouTube. Network workflows are mocked; actual ffmpeg/ffprobe
coverage uses a generated local video and is skipped if those tools are absent.

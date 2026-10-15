# Join videos without re-encoding

`glue_videos.py` requires Python 3, FFmpeg and ffprobe on `PATH`. It has no
third-party Python dependencies.

## Project launcher

From any working directory, use the project's `StartMe.sh` launcher. It preserves
input order and passes paths and options unchanged; relative paths refer to your
current working directory:

```bash
./StartMe.sh glue-videos part1.mkv part2.mkv -o joined.mkv
./StartMe.sh help glue-videos
./StartMe.sh glue-videos --help
```

Calling `./StartMe.sh glue-videos` without arguments shows the utility's short
introduction. Detailed help is delegated to the utility itself.

## Standalone usage

```bash
python3 subtitle-utils/glue_videos.py \
  2026-10-13_15-23-46-Record1.mkv \
  2026-10-13_16-08-41-Record2.mkv \
  --output 2026-10-13-Record-combined.mkv
```

Supply any number of inputs in **playback order**. The script never sorts them;
shell wildcards use your shell's expansion order. One input is also accepted.
`--output` / `-o` selects the final file. Omitting it implies `--dry-run` and
reports that output is not specified. Inputs and output must have the same container
extension (case insensitive), consistent with their detected container.
Common containers include MKV, MP4, MOV, WebM, AVI, TS, MPEG, OGV and FLV;
the corresponding FFmpeg muxer must be installed.

```bash
python3 subtitle-utils/glue_videos.py part1.mp4 part2.mp4 part3.mp4 -o complete.mp4
python3 subtitle-utils/glue_videos.py part1.mkv part2.mkv -o complete.mkv --overwrite
python3 subtitle-utils/glue_videos.py -o complete.mkv -- -filename-starting-with-dash.mkv part2.mkv
```

## Preview without creating files

Use `--dry-run` with an output path to validate the planned result, or omit
`-o/--output` to inspect the inputs without choosing a destination:

```bash
./StartMe.sh glue-videos part1.mkv part2.mkv -o complete.mkv --dry-run
./StartMe.sh glue-videos part1.mkv part2.mkv
```

Both forms use the normal input checks: missing, unreadable, empty, damaged, or
incompatible videos fail with the same error mechanism and nonzero exit status.
The report lists each absolute input path, size, container, duration, video
properties (codec, resolution, frame rates, pixel/color formats), audio properties
(codec, sample rate, channels), stream order, codec initialization hashes, and
track metadata. It then shows the output path (or `Output: not specified`), muxer,
stream/audio-track counts, segment concat durations, and estimated total duration
in seconds and `HH:MM:SS.mmm`. The estimate includes packet-timing corrections;
container rounding and actual FFmpeg processing can slightly change the result.

When supplied, the output path undergoes the normal container, directory, symlink,
and input-alias checks, plus directory writability and available-space checks.
An existing output is reported without prompting or replacing it, even with
`--overwrite`. Without an output path, destination-specific checks cannot run.
Dry-run creates neither the final file nor temporary manifests/media and does
not run the FFmpeg concatenation; metadata, muxer, and packet-timing inspection
still require FFmpeg/ffprobe. Normal no-argument usage continues to print only
the short introduction.

Existing outputs require a `y`/`n` response unless `--overwrite` is supplied.
An unanswered prompt fails in unattended runs. Source files, including aliases
through hard links or symlinks, cannot be overwritten. Output symlinks are refused.
An output's parent directory must already exist.

For lists exceeding your shell's argument limit, use `@arguments.txt`. Put one
argument on each line, without shell quotes. Paths containing spaces work:

```text
/recordings/part 1.mkv
/recordings/part 2.mkv
-o
/recordings/complete.mkv
```

```bash
python3 subtitle-utils/glue_videos.py @arguments.txt
```

Each input is compared with the first. Checks include the actual container,
stream order/count, codecs, codec initialization data, time bases, video
dimensions/frame rates/pixel and color formats, and audio sample rates/channel
layouts. Track titles, languages, dispositions and stream side data must also
match, which helps catch reordered tracks. Durations, bitrates and packet counts
may differ. Differences are reported with the filename, stream position,
property, expected value and actual value. Streams are numbered from zero.

Every audio track stays separate: first audio track joins first audio track,
second joins second, and so on. Tracks with identical properties and labels
cannot be distinguished by their content; arrange them consistently when recording.
Video and subtitle streams are also copied. Silent videos are supported.
Attachments, cover art and data streams are rejected rather than silently dropped.
Existing chapters are omitted. Track metadata is taken from the first input.

The join uses the [FFmpeg concat demuxer](https://www.ffmpeg.org/ffmpeg-formats.html#concat-1)
with `-map 0 -c copy`. It writes a temporary file on the output filesystem,
checks the result's stream count/order/codecs and duration, then publishes it
atomically. Existing output stays intact on failure or cancellation. Allow free
space for approximately the sum of the input sizes plus a small overhead, even
when replacing an existing output. Active recordings should be closed first;
inputs changing during the join cause failure.

No decoding/re-encoding is performed. Metadata checks and FFmpeg's reported read
errors do not certify every compressed frame against corruption. Concatenation
uses the duration of each segment to advance all tracks together. The script
checks beginning/end packet timestamps and extends a segment when necessary to
avoid overlapping packets (for example, AAC encoder delay in MP4). This may add
a small gap; pre-existing differences in track lengths can also remain at joins.

Exit status: `0` success, `1` failure/cancellation at the overwrite prompt,
`2` invalid command-line arguments, `130` interruption.

## Help and validation

Running without arguments prints a short description, a common example, and a
`--help` hint, then exits successfully without inspecting files or invoking FFmpeg.
`--help` / `-h` displays detailed usage. Unknown or abbreviated option names fail
with exit status `2` before processing; use exact names such as `--output`.

```bash
python3 subtitle-utils/glue_videos.py
python3 subtitle-utils/glue_videos.py --help
```

## Tests

Run the integration checks from the project root with:

```bash
python3 -m unittest discover -s tests -p 'test_glue_videos.py' -v
```

The tests create temporary tiny videos and check compressed-packet hashes and
their order independently for each track in MKV and MP4. Your recordings are
not used or modified by this test suite.

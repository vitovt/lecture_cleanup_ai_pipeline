# Entry point: StartMe

`StartMe.sh` is the high-level dispatcher for complete workflows. Run it from
any directory; delegated project scripts are resolved relative to `StartMe.sh`.

```bash
./StartMe.sh
./StartMe.sh help MODE
./StartMe.sh MODE [arguments]
```

Workflow modes include transcript cleanup, YouTube subtitles, YouTube/local
Groq and SpeechCore transcription, batch variants, and `multitrack`. Provider
and maintenance modes expose Groq, diarization, setup, update, and conversion
operations where direct access is useful.

```bash
./StartMe.sh cleanup --input lecture.txt --lang uk
./StartMe.sh local-groq --lang auto ./meeting.m4a
./StartMe.sh multitrack --preset ./webinar.yaml ./recording.mkv
```

Use `--color`, `--no-color`, or `--color=auto|always|never` before the mode.
Detailed, current options come from `./StartMe.sh help MODE`.

Use `add-summary` to add or regenerate short/long summaries of existing Markdown:

```bash
./StartMe.sh add-summary ./notes.md --type both --lang uk --dry-run
./StartMe.sh add-summary ./notes.md --type both --lang uk
./StartMe.sh help add-summary
```

This mode delegates to `subtitle-utils/add_summary.sh`, using the project virtual
environment and keeping paths relative to the invocation directory. It supports
internal/external output, skip/replace/add/error conflict policies, source
inspection and configurable backups. Tool-specific settings belong to
`summary_regeneration` in the config. See [TOOL_AddSummary.md](TOOL_AddSummary.md)
for legacy summaries, references, replacement selectors and configuration.

Use `source-timecodes` to inspect or transform Markdown heading timestamps,
camera links, and source block IDs:

```bash
./StartMe.sh source-timecodes doctor ./notes.md
./StartMe.sh source-timecodes analyze ./notes.md
./StartMe.sh source-timecodes transform ./notes.md --add-src --overwrite
./StartMe.sh help source-timecodes
```

This mode delegates to `subtitle-utils/source_timecodes.py`, forwarding its
subcommands and options. Paths refer to the invocation directory. `transform`
supports stdout, `--diff`, `-o FILE.md`, and `--overwrite` output modes.

Use `add-video-url` to turn local Markdown timestamps into YouTube links:

```bash
./StartMe.sh add-video-url -u https://youtu.be/JF1ooAGs0L4 ./notes.md --overwrite
./StartMe.sh help add-video-url
```

This mode delegates to `subtitle-utils/add_video_url.py` and keeps paths relative
to the invocation directory. Omit `--overwrite` to print Markdown to stdout,
use `-o FILE.md` to write another file, or use `--diff` to preview changes.

For `cleanup`, relative `--input`, `--outdir`, `--context-file`, and `--glossary`
paths refer to the directory where you invoke StartMe. Both `--option value`
and `--option=value` forms work, including repeated context files.

Set the default Markdown destination in the project's `.env`:

```bash
CLEANUP_MDOUTDIR="$HOME/Desktop/obsidian"
```

An explicit `--outdir` takes precedence. Without either setting, Markdown goes
to the project's `output` directory. Relative `CLEANUP_MDOUTDIR` paths also
refer to the project directory. QC CSV placement follows `--qc-report`;
`default_outdir` keeps reports in the project's `output` directory.

The destination rules also apply to direct `lecture_cleanup.sh`. Existing
Markdown is an error unless `--overwrite` is explicit.

Low-level multitrack transcription and merging are intentionally not StartMe
modes. They remain standalone modules documented in
[TOOL_TranscribeTracks.md](TOOL_TranscribeTracks.md) and
[TOOL_MergeTranscripts.md](TOOL_MergeTranscripts.md).

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
./StartMe.sh multitrack --manifest ./webinar.yaml
```

Use `--color`, `--no-color`, or `--color=auto|always|never` before the mode.
Detailed, current options come from `./StartMe.sh help MODE`.

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
refer to the invocation directory. QC CSV placement follows `--qc-report`;
`default_outdir` keeps reports in the project's `output` directory.

These path and destination settings apply only to `StartMe.sh cleanup`.
Direct `lecture_cleanup.sh` calls and other StartMe modes retain their existing
behavior and output settings.

Low-level multitrack transcription and merging are intentionally not StartMe
modes. They remain standalone modules documented in
[TOOL_TranscribeTracks.md](TOOL_TranscribeTracks.md) and
[TOOL_MergeTranscripts.md](TOOL_MergeTranscripts.md).

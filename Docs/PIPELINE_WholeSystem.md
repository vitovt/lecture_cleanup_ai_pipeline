# Pipeline: whole system

The system accepts existing transcripts, YouTube sources, one local media file,
batches, or simultaneous multitrack sessions. Every complete workflow ends at
the same `lecture_cleanup.sh` boundary and produces Markdown only after all
required upstream stages succeed.

## Existing transcript

```text
TXT/SRT -> parse and chunk -> cleanup LLM -> stitch -> summaries -> Markdown/QC
```

Use `StartMe.sh cleanup` or `cleanup-list`. See
[TOOL_LectureCleanup.md](TOOL_LectureCleanup.md).

## YouTube subtitles

```text
URL -> yt-dlp subtitles -> SRT -> custom TXT -> cleanup -> Markdown
```

See [PIPELINE_YouTube.md](PIPELINE_YouTube.md).

## YouTube or local media ASR

```text
media -> audio preparation -> Groq/SpeechCore -> timestamped TXT
      -> cleanup -> front matter + Markdown
```

Groq may invoke pyannote before formatting speaker-attributed events. Provider
artifacts remain inputs to their wrapper, while timestamped TXT is the cleanup
handoff. See [PIPELINE_LocalMedia.md](PIPELINE_LocalMedia.md),
[ASRprovider_Groq.md](ASRprovider_Groq.md), and
[ASRprovider_SpeechCore.md](ASRprovider_SpeechCore.md).

## Multitrack session

```text
session YAML / --file list
    -> one ASR adapter call per track
    -> one event JSON per track
    -> resolved manifest
    -> manual offset application and chronological merge
    -> combined event JSON + TXT + SRT
    -> one cleanup call
    -> Markdown/QC/summaries
```

The event JSON boundary lets transcription and merging evolve independently.
The resolved manifest lets synchronization change without repeating ASR. The
combined custom TXT boundary lets the existing cleanup pipeline remain
unchanged. See [PIPELINE_Multitrack.md](PIPELINE_Multitrack.md).

## Failure boundaries

- Manifest and CLI validation occur before paid transcription.
- A failed track stops the multitrack pipeline before merging and cleanup.
- Invalid event documents stop the merger before replacing combined outputs.
- Failed cleanup chunks prevent partial Markdown from being written.
- Provider diagnostics and stable event files remain available for independent
  retries and inspection.

Every serialized handoff is specified in [FORMATS.md](FORMATS.md).

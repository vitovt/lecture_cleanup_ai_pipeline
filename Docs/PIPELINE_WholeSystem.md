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
CLI sources / YAML preset + optional multistream recording
    -> validate every source/provider combination
    -> extract selected streams or single-stream files
    -> independent transcription per source
    -> named timestamped TXT per source
    -> offsets and chronological TXT merge
    -> optional cleanup/Markdown (initially disabled by default)
```

Preserve extracted audio, provider diagnostics, and per-source TXT for inspection.
See [PIPELINE_Multitrack.md](PIPELINE_Multitrack.md). Local single-file workflows
reject multiple audio streams; use explicit multitrack source selection instead.

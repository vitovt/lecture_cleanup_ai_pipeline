# Multitrack quick start

Stage 1 is feature-complete and ready for real-data testing. See
[MULTITRACK_STATUS.md](MULTITRACK_STATUS.md) for verified behavior and limits.
Run commands from the project directory after configuring the providers you use.

## Preview and process a recording

This preset selects OBS audio track 2 as Student_Nazar and track 5 as
Teacher_Vitalii, using ElevenLabs with Ukrainian/German language hints:

```bash
./StartMe.sh multitrack \
  --preset Docs/examples/multitrack-webinar.yaml \
  --start 00:00:10 --end 00:01:10 \
  --workdir ./multitrack-work/lesson-preview --output-name lesson-preview \
  --dry-run \
  ~/Videos/OBS/2026-10-08_18-01-41-NazarUrok.mkv
```

The dry run prints the selected sources, inherited/default settings, extraction
bounds, provider plan, and output locations without uploading or extracting.
Remove `--dry-run` to process. Remove `--start`/`--end` for the whole recording,
and choose a different workdir/output name for the full result. Transcript
accuracy still depends on the audio and provider; inspect the source TXT first.

Only selected streams are uploaded. Audio track numbers start at 1 and do not
count video streams. A stereo audio stream is one track, not two.

## Describe sources directly

```bash
./StartMe.sh multitrack --provider elevenlabs --lang uk --additional-lang de \
  --source student --track 2 --name Student_Nazar \
  --source teacher --track 5 --name Teacher_Vitalii recording.mkv
```

Everything before the first `--source` is global. Each `--source ID` opens a
source context; subsequent options apply only there. Global options such as
`--dry-run`, `--start`, `--workdir`, and cleanup flags must come first. The shared
recording is always last and required only when a source uses `--track`.

Use descriptive `--name` values. If omitted, the label is `Source_<ID>`.
The stable ID is used for overrides and artifact directories, not speaker names.

Separate files and embedded tracks can be combined:

```bash
./StartMe.sh multitrack --provider elevenlabs --lang uk \
  --source host --file ./microphone.wav --name Vitalii \
  --source audience --track 3 --name Students --diarization provider \
  recording.mkv
```

With separate files only, omit the final recording. Each `--file` must contain
exactly one audio stream; `--file` and `--track` are mutually exclusive within a
source. Existing single-file local workflows enforce the same one-stream rule;
batch wrappers encounter that check through their single-file child scripts.

## Override a preset or provider

CLI source settings override matching preset source IDs; new IDs append sources.
CLI defaults override preset defaults, but source-specific settings still win.

```bash
./StartMe.sh multitrack --preset Docs/examples/multitrack-webinar.yaml \
  --source teacher --file ./better-microphone.wav --name Teacher_Vitalii \
  recording.mkv
```

This replaces the teacher's inherited track selection with a file. The student
still uses track 2. CLI `--track` similarly replaces an inherited file.
YAML file paths are relative to the preset; CLI paths are relative to the cwd.

Different providers per source:

```bash
./StartMe.sh multitrack --provider groq --lang uk \
  --source host --track 2 --name Vitalii --diarization off \
  --source audience --track 5 --name Students --provider elevenlabs \
    --additional-lang de --diarization provider --num-speakers 3 \
  recording.mkv
```

A source's first `--additional-lang` replaces the inherited list; repeat it to
specify several languages, or use `--no-additional-langs` to clear the list.
Groq does not accept that list: use a single `--lang` hint or `--lang auto`.
Provider-specific settings are checked before transcription; unsupported options
are errors, not silently ignored hints.

## Inspect outputs and resume

Running the preview command above without `--dry-run` creates:

```text
multitrack-work/lesson-preview/
  resolved-plan.yaml
  sources/student/audio.flac
  sources/student/source.txt
  sources/student/provider/...
  sources/teacher/audio.flac
  sources/teacher/source.txt
  sources/teacher/provider/...
  combined/lesson-preview.txt
```

Source TXT timestamps are relative to extracted audio. The merged TXT restores
the original/session timeline, including `--start` and synchronization offsets.
Do not add a manual offset merely to compensate for an excerpt's start time.
Provider JSON stays available for diagnostics; merging uses timestamped TXT.

To resume, repeat the same command with the same workdir and settings. Completed,
matching source transcripts are reused. Provider checkpoints may also recover
an interrupted source. Changing audio or effective settings invalidates reuse.
Use global `--overwrite` only when you want reprocessing; it also disables
provider checkpoint reuse for that run. `--resume off` alone controls provider
checkpoints, not the outer completed-source cache.

Without explicit paths, artifacts go under `multitrack-work/<recording stem or
session>/`; excerpt names include bounds in milliseconds. Use distinct workdirs
for different recordings, especially separate-file sessions or files with the
same basename. `resolved-plan.yaml` is an inspection artifact, not a preset.

## Cleanup and standalone tools

Multitrack processing currently stops after merging because root configuration
has `multitrack.stop_after_merge: true`. All intermediate artifacts remain.
For an explicit cleanup run, put `--cleanup` before the first source:

```bash
./StartMe.sh multitrack --preset Docs/examples/multitrack-webinar.yaml \
  --cleanup --cleanup-lang uk --short-summary recording.mkv
```

The normal cleanup options are global. `--cleanup-lang` is required when source
languages do not resolve to a single explicit two-letter language. To review
before cleanup, process the merged file separately:

```bash
./lecture_cleanup.sh \
  --input ./multitrack-work/lesson-preview/combined/lesson-preview.txt \
  --lang uk --outdir ./output/multitrack
```

`python3 scripts/transcribe_tracks.py` accepts the multitrack options but always
stops after TXT merging. To merge already reviewed source TXT without any ASR or
cleanup calls, use [merge_transcripts.py](TOOL_MergeTranscripts.md). Supply the
appropriate offsets, including excerpt origins when using excerpt-local TXT.

## Progress logging

INFO reports hashing/cache checks, extraction, provider preparation, chunk
preparation, transcription, merging, and the reason cleanup is skipped.
Use global `--debug` for elapsed times, sizes, paths, and concise provider results.
`--trace` additionally includes STT request settings and full provider responses;
DEBUG does not print transcript payloads. Credentials and audio bytes are not
included in these payload logs. Quiet/error modes suppress progress messages.
The stop message distinguishes `multitrack.stop_after_merge=true`, an explicit
`--stop-after-merge`, and the always-cleanup-free standalone utility.

## Reporting a problem

Keep the exact command or preset, the affected source ID/provider, the relevant
original time interval, and the expected versus actual text/labels. Preserve
`resolved-plan.yaml`, source TXT, merged TXT, and provider metadata/logs. If we
process a file together, a short reproducible interval is enough to start.
Do not include API keys or `.env` files. No need to rerun the whole recording
before reporting a failure.

Full reference: `./StartMe.sh multitrack --help`,
[PIPELINE_Multitrack.md](PIPELINE_Multitrack.md), and
[MULTITRACK_DESIGN.md](MULTITRACK_DESIGN.md).

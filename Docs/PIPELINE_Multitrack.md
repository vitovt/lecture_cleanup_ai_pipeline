# Pipeline: multitrack sources

The complete agreed design, examples, and validation rules are recorded in
[MULTITRACK_DESIGN.md](MULTITRACK_DESIGN.md).

```bash
./StartMe.sh multitrack --provider elevenlabs --lang uk --additional-lang de \
  --source student --track 2 --name Student_Nazar \
  --source teacher --track 5 --name Teacher_Vitalii recording.mkv
```

`--source ID` opens a source scope. Before it, transcription options are shared
defaults; after it they affect that source only. Global workflow/cleanup options
must precede the first source. Use `--file single-stream.wav` instead of `--track N`
for separate recordings. Mix these freely. A final recording is required only
when at least one source selects an embedded track. Names are recommended;
otherwise labels are `Source_ID`.

`--preset FILE` reads YAML `defaults` and a `sources` list. CLI global values
override YAML defaults; source values take priority over globals. CLI sources
update matching IDs and append new IDs. CLI `--file` replaces inherited `track`
and vice versa. Repeated `--additional-lang` replaces the inherited list;
`--no-additional-langs` clears it. See `--help` for complete options and examples.

The workflow preflights every source, extracts selected audio streams into FLAC,
transcribes independently, renames speakers in timestamped TXT, applies offsets,
and merges chronologically. Provider JSON is retained only as diagnostics.
Sources are cached using audio bytes and effective settings, not basename alone.

Default artifacts: `multitrack-work/<recording stem or session>/`, containing
`resolved-plan.yaml`, `sources/ID/audio.flac`, `sources/ID/provider/`,
`sources/ID/source.txt`, and `combined/<name>.txt`. Original inputs are never
modified. `--workdir` and `--output-name` override these locations.

`--dry-run` performs local inspection and option validation and prints every
resolved source/default without extracting, uploading, or writing output files.
Provider credentials are checked for real runs, not required for dry-run.

`multitrack.stop_after_merge: true` in root configuration initially stops here.
Pass global `--cleanup` to invoke `lecture_cleanup.sh`; `--stop-after-merge`
explicitly disables cleanup. For mixed/automatic languages, set `--cleanup-lang`.
All existing shared cleanup options are accepted before the first source.

Provider limitations are explicit: Groq supports off/Pyannote; the stt-api
Gemini/ElevenLabs adapters support off/provider. Timed output is mandatory.
Groq uses one language hint and `--prompt`, not additional-language lists or
native keyterms. Unsupported options fail rather than being silently ignored.
Provider diarization requiring multiple independent requests is rejected.

See [TOOL_TranscribeTracks.md](TOOL_TranscribeTracks.md) for a cleanup-free entry
point and [TOOL_MergeTranscripts.md](TOOL_MergeTranscripts.md) for TXT-only merging.

A ready-to-review preset for the OBS lesson is available at
[examples/multitrack-webinar.yaml](examples/multitrack-webinar.yaml):

```bash
./StartMe.sh multitrack --preset Docs/examples/multitrack-webinar.yaml --dry-run \
  ~/Videos/OBS/2026-10-08_18-01-41-NazarUrok.mkv
```

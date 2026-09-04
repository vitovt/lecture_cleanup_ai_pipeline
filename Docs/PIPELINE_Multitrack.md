# Pipeline: multitrack session

Use this workflow for simultaneous recordings of one webinar: one file per
speaker, a fixed host track plus a mixed audience track, or several mixed
tracks.

```bash
./StartMe.sh multitrack --manifest ./webinar.yaml
```

Manifestless usage is also supported:

```bash
./StartMe.sh multitrack \
  --no-manifest --lang uk \
  --file ./host.wav --file ./guest.wav
```

The complete sequence is:

1. Validate the session manifest before external ASR work.
2. Transcribe every missing/overwritten track through its provider adapter.
3. Normalize fixed and diarized identities into transcript event JSON.
4. Save `resolved-manifest.yaml` for reproducibility and offset editing.
5. Apply manual offsets and merge the event timelines.
6. Write combined event JSON, custom TXT, and SRT under `WORKDIR/combined/`.
7. Run `lecture_cleanup.sh` once on the combined TXT.

Default locations are `./multitrack-work` and `./output/multitrack`. Change them
with `--workdir` and `--outdir`. Use `--name` for the combined basename and
`--cleanup-lang` with a two-letter code when `auto` or per-track languages do
not resolve to one common cleanup language. `--overwrite` retranscribes;
without it valid existing event files are reused.

Cleanup options such as `--summary-mode`, `--context-file`, `--llm-provider`,
and `--include-timecodes` are validated by the wrapper before transcription and
forwarded to the final cleanup stage.

The standalone stages are documented in [TOOL_TranscribeTracks.md](TOOL_TranscribeTracks.md)
and [TOOL_MergeTranscripts.md](TOOL_MergeTranscripts.md).

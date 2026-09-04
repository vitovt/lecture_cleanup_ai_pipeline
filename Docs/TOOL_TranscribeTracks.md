# Tool: transcribe tracks

`scripts/transcribe_tracks.py` performs only ASR and speaker normalization. It
does not merge tracks or run lecture cleanup.

## Manifest mode

```bash
python3 scripts/transcribe_tracks.py \
  --manifest ./webinar.yaml \
  --output-dir ./multitrack-work
```

## Manifestless mode

```bash
python3 scripts/transcribe_tracks.py \
  --no-manifest \
  --lang uk \
  --file ./host.wav \
  --file ./guest.wav \
  --output-dir ./multitrack-work
```

`--file` is repeatable. Manifestless mode uses zero offsets, disables
diarization, assigns `SPEAKER_NN` in argument order, and saves the generated
configuration as `resolved-manifest.yaml`.

Useful options:

- `--provider groq` selects the default provider for manifestless mode.
- `--provider-config FILE` passes a provider configuration override.
- `--resolved-manifest FILE` changes the resolved-manifest destination.
- `--overwrite` retranscribes existing track event files.
- `--log-level quiet|error|info|debug|trace` controls provider logging.

Outputs and contracts are described in [FORMATS.md](FORMATS.md). Provider
selection is isolated behind `multitrack.providers.TranscriptionProvider`, so a
new adapter can replace Groq without changing the merger.

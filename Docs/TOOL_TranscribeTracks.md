# Tool: transcribe sources and merge TXT

`python3 scripts/transcribe_tracks.py` accepts the same scoped source/preset
options as `StartMe.sh multitrack`, but always stops after merged TXT. It never
calls cleanup, even if `--cleanup` or configuration requests it.

```bash
python3 scripts/transcribe_tracks.py --provider elevenlabs --lang uk \
  --source host --file host.wav --name Vitalii \
  --source guest --file guest.wav --name Nazar
```

Use global `--dry-run` for a read-only resolved plan. Prefer explicit speaker
names; omitted names become `Source_ID`. The old `--manifest`/`--no-manifest`
interface is removed. See [PIPELINE_Multitrack.md](PIPELINE_Multitrack.md).

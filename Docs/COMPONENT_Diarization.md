# Component: speaker diarization

The independent `pyannote-diarization/` repository provides provider-neutral
speaker turns. Groq can invoke it before formatting words into speaker-attributed
events.

```bash
./StartMe.sh diarize \
  --input-file ./meeting.wav \
  --output-json ./meeting.speakers.json \
  --num-speakers auto
```

In a multitrack manifest, keep `diarization: false` for a recording containing
one known speaker. Set it to `true` only for a mixed track. Strict manifest
roles apply:

- Fixed track: optional `speaker`, no `speaker_prefix`.
- Diarized track: optional `speaker_prefix`, no `speaker`.

Provider-local labels are remapped to session labels before event files are
written. This prevents accidental collisions between separate diarization
runs. See [FORMATS.md](FORMATS.md).

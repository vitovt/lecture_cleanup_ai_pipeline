# Pipeline: local media

Public local-media workflows are:

- `process_localaudiovideo_via_groq.sh` and its `_list` batch wrapper.
- `process_localaudiovideo_via_speechcore.sh` and its `_list` batch wrapper.
- `StartMe.sh local-groq`, `local-groq-list`, `local-speechcore`, and
  `local-speechcore-list` aliases.

Single-file wrappers detect audio versus video, extract compatible audio when
needed, invoke the selected provider, normalize the transcript filename, run
cleanup, and prepend source metadata to Markdown. List wrappers validate and
delegate each selected file to the corresponding single-file module.

```bash
./StartMe.sh local-groq --lang uk --diarization off ./meeting.mp4
./StartMe.sh local-speechcore-list --lang en --all
```

Use `StartMe.sh help MODE` for current options. Provider details are in
[ASRprovider_Groq.md](ASRprovider_Groq.md) and
[ASRprovider_SpeechCore.md](ASRprovider_SpeechCore.md). Simultaneous recordings
belong to [PIPELINE_Multitrack.md](PIPELINE_Multitrack.md), not the list modes.

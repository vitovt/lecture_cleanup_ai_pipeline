# Pipeline: YouTube

The project has three YouTube paths, each with single-video and playlist forms:

- Subtitle download: `auto_process_youtube.sh` and `_list`.
- Groq audio transcription: `auto_process_youtube_via_groq.sh` and `_list`.
- SpeechCore audio transcription: `auto_process_youtube_via_speechcore.sh` and `_list`.

`manual_process_youtube.sh` cleans an already prepared subtitle TXT while
optionally deriving YouTube metadata from a URL.

```bash
./StartMe.sh youtube-subtitles "https://youtu.be/VIDEO_ID"
./StartMe.sh youtube-groq --lang auto "https://youtu.be/VIDEO_ID"
./StartMe.sh youtube-speechcore-list --videos 1-3 "PLAYLIST_URL"
```

Subtitle workflows normalize the URL, download SRT with `yt-dlp`, convert it to
custom TXT, and clean it. ASR workflows download audio before provider
transcription. All final wrappers add YouTube source metadata to Markdown.

Use `StartMe.sh help MODE` for options and [FORMATS.md](FORMATS.md) for handoff
formats.

from __future__ import annotations

import subprocess
from pathlib import Path

from multitrack.formats import EventDocument, read_event_document
from multitrack.manifest import TrackSpec

from .base import TranscriptionProvider


class GroqProvider(TranscriptionProvider):
    def __init__(
        self,
        project_root: Path,
        *,
        config_path: Path | None = None,
        log_level: str = "info",
    ) -> None:
        self.project_root = project_root.resolve()
        self.runner = self.project_root / "groq-api/groq_api.sh"
        self.config_path = config_path.expanduser().resolve() if config_path else None
        self.log_level = log_level

    def transcribe(self, track: TrackSpec, work_dir: Path) -> EventDocument:
        if not self.runner.is_file():
            raise RuntimeError(f"Groq runner not found: {self.runner}")
        provider_dir = work_dir / f"track-{track.index:02d}"
        provider_dir.mkdir(parents=True, exist_ok=True)
        events_path = provider_dir / "provider.events.json"
        metadata_path = provider_dir / "provider.metadata.json"
        command = [
            str(self.runner),
            "transcribe",
            "--input-file",
            str(track.file),
            "--output-dir",
            str(provider_dir),
            "--events-output",
            str(events_path),
            "--metadata-output",
            str(metadata_path),
            "--language-suffix",
            "--language",
            track.language,
            "--diarization",
            "on" if track.diarization else "off",
            f"--{self.log_level}",
        ]
        if self.config_path is not None:
            command.extend(["--config", str(self.config_path)])
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                f"Groq transcription failed for track {track.index} "
                f"with exit code {result.returncode}"
            )
        if not events_path.is_file():
            raise RuntimeError(
                f"Groq did not create the expected event file: {events_path}"
            )
        return read_event_document(events_path)

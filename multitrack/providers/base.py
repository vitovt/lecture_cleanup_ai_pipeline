from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from multitrack.formats import EventDocument
from multitrack.manifest import TrackSpec


class TranscriptionProvider(ABC):
    """Adapter boundary between session orchestration and an ASR implementation."""

    @abstractmethod
    def transcribe(self, track: TrackSpec, work_dir: Path) -> EventDocument:
        """Transcribe one track into provider-neutral local-time events."""

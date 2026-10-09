from __future__ import annotations

import json
import logging
import time
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .errors import InputError


@dataclass(frozen=True)
class AudioPart:
    path: Path
    offset: float
    duration: float
    owned_start: float
    owned_end: float


@dataclass
class PreparedAudio:
    parts: list[AudioPart]
    duration: float
    temporary_directory: Path | None = None

    def cleanup(self) -> None:
        if self.temporary_directory:
            shutil.rmtree(self.temporary_directory, ignore_errors=True)


def probe_duration(path: Path) -> float:
    if shutil.which("ffprobe") is None:
        raise InputError("ffprobe is required to inspect audio duration")
    command = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "json", str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise InputError(f"ffprobe could not read {path}: {result.stderr.strip()}")
    try:
        duration = float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise InputError(f"ffprobe returned no usable duration for {path}") from exc
    if duration <= 0:
        raise InputError(f"audio duration must be positive: {path}")
    return duration


def prepare_audio(path: Path, *, max_seconds: float, overlap_seconds: float) -> PreparedAudio:
    duration = probe_duration(path)
    if duration <= max_seconds:
        return PreparedAudio([AudioPart(path, 0.0, duration, 0.0, duration)], duration)
    if shutil.which("ffmpeg") is None:
        raise InputError("ffmpeg is required to split long audio")
    if overlap_seconds < 0 or overlap_seconds >= max_seconds:
        raise InputError("chunk overlap must be non-negative and shorter than the chunk")

    temp_dir = Path(tempfile.mkdtemp(prefix="stt-api-"))
    parts: list[AudioPart] = []
    step = max_seconds - overlap_seconds
    offset = 0.0
    index = 0
    try:
        while offset < duration:
            part_duration = min(max_seconds, duration - offset)
            output = temp_dir / f"part-{index:04d}.flac"
            command = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-ss", str(offset), "-i", str(path), "-t", str(part_duration),
                "-vn", "-ar", "16000", "-ac", "1", "-c:a", "flac", str(output),
            ]
            logging.getLogger("stt-api").info("Preparing audio part %d: offset=%.3fs, duration=%.3fs", index + 1, offset, part_duration)
            started = time.monotonic()
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            if result.returncode != 0 or not output.is_file():
                raise InputError(f"ffmpeg failed to create audio chunk: {result.stderr.strip()}")
            logging.getLogger("stt-api").debug("Audio part %d ready in %.2fs; %d bytes", index + 1, time.monotonic() - started, output.stat().st_size)
            ownership_start = offset if index == 0 else offset + overlap_seconds / 2
            ownership_end = min(duration, offset + part_duration)
            if ownership_end < duration:
                ownership_end -= overlap_seconds / 2
            parts.append(
                AudioPart(output, offset, part_duration, ownership_start, ownership_end)
            )
            if offset + part_duration >= duration:
                break
            offset += step
            index += 1
        return PreparedAudio(parts, duration, temp_dir)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

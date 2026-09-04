from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml


LANGUAGE_RE = re.compile(r"^[a-z]{2}$")
INVALID_LABEL_RE = re.compile(r"[\[\]\r\n]")


class ManifestError(ValueError):
    """The multitrack session manifest is invalid."""


@dataclass(frozen=True)
class TrackSpec:
    index: int
    file: Path
    language: str
    provider: str
    diarization: bool = False
    speaker: str | None = None
    speaker_prefix: str | None = None
    offset_ms: float = 0.0
    events_file: Path | None = None


@dataclass(frozen=True)
class SessionManifest:
    source: Path | None
    language: str | None
    provider: str
    tracks: tuple[TrackSpec, ...]


def _language(value: Any, field: str, *, required: bool) -> str | None:
    if value is None or not str(value).strip():
        if required:
            raise ManifestError(f"{field} is required")
        return None
    language = str(value).strip().lower()
    if language != "auto" and not LANGUAGE_RE.fullmatch(language):
        raise ManifestError(f"{field} must be a two-letter code or 'auto'")
    return language


def _label(value: Any, field: str) -> str | None:
    if value is None:
        return None
    label = str(value).strip()
    if not label:
        raise ManifestError(f"{field} cannot be empty")
    if INVALID_LABEL_RE.search(label):
        raise ManifestError(f"{field} cannot contain brackets or newlines")
    return label


def _bool(value: Any, field: str, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise ManifestError(f"{field} must be true or false")


def _path(value: Any, field: str, base_dir: Path) -> Path:
    if value is None or not str(value).strip():
        raise ManifestError(f"{field} is required")
    path = Path(str(value)).expanduser()
    return (path if path.is_absolute() else base_dir / path).resolve()


def _parse_manifest(data: Any, source: Path | None, base_dir: Path) -> SessionManifest:
    if not isinstance(data, dict):
        raise ManifestError("manifest root must be a mapping")
    top_language = _language(data.get("language"), "language", required=False)
    provider = str(data.get("provider") or "groq").strip().lower()
    if not provider:
        raise ManifestError("provider cannot be empty")
    raw_tracks = data.get("tracks")
    if not isinstance(raw_tracks, list) or not raw_tracks:
        raise ManifestError("tracks must be a non-empty list")

    tracks: list[TrackSpec] = []
    for index, raw in enumerate(raw_tracks):
        field = f"tracks[{index}]"
        if not isinstance(raw, dict):
            raise ManifestError(f"{field} must be a mapping")
        diarization = _bool(raw.get("diarization"), f"{field}.diarization")
        speaker = _label(raw.get("speaker"), f"{field}.speaker")
        speaker_prefix = _label(
            raw.get("speaker_prefix"), f"{field}.speaker_prefix"
        )
        if diarization and speaker is not None:
            raise ManifestError(
                f"{field}.speaker is only valid when diarization is false; "
                "use speaker_prefix for a diarized track"
            )
        if not diarization and speaker_prefix is not None:
            raise ManifestError(
                f"{field}.speaker_prefix is only valid when diarization is true"
            )
        if not diarization and speaker is None:
            speaker = f"SPEAKER_{index:02d}"
        language = _language(
            raw.get("language", top_language),
            f"{field}.language",
            required=True,
        )
        try:
            offset_ms = float(raw.get("offset_ms", 0) or 0)
        except (TypeError, ValueError) as exc:
            raise ManifestError(f"{field}.offset_ms must be a number") from exc
        track_provider = str(raw.get("provider") or provider).strip().lower()
        if not track_provider:
            raise ManifestError(f"{field}.provider cannot be empty")
        events_file = raw.get("events_file")
        tracks.append(
            TrackSpec(
                index=index,
                file=_path(raw.get("file"), f"{field}.file", base_dir),
                language=language or "auto",
                provider=track_provider,
                diarization=diarization,
                speaker=speaker,
                speaker_prefix=speaker_prefix,
                offset_ms=offset_ms,
                events_file=(
                    _path(events_file, f"{field}.events_file", base_dir)
                    if events_file is not None
                    else None
                ),
            )
        )
    return SessionManifest(source, top_language, provider, tuple(tracks))


def load_manifest(path: Path) -> SessionManifest:
    manifest_path = path.expanduser().resolve()
    try:
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ManifestError(f"cannot read manifest {manifest_path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ManifestError(f"invalid YAML in {manifest_path}: {exc}") from exc
    return _parse_manifest(data, manifest_path, manifest_path.parent)


def manifest_from_files(
    files: list[Path],
    language: str,
    provider: str,
    base_dir: Path,
) -> SessionManifest:
    data = {
        "language": language,
        "provider": provider,
        "tracks": [{"file": str(path)} for path in files],
    }
    return _parse_manifest(data, None, base_dir.resolve())


def with_events_files(
    manifest: SessionManifest, events_files: list[Path]
) -> SessionManifest:
    if len(events_files) != len(manifest.tracks):
        raise ManifestError("events file count does not match track count")
    tracks = tuple(
        replace(track, events_file=events_file.resolve())
        for track, events_file in zip(manifest.tracks, events_files)
    )
    return replace(manifest, tracks=tracks)


def write_manifest(manifest: SessionManifest, path: Path) -> Path:
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "language": manifest.language,
        "provider": manifest.provider,
        "tracks": [],
    }
    if data["language"] is None:
        data.pop("language")
    for track in manifest.tracks:
        item: dict[str, Any] = {
            "file": str(track.file),
            "language": track.language,
            "provider": track.provider,
            "diarization": track.diarization,
            "offset_ms": track.offset_ms,
        }
        if track.speaker is not None:
            item["speaker"] = track.speaker
        if track.speaker_prefix is not None:
            item["speaker_prefix"] = track.speaker_prefix
        if track.events_file is not None:
            item["events_file"] = str(track.events_file)
        data["tracks"].append(item)
    destination.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return destination

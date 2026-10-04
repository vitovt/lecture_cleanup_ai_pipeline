"""Stage Markdown updates, preserve originals, and roll back failed writes."""

from __future__ import annotations

import os
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from scripts.summary_document import SummaryError


def snapshot(path: Path) -> bytes | None:
    if path.exists():
        if not path.is_file():
            raise SummaryError("invalid_output", f"Not a regular file: {path}")
        return path.read_bytes()
    return None


def backup_paths(paths, policy, *, timestamp=None):
    stamp = timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S-%f")
    result = {}
    if policy.backups:
        for path in paths:
            if path.exists():
                name = policy.backup_filename.format(stem=path.stem, name=path.name, datetime=stamp)
                backup = path.with_name(name)
                if backup.suffix.lower() != ".md" or backup == path or backup in paths or backup in result.values():
                    raise SummaryError("invalid_backup", f"Backup template produces an unsafe or duplicate path: {backup}")
                if backup.exists():
                    raise SummaryError("backup_exists", f"Backup already exists: {backup}")
                result[path] = backup
    return result


def _stage(path: Path, data: bytes, mode: int) -> Path:
    descriptor, filename = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(filename)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(mode)
        return temporary
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def publish(updates: dict[Path, str], originals: dict[Path, bytes | None], backups: dict[Path, Path]) -> None:
    """Check every observed file, stage all outputs, then publish with rollback.

    Atomicity is per file. Saved originals also permit rollback when backups
    are disabled. A rollback failure reports its affected paths explicitly.
    """
    def check(path):
        if snapshot(path) != originals[path]:
            raise SummaryError("file_changed", f"File changed after planning: {path}")

    for path in originals:
        check(path)
    staged = {}
    rollback = {}
    written = []
    try:
        for path, text in updates.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            mode = stat.S_IMODE(path.stat().st_mode) if originals[path] is not None else 0o644
            staged[path] = _stage(path, text.encode("utf-8"), mode)
            if originals[path] is not None:
                rollback[path] = _stage(path, originals[path], mode)
        for path in originals:
            check(path)
        for path, backup in backups.items():
            # Exclusive creation prevents concurrent runs from losing a backup.
            with backup.open("xb") as handle:
                try:
                    handle.write(originals[path])
                    handle.flush()
                    os.fsync(handle.fileno())
                    os.fchmod(handle.fileno(), stat.S_IMODE(path.stat().st_mode))
                except BaseException:
                    backup.unlink(missing_ok=True)
                    raise
        for path in staged:
            check(path)
            os.replace(staged[path], path)
            written.append(path)
    except BaseException as exc:
        failures = []
        for path in reversed(written):
            try:
                if snapshot(path) != updates[path].encode("utf-8"):
                    failures.append(str(path))
                elif originals[path] is None:
                    path.unlink()
                else:
                    os.replace(rollback[path], path)
            except OSError:
                failures.append(str(path))
        if failures:
            raise SummaryError("partial_write", "Cannot restore changed files: " + ", ".join(failures)) from exc
        raise
    finally:
        for temporary in (*staged.values(), *rollback.values()):
            temporary.unlink(missing_ok=True)

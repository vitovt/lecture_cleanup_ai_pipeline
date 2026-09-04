#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from multitrack.manifest import (  # noqa: E402
    ManifestError,
    load_manifest,
    manifest_from_files,
    write_manifest,
)
from multitrack.providers import create_provider  # noqa: E402
from multitrack.transcription import transcribe_manifest  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Transcribe session audio tracks into provider-neutral event files."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--manifest", type=Path, help="Session YAML manifest.")
    source.add_argument(
        "--no-manifest",
        action="store_true",
        help="Build and save a manifest from repeatable --file arguments.",
    )
    parser.add_argument("--file", type=Path, action="append", default=[])
    parser.add_argument("--lang", help="Default language for --no-manifest mode.")
    parser.add_argument("--provider", default="groq")
    parser.add_argument("--provider-config", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("multitrack-work"))
    parser.add_argument("--resolved-manifest", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--log-level",
        choices=("quiet", "error", "info", "debug", "trace"),
        default="info",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.no_manifest:
        if not args.file:
            parser.error("--no-manifest requires at least one --file FILE")
        if not args.lang:
            parser.error("--no-manifest requires --lang CODE|auto")
        manifest = manifest_from_files(
            args.file,
            args.lang,
            args.provider,
            Path.cwd(),
        )
    else:
        if args.file or args.lang:
            parser.error("--file and --lang are only valid with --no-manifest")
        try:
            manifest = load_manifest(args.manifest)
        except ManifestError as exc:
            parser.error(str(exc))

    output_dir = args.output_dir.expanduser().resolve()
    resolved_path = (
        args.resolved_manifest.expanduser().resolve()
        if args.resolved_manifest
        else output_dir / "resolved-manifest.yaml"
    )
    providers = {}

    def provider_factory(name: str):
        if name not in providers:
            providers[name] = create_provider(
                name,
                PROJECT_ROOT,
                config_path=args.provider_config,
                log_level=args.log_level,
            )
        return providers[name]

    try:
        resolved = transcribe_manifest(
            manifest,
            output_dir,
            provider_factory,
            overwrite=args.overwrite,
        )
        write_manifest(resolved, resolved_path)
    except (FileNotFoundError, ManifestError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Resolved manifest: {resolved_path}")
    for track in resolved.tracks:
        print(f"Track {track.index}: {track.events_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

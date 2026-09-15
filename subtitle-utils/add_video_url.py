#!/usr/bin/env python3

import argparse
import difflib
import os
import stat
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.source_timecode_core import (
    HEADING_RE,
    find_inline_markers,
    is_local_target,
    parse_below_marker,
    protected_line_mask,
    render_below_marker,
    render_inline_marker,
    timestamp_url,
    youtube_base_url,
)


def video_url(value):
    """argparse validator + normalization for a YouTube URL."""
    try:
        _, base_url = youtube_base_url(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("invalid URL: %s" % exc)
    return base_url


def convert(text, base_url):
    output = []
    changed = 0
    lines = text.splitlines(keepends=True)
    if not lines and text:
        lines = [text]
    protected = protected_line_mask(lines)

    for index, line in enumerate(lines):
        if protected[index]:
            output.append(line)
            continue

        heading = HEADING_RE.match(line)
        if heading:
            body = heading.group("body")
            for marker in reversed(find_inline_markers(body)):
                if not is_local_target(marker.target):
                    continue
                if marker.seconds is None:
                    raise ValueError(marker.error or "invalid timestamp")
                replacement = render_inline_marker(
                    marker.label,
                    timestamp_url(base_url, marker.seconds),
                )
                body = body[:marker.start] + replacement + body[marker.end:]
                changed += 1
            output.append(
                heading.group("bom")
                + heading.group("prefix")
                + body
                + (heading.group("eol") or "")
            )
            continue

        line_body = line.rstrip("\r\n")
        eol = line[len(line_body):]
        stripped = line_body.strip()
        below = parse_below_marker(stripped)
        if below and is_local_target(below.target):
            if below.seconds is None:
                raise ValueError(below.error or "invalid timestamp")
            leading = line_body[:len(line_body) - len(line_body.lstrip())]
            trailing = line_body[len(line_body.rstrip()):]
            changed += 1
            output.append(
                leading
                + render_below_marker(
                    below.label,
                    timestamp_url(base_url, below.seconds),
                )
                + trailing
                + eol
            )
            continue

        output.append(line)

    # Empty file: splitlines(True) returns [].
    return ("".join(output) if output else text), changed


def unified_diff(original, generated, source_path):
    generated_path = source_path.with_name(
        "%s.generated%s" % (source_path.stem, source_path.suffix)
    )
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            generated.splitlines(keepends=True),
            fromfile=str(source_path),
            tofile=str(generated_path),
            n=3,
        )
    )


def check_input(path):
    if path.suffix.lower() != ".md":
        raise ValueError("input file must have a .md extension: %s" % path)
    if not path.exists():
        raise ValueError("input file does not exist: %s" % path)
    if not path.is_file():
        raise ValueError("input path is not a regular file: %s" % path)


def check_output(path):
    if path.suffix.lower() != ".md":
        raise ValueError("output file must have a .md extension: %s" % path)
    if not path.parent.exists():
        raise ValueError("output directory does not exist: %s" % path.parent)
    if not path.parent.is_dir():
        raise ValueError("output parent is not a directory: %s" % path.parent)
    if path.exists() and not path.is_file():
        raise ValueError("output path is not a regular file: %s" % path)


def read_file(path):
    try:
        # newline="" preserves original line endings. UTF-8 BOM, if present,
        # is preserved as U+FEFF and handled by HEADING_RE on the first line.
        with path.open("r", encoding="utf-8", newline="") as f:
            return f.read()
    except UnicodeDecodeError as exc:
        raise ValueError("input is not valid UTF-8 near byte %d" % exc.start)
    except OSError as exc:
        raise ValueError("cannot read '%s': %s" % (path, exc))


def atomic_write(path, text, source_path):
    """Safely supports: -o FILENAME FILENAME."""
    try:
        mode_source = path if path.exists() else source_path
        mode = stat.S_IMODE(mode_source.stat().st_mode)
    except OSError:
        mode = None

    fd = None
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(
            prefix=".%s." % path.name,
            suffix=".tmp",
            dir=str(path.parent),
        )
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            fd = None
            f.write(text)
            f.flush()
            os.fsync(f.fileno())

        if mode is not None:
            os.chmod(tmp, mode)

        # Atomic on the same filesystem. Original file is replaced only after
        # the temporary file has been fully written.
        os.replace(tmp, path)
        tmp = None
    except OSError as exc:
        raise ValueError("cannot write '%s': %s" % (path, exc))
    finally:
        if fd is not None:
            os.close(fd)
        if tmp is not None:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass


def parser():
    p = argparse.ArgumentParser(
        prog="add_video_url.py",
        description=(
            "Add a YouTube URL independently to local timestamps in Markdown "
            "headings and standalone [🎥 HH:MM:SS](#) lines."
        ),
        epilog=(
            "Without -o or --diff, Markdown is written to stdout. With -o, "
            "OUTFILE is written atomically and may be the same file as "
            "FILENAME. --diff prints a unified three-line-context preview."
        ),
    )
    p.add_argument(
        "-u", "--url", required=True, type=video_url, metavar="VIDEO_URL",
        help="YouTube URL, e.g. https://youtu.be/RQFO6xsXt3k",
    )
    destination = p.add_mutually_exclusive_group()
    destination.add_argument(
        "-o", "--output", metavar="OUTFILE.md",
        help="write result to this .md file instead of stdout",
    )
    destination.add_argument(
        "--diff",
        action="store_true",
        help="print a unified diff with three context lines",
    )
    p.add_argument("filename", metavar="FILENAME.md", help="input Markdown file")
    return p


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    p = parser()

    # Explicit requirement: no arguments => help, not an argparse error.
    if not argv:
        p.print_help(sys.stdout)
        return 0

    args = p.parse_args(argv)
    src = Path(args.filename)
    dst = Path(args.output) if args.output else None

    try:
        check_input(src)
        if dst:
            check_output(dst)

        text = read_file(src)
        result, changed = convert(text, args.url)

        if changed == 0:
            print(
                "warning: no local heading or below timestamp needs a URL; "
                "output is unchanged",
                file=sys.stderr,
            )

        if dst:
            atomic_write(dst, result, src)
            print("converted %d timestamp link(s) -> %s" % (changed, dst), file=sys.stderr)
        elif args.diff:
            sys.stdout.write(unified_diff(text, result, src))
        else:
            # stdout contains Markdown only; diagnostics go to stderr.
            sys.stdout.write(result)

    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())

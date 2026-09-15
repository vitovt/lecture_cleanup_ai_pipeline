#!/usr/bin/env python3

import argparse
import difflib
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

YOUTUBE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
    "youtu.be", "www.youtu.be",
    "youtube-nocookie.com", "www.youtube-nocookie.com",
}

# Only ATX Markdown headings (# ... through ###### ...).
HEADING_RE = re.compile(
    r"^(?P<bom>\ufeff?)(?P<prefix>[ \t]{0,3}#{1,6}[ \t]+)"
    r"(?P<body>[^\r\n]*)(?P<eol>\r\n|\n|\r)?$"
)

TIME_LABEL = r"\d{1,3}:\d{2}(?::\d{2})?"
LOCAL_TARGET = r"(?:\(\s*#(?:t=[^)\s]+)?\s*\)|(?!\())"
INLINE_TIMECODE_RE = re.compile(
    rf"\[(?P<label>{TIME_LABEL})\]{LOCAL_TARGET}"
)
BELOW_TIMECODE_RE = re.compile(
    rf"\[🎥[ \t]+(?P<label>{TIME_LABEL})\]{LOCAL_TARGET}"
)


def video_url(value):
    """argparse validator + normalization for a YouTube URL."""
    try:
        p = urlsplit(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("invalid URL: %s" % exc)

    if p.scheme not in ("http", "https") or not p.netloc:
        raise argparse.ArgumentTypeError(
            "video URL must be an absolute http:// or https:// URL"
        )

    host = (p.hostname or "").lower()
    if host not in YOUTUBE_HOSTS:
        raise argparse.ArgumentTypeError(
            "unsupported host '%s'; expected a YouTube URL" % host
        )

    query = dict(parse_qsl(p.query, keep_blank_values=True))
    path = p.path.rstrip("/")

    if host in ("youtu.be", "www.youtu.be"):
        if not path.lstrip("/").split("/", 1)[0]:
            raise argparse.ArgumentTypeError("youtu.be URL has no video ID")
    elif path == "/watch":
        if not query.get("v"):
            raise argparse.ArgumentTypeError(
                "youtube.com/watch URL has no 'v' video ID"
            )
    elif path.startswith(("/shorts/", "/live/", "/embed/")):
        if len(path.split("/")) < 3 or not path.split("/", 2)[2]:
            raise argparse.ArgumentTypeError("YouTube URL has no video ID")
    else:
        raise argparse.ArgumentTypeError(
            "unsupported YouTube URL form; use youtu.be/<id>, "
            "youtube.com/watch?v=<id>, /shorts/<id>, /live/<id>, or /embed/<id>"
        )

    # Remove a pre-existing timestamp and fragment. Every marker gets its own time.
    q = [
        (k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
        if k.lower() not in ("t", "start", "time_continue")
    ]
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q, doseq=True), ""))


def time_to_seconds(value):
    """Accept 427s, 427, MM:SS or HH:MM:SS."""
    value = value.strip()

    m = re.fullmatch(r"\d+s?", value, flags=re.IGNORECASE)
    if m:
        return int(value[:-1] if value.lower().endswith("s") else value)

    parts = value.split(":")
    if len(parts) not in (2, 3) or not all(x.isdigit() for x in parts):
        raise ValueError("expected seconds, MM:SS, or HH:MM:SS")

    nums = [int(x) for x in parts]
    if len(nums) == 2:
        minutes, seconds = nums
        if seconds > 59:
            raise ValueError("seconds must be 00..59")
        return minutes * 60 + seconds

    hours, minutes, seconds = nums
    if minutes > 59 or seconds > 59:
        raise ValueError("minutes and seconds must be 00..59")
    return hours * 3600 + minutes * 60 + seconds


def timestamp_url(base_url, seconds):
    p = urlsplit(base_url)
    q = [
        (k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
        if k.lower() not in ("t", "start", "time_continue")
    ]
    q.append(("t", "%ds" % seconds))
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q, doseq=True), ""))


def convert(text, base_url):
    output = []
    changed = 0

    # splitlines(True) preserves LF/CRLF line endings.
    for line in text.splitlines(True):
        def replace_inline(match):
            nonlocal changed
            label = match.group("label")
            changed += 1
            return "[%s](%s)" % (
                label,
                timestamp_url(base_url, time_to_seconds(label)),
            )

        heading = HEADING_RE.match(line)
        if heading:
            body = INLINE_TIMECODE_RE.sub(replace_inline, heading.group("body"))
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
        below = BELOW_TIMECODE_RE.fullmatch(stripped)
        if below:
            label = below.group("label")
            leading = line_body[:len(line_body) - len(line_body.lstrip())]
            trailing = line_body[len(line_body.rstrip()):]
            changed += 1
            output.append(
                leading
                + "[🎥 %s](%s)" % (
                    label,
                    timestamp_url(base_url, time_to_seconds(label)),
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

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


class StartMeCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.project = root / "project with spaces"
        self.caller = root / "caller with spaces"
        self.bin = root / "bin"
        for directory in (self.project, self.caller, self.bin):
            directory.mkdir()
        for name in ("StartMe.sh", "lecture_cleanup.sh"):
            shutil.copy2(PROJECT / name, self.project / name)

        # Run the real dispatcher and cleanup shell boundary, replacing only
        # Python execution so these tests cannot call an LLM or use local keys.
        venv = self.project / ".venv/bin"
        venv.mkdir(parents=True)
        (venv / "activate").write_text(":\n", encoding="utf-8")
        probe = self.bin / "python3"
        probe.write_text(
            f"#!{sys.executable}\n"
            "import json, sys\n"
            "from pathlib import Path\n"
            "if '--help' in sys.argv:\n"
            "    print('usage: run_pipeline --input INPUT --lang LANG --outdir OUTDIR')\n"
            "else:\n"
            "    print(json.dumps({'cwd': str(Path.cwd()), 'args': sys.argv[1:]}))\n",
            encoding="utf-8",
        )
        probe.chmod(0o755)
        self.env = os.environ.copy()
        self.env.pop("CLEANUP_MDOUTDIR", None)
        self.env["PATH"] = f"{self.bin}:{self.env['PATH']}"
        (self.caller / "lecture.txt").write_text("Transcript\n", encoding="utf-8")

    def run_startme(self, *args: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.project / "StartMe.sh"), *(str(arg) for arg in args)],
            cwd=self.caller,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

    def cleanup_args(self, *args: object) -> list[str]:
        result = self.run_startme("cleanup", *args)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        captured = json.loads(result.stdout)
        self.assertEqual(captured["cwd"], str(self.project))
        self.assertEqual(captured["args"][:2], ["-m", "scripts.run_pipeline"])
        return captured["args"][2:]

    def test_relative_paths_and_repeated_contexts_use_caller_directory(self) -> None:
        args = self.cleanup_args(
            "--input", "lecture.txt", "--lang", "en", "--outdir", "notes",
            "--context-file", "context one.txt", "--context-file", "context two.txt",
            "--glossary", "terms.txt", "--qc-report", "default_outdir", "--debug",
        )
        self.assertEqual(args, [
            "--input", str(self.caller / "lecture.txt"), "--lang", "en",
            "--outdir", str(self.caller / "notes"),
            "--context-file", str(self.caller / "context one.txt"),
            "--context-file", str(self.caller / "context two.txt"),
            "--glossary", str(self.caller / "terms.txt"),
            "--qc-report", "default_outdir", "--debug",
        ])
        self.assertTrue(Path(args[1]).is_file())

    def test_equals_options_resolve_paths_and_preserve_other_arguments(self) -> None:
        args = self.cleanup_args(
            "--input=lecture.txt", "--lang=en", "--outdir=notes",
            "--context-file=context one.txt", "--context-file=context two.txt",
            "--glossary=terms.txt", "--chunks=1,3-5",
        )
        self.assertEqual(args, [
            f"--input={self.caller / 'lecture.txt'}", "--lang=en",
            f"--outdir={self.caller / 'notes'}",
            f"--context-file={self.caller / 'context one.txt'}",
            f"--context-file={self.caller / 'context two.txt'}",
            f"--glossary={self.caller / 'terms.txt'}", "--chunks=1,3-5",
        ])

    def test_absolute_paths_are_preserved(self) -> None:
        expected = [
            "--input", str(self.caller / "lecture.txt"),
            "--lang", "en", "--outdir", str(self.caller / "notes"),
            "--context-file", str(self.caller / "context.txt"),
            "--glossary", str(self.caller / "terms.txt"),
        ]
        self.assertEqual(self.cleanup_args(*expected), expected)

    def test_env_output_expands_home_and_cannot_override_dispatcher(self) -> None:
        (self.project / ".env").write_text(
            'CLEANUP_MDOUTDIR="$HOME/Desktop/obsidian"\n'
            'MODE="invalid"\nTARGET="/invalid"\nSCRIPT_DIR="/invalid"\n',
            encoding="utf-8",
        )
        args = self.cleanup_args("--input", "lecture.txt", "--lang", "en")
        self.assertEqual(args[-2:], [
            "--outdir", str(Path(self.env["HOME"]) / "Desktop/obsidian"),
        ])

    def test_relative_env_output_uses_caller_directory(self) -> None:
        (self.project / ".env").write_text(
            'CLEANUP_MDOUTDIR="notes"\n', encoding="utf-8",
        )
        args = self.cleanup_args("--input", "lecture.txt", "--lang", "en")
        self.assertEqual(args[-2:], ["--outdir", str(self.caller / "notes")])

    def test_explicit_output_overrides_env_for_both_option_forms(self) -> None:
        (self.project / ".env").write_text(
            'CLEANUP_MDOUTDIR="/configured/output"\n', encoding="utf-8",
        )
        for option in (("--outdir", "notes"), ("--outdir=notes",)):
            with self.subTest(option=option):
                args = self.cleanup_args("--input", "lecture.txt", "--lang", "en", *option)
                self.assertNotIn("/configured/output", args)
                self.assertEqual(
                    args[4:],
                    ["--outdir", str(self.caller / "notes")]
                    if len(option) == 2 else [f"--outdir={self.caller / 'notes'}"],
                )

    def test_missing_or_empty_env_output_preserves_project_default(self) -> None:
        for content in (None, 'CLEANUP_MDOUTDIR=""\n'):
            with self.subTest(content=content):
                if content is not None:
                    (self.project / ".env").write_text(content, encoding="utf-8")
                args = self.cleanup_args("--input", "lecture.txt", "--lang", "en")
                self.assertNotIn("--outdir", args)

    def test_missing_path_values_fail_before_delegating(self) -> None:
        for option in ("--input", "--outdir", "--context-file", "--glossary"):
            for tail in ((), ("",), ("--lang", "en")):
                with self.subTest(option=option, tail=tail):
                    result = self.run_startme("cleanup", option, *tail)
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, "")
                    self.assertIn(f"{option} requires a path", result.stderr)
            with self.subTest(option=f"{option}="):
                result = self.run_startme("cleanup", f"{option}=")
                self.assertEqual(result.returncode, 2)
                self.assertIn(f"{option} requires a path", result.stderr)

    def test_both_help_entrypoints_include_wrapper_rules(self) -> None:
        for arguments in (("help", "cleanup"), ("cleanup", "--help"), ("cleanup", "-h")):
            with self.subTest(arguments=arguments):
                result = self.run_startme(*arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage: run_pipeline", result.stdout)
                self.assertIn("CLEANUP_MDOUTDIR", result.stdout)
                self.assertIn("--context-file", result.stdout)
                self.assertIn("--qc-report", result.stdout)

    def test_other_modes_do_not_load_cleanup_env_or_transform_paths(self) -> None:
        (self.project / ".env").write_text('exit 99\n', encoding="utf-8")
        target = self.project / "bulk_cleanup.sh"
        target.write_text(
            '#!/usr/bin/env bash\nexec python3 "$@"\n', encoding="utf-8",
        )
        target.chmod(0o755)
        expected = ["--indir", "notes", "--outdir", "output", "--lang", "en"]
        result = self.run_startme("cleanup-list", *expected)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            "cwd": str(self.caller), "args": expected,
        })

    def test_direct_cleanup_retains_relative_paths_and_ignores_new_env(self) -> None:
        (self.project / ".env").write_text('exit 99\n', encoding="utf-8")
        expected = ["--input", "lecture.txt", "--lang", "en"]
        result = subprocess.run(
            [str(self.project / "lecture_cleanup.sh"), *expected],
            cwd=self.caller, env=self.env, text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            "cwd": str(self.project), "args": ["-m", "scripts.run_pipeline", *expected],
        })


if __name__ == "__main__":
    unittest.main()

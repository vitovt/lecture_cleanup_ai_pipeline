from __future__ import annotations

import copy
import importlib.util
import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import yaml

from aiadapters.base import LLMAuthError, LLMConnectionError
from scripts.heading_references import HeadingReferenceOptions, render_heading_references
from scripts.summary_document import inventory
from scripts.summary_generation import (
    LONG_SUMMARY_START, LONG_SUMMARY_END, SHORT_SUMMARY_START, SHORT_SUMMARY_END,
    _summary_block,
)
from scripts.summary_references import collect_source_blocks
from scripts.summary_storage import publish


PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("add_summary_tool", PROJECT / "subtitle-utils/add_summary.py")
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


class SummaryAdapter:
    def __init__(self):
        self.calls = []
        self.fail_at = None
        self.failure = LLMAuthError
        self.mutate = None
        self.invalid_reference = False

    def name(self):
        return "test"

    def generate(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if self.fail_at == len(self.calls):
            raise self.failure("test failure")
        if self.mutate:
            self.mutate()
        system = messages[0]["content"]
        source = messages[1]["content"].split("<<<\n", 1)[-1].rsplit("\n>>>", 1)[0]
        references = "### Source traceability" in system
        long = "### 0️⃣ Overview\n"
        if references:
            prefix = "SOURCE" if "[[SOURCE#" in system else ""
            blocks = collect_source_blocks(source)
            identifier, block = next(iter(blocks.items()))
            if self.invalid_reference:
                identifier = "src-999999"
            label = f"Source · {block.timestamp}" if block.timestamp else "Source"
            long += f"↩ [[{prefix}#^{identifier}|{label}]]\n"
        long += "\nLong result\n"
        short = "### Overview\n\nShort result\n"
        if "[LONG SUMMARY SYSTEM INSTRUCTIONS]" in system:
            return f"{LONG_SUMMARY_START}\n{long}{LONG_SUMMARY_END}\n{SHORT_SUMMARY_START}\n{short}{SHORT_SUMMARY_END}"
        return long if "lecture reconstruction" in system else short


class SummaryRegenerationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "My lecture.md"
        self.original = "# Lecture\n\n### Timed [00:01:00](#t=60s)\nFacts from the source.\n\n### Untimed\nFurther facts.\n"
        self.source.write_text(self.original, encoding="utf-8")
        self.cfg = yaml.safe_load((PROJECT / "config.default.yaml").read_text(encoding="utf-8"))
        self.cfg["summary"]["short"].update(enabled=True, lang="uk")
        self.cfg["summary"]["long"].update(enabled=True, lang="uk")
        self.cfg["llm"].update(provider="dummy", dummy={"model": "test-model"}, request_delay_seconds=0)
        self.cfg["retry"].update(attempts=1, pause_seconds=0)
        self.cfg["logging"]["level"] = "info"
        self.adapter = SummaryAdapter()

    def invoke(self, *args):
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(TOOL, "load_effective_config", return_value=(copy.deepcopy(self.cfg), True)), patch(
            "scripts.summary_regeneration.create_llm_adapter", return_value=self.adapter,
        ) as factory, redirect_stdout(output), redirect_stderr(errors):
            status = TOOL.main([str(self.source), *map(str, args)])
        return status, output.getvalue(), errors.getvalue(), factory

    def blocks(self, path=None):
        path = path or self.source
        return inventory(path, path.read_text(encoding="utf-8"))

    def append_existing(self, kind="long", lang="uk", identifier="existing", body="Old result"):
        text = self.source.read_text(encoding="utf-8")
        block = _summary_block(kind, body, "## Summary", metadata={"id": identifier, "lang": lang, "source": str(self.source)})
        self.source.write_text(text + "\n" + block + "\n", encoding="utf-8")

    def test_quiet_suppresses_errors_without_changing_failure_status(self):
        self.cfg['logging']['level'] = 'quiet'
        self.source.unlink()
        status, output, errors, factory = self.invoke()
        self.assertNotEqual(status, 0)
        self.assertEqual(output, '')
        self.assertEqual(errors, '')
        factory.assert_not_called()

    def test_both_use_one_request_and_backup_original(self):
        status, _, errors, _ = self.invoke()
        self.assertEqual(status, 0, errors)
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertEqual([block.kind for block in self.blocks()], ["long", "short"])
        self.assertEqual({block.language for block in self.blocks()}, {"uk"})
        self.assertEqual(len({block.identifier for block in self.blocks()}), 2)
        self.assertEqual(next(self.root.glob("*-bak.md")).read_text(encoding="utf-8"), self.original)

    def test_default_skip_generates_only_missing_type(self):
        self.append_existing()
        status, _, errors, _ = self.invoke()
        self.assertEqual(status, 0, errors)
        self.assertEqual([block.kind for block in self.blocks()], ["long", "short"])
        self.assertIn("Old result", self.source.read_text(encoding="utf-8"))
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertNotIn("Old result", self.adapter.calls[0][0][1]["content"])
        self.assertNotIn("[LONG SUMMARY SYSTEM INSTRUCTIONS]", self.adapter.calls[0][0][0]["content"])

    def test_all_skipped_have_no_requests_or_backups(self):
        self.append_existing("long", identifier="long-old")
        self.append_existing("short", identifier="short-old")
        before = self.source.read_bytes()
        status, output, _, factory = self.invoke()
        self.assertEqual(status, 0)
        self.assertIn("llm_requests=0", output)
        factory.assert_not_called()
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(list(self.root.glob("*-bak.md")), [])

    def test_add_allows_same_type_and_language_repeatedly(self):
        self.append_existing()
        for _ in range(2):
            status, _, errors, _ = self.invoke("--type", "long", "--on-existing", "add", "--no-backup")
            self.assertEqual(status, 0, errors)
            self.assertIn("duplicate_summary", errors)
        self.assertEqual(len(self.blocks()), 3)
        self.assertEqual(len({block.identifier for block in self.blocks()}), 3)

    def test_another_language_is_added_without_replacing_original(self):
        self.append_existing()
        status, _, errors, _ = self.invoke("--type", "long", "--lang", "en")
        self.assertEqual(status, 0, errors)
        self.assertEqual([block.language for block in self.blocks()], ["uk", "en"])

    def test_replace_preserves_id_position_and_other_summary(self):
        self.append_existing("long", identifier="long-old")
        self.append_existing("short", identifier="short-old", body="Keep short")
        status, _, errors, _ = self.invoke("--type", "long", "--on-existing", "replace")
        self.assertEqual(status, 0, errors)
        self.assertEqual([block.identifier for block in self.blocks()], ["long-old", "short-old"])
        text = self.source.read_text(encoding="utf-8")
        self.assertNotIn("Old result", text)
        self.assertIn("Keep short", text)

    def test_multiple_matches_require_target_before_api(self):
        self.append_existing(identifier="one")
        self.append_existing(identifier="two")
        status, _, errors, factory = self.invoke("--type", "long", "--on-existing", "replace")
        self.assertEqual(status, 2)
        self.assertIn("ambiguous_summary", errors)
        factory.assert_not_called()
        status, _, errors, _ = self.invoke("--type", "long", "--on-existing", "replace", "--target", "two")
        self.assertEqual(status, 0, errors)
        self.assertIn("Old result", self.source.read_text(encoding="utf-8"))
        self.assertEqual([block.identifier for block in self.blocks()], ["one", "two"])

    def test_target_all_keeps_each_language_and_count(self):
        self.append_existing(identifier="one", lang="uk")
        self.append_existing(identifier="two", lang="en")
        status, _, errors, _ = self.invoke("--type", "long", "--on-existing", "replace", "--target", "all")
        self.assertEqual(status, 0, errors)
        self.assertEqual([block.language for block in self.blocks()], ["uk", "en"])
        self.assertEqual([block.identifier for block in self.blocks()], ["one", "two"])
        self.assertEqual(len(self.adapter.calls), 2)

    def test_conflict_error_is_reported_by_dry_run_without_calls(self):
        self.append_existing()
        status, output, errors, factory = self.invoke("--on-existing", "error", "--dry-run")
        self.assertEqual(status, 2)
        self.assertIn("SOURCE lines=", output)
        self.assertIn("summary_exists", errors)
        factory.assert_not_called()

    def test_dry_run_reports_exclusions_writes_ids_backups(self):
        self.cfg["summary"]["long"]["references"]["enabled"] = True
        self.source.write_text(self.original + '<!-- unsures: diagnostic -->\n## Summary\nLegacy result\n', encoding="utf-8")
        before = self.source.read_bytes()
        status, output, errors, factory = self.invoke("--dry-run", "--replace-legacy-tail")
        self.assertEqual(status, 0, errors)
        self.assertIn("legacy summary tail", output)
        self.assertIn("service comment", output)
        self.assertIn("SOURCE_EDIT action=add_ids", output)
        self.assertIn("action=replace_legacy_tail", output)
        self.assertIn("BACKUP", output)
        self.assertIn("llm_requests=0 writes=0", output)
        factory.assert_not_called()
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(list(self.root.glob("*-bak.md")), [])

    def test_legacy_default_skip_add_and_replace(self):
        self.source.write_text(self.original + "## SUMMARY\nLegacy body\n", encoding="utf-8")
        status, _, _, factory = self.invoke()
        self.assertEqual(status, 0)
        factory.assert_not_called()
        status, _, errors, _ = self.invoke("--on-existing", "add", "--no-backup")
        self.assertEqual(status, 0, errors)
        self.assertIn("Legacy body", self.source.read_text(encoding="utf-8"))
        self.assertNotIn("Legacy body", self.adapter.calls[-1][0][1]["content"])
        status, _, errors, _ = self.invoke("--replace-legacy-tail")
        self.assertEqual(status, 0, errors)
        self.assertNotIn("Legacy body", self.source.read_text(encoding="utf-8"))
        self.assertEqual(len(self.blocks()), 2)

    def test_keyword_and_case_sensitivity_are_configurable(self):
        self.cfg["summary_regeneration"]["legacy"].update(heading_words=["Підсумок"], case_sensitive=True)
        self.source.write_text(self.original + "## підсумок\nKeep this\n## Підсумок\nDrop this\n", encoding="utf-8")
        status, output, errors, factory = self.invoke("--print-source")
        self.assertEqual(status, 0, errors)
        self.assertIn("Keep this", output)
        self.assertNotIn("Drop this", output)
        factory.assert_not_called()
        status, output, _, _ = self.invoke("--print-source", "--legacy-ignore-case")
        self.assertEqual(status, 0)
        self.assertNotIn("Keep this", output)
        status, output, _, _ = self.invoke("--print-source", "--no-legacy-summary-detection")
        self.assertEqual(status, 0)
        self.assertIn("Drop this", output)

    def test_comment_filter_ignores_diagnostics_but_preserves_code(self):
        comments = ('<!-- filler_removed: x -->\n<!-- unsures: y -->\n'
                    '<!-- model: old-model -->\n<!-- useful: retain -->\n'
                    '```html\n<!-- rephrased: example -->\nMeaningful code\n```\n'
                    '```php-template\n<!-- unsures: diagnostic -->\n<!-- END: part -->\n```\n')
        self.source.write_text(self.original + comments, encoding="utf-8")
        status, output, errors, _ = self.invoke("--print-source")
        self.assertEqual(status, 0, errors)
        self.assertNotIn("old-model", output)
        self.assertNotIn("diagnostic", output)
        self.assertNotIn("filler_removed", output)
        self.assertIn("useful: retain", output)
        self.assertIn("rephrased: example", output)
        status, output, _, _ = self.invoke("--print-source", "--comments", "all")
        self.assertEqual(status, 0)
        self.assertNotIn("useful: retain", output)
        self.assertIn("Meaningful code", output)

    def test_setext_legacy_heading_and_code_heading_examples(self):
        self.source.write_text(self.original + "```md\n## Summary\nExample\n```\n\nSummary\n=======\nOld tail\n", encoding="utf-8")
        status, output, errors, _ = self.invoke("--print-source")
        self.assertEqual(status, 0, errors)
        self.assertIn("Example", output)
        self.assertNotIn("Old tail", output)

    def test_frontmatter_never_resolves_default_language(self):
        self.cfg["summary"]["short"]["lang"] = "default"
        self.source.write_text("---\nlanguage: uk\n---\n" + self.original, encoding="utf-8")
        status, _, errors, factory = self.invoke("--type", "short")
        self.assertEqual(status, 2)
        self.assertIn("explicit --lang", errors)
        factory.assert_not_called()
        status, _, errors, _ = self.invoke("--type", "short", "--lang", "en")
        self.assertEqual(status, 0, errors)
        self.assertNotIn("language: uk", self.adapter.calls[0][0][1]["content"])

    def test_normalized_default_language_also_requires_explicit_option(self):
        self.cfg["summary"]["short"]["lang"] = " DEFAULT "
        status, _, errors, factory = self.invoke("--type", "short")
        self.assertEqual(status, 2, errors)
        self.assertIn("explicit --lang", errors)
        factory.assert_not_called()

    def test_inline_comment_does_not_hide_legacy_heading(self):
        self.source.write_text(self.original + "## Summary <!-- old model -->\nOld tail\n", encoding="utf-8")
        status, source, errors, factory = self.invoke("--print-source")
        self.assertEqual(status, 0, errors)
        self.assertNotIn("Old tail", source)
        self.assertIn("Facts from the source", source)
        factory.assert_not_called()

    def test_connection_failure_retries_using_tool_specific_settings(self):
        self.cfg["summary_regeneration"]["retry"] = {"attempts": 2, "pause_seconds": 0}
        self.adapter.fail_at = 1
        self.adapter.failure = LLMConnectionError
        status, _, errors, _ = self.invoke("--type", "short")
        self.assertEqual(status, 0, errors)
        self.assertEqual(len(self.adapter.calls), 2)
        self.assertEqual(len(self.blocks()), 1)

    def test_regeneration_overrides_and_null_inheritance(self):
        self.cfg["summary_regeneration"]["short"] = {"lang": "en", "output": "separate", "enabled": True}
        self.cfg["summary_regeneration"]["long"] = {"enabled": False, "lang": None}
        self.cfg["summary_regeneration"]["llm"] = {"dummy": {"model": "stronger-model"}}
        status, _, errors, _ = self.invoke()
        self.assertEqual(status, 0, errors)
        self.assertEqual(self.source.read_text(encoding="utf-8"), self.original)
        self.assertEqual(self.blocks(self.root / "My lecture-summary.md")[0].language, "en")
        self.assertEqual(self.adapter.calls[0][1]["model"], "stronger-model")
        self.assertIn("`en`", self.adapter.calls[0][0][0]["content"])

    def test_external_output_keeps_source_and_adds_relative_links(self):
        self.cfg["summary"]["long"]["references"]["enabled"] = True
        original = render_heading_references(self.original, HeadingReferenceOptions(include_src=True, include_txt_for_untimed=True, only_add_ids=True)).markdown
        self.source.write_text(original, encoding="utf-8")
        directory = self.root / "summaries"
        status, _, errors, _ = self.invoke("--output", "separate", "--outdir", directory)
        self.assertEqual(status, 0, errors)
        self.assertEqual(self.source.read_text(encoding="utf-8"), original)
        long = directory / "My lecture-longsummary.md"
        self.assertIn("../My%20lecture.md#^txt-1", long.read_text(encoding="utf-8"))
        self.assertTrue((directory / "My lecture-summary.md").is_file())
        self.assertEqual(list(self.root.glob("*-bak.md")), [])

    def test_external_duplicate_filenames_do_not_overwrite(self):
        for _ in range(3):
            status, _, errors, _ = self.invoke("--type", "short", "--output", "separate", "--on-existing", "add")
            self.assertEqual(status, 0, errors)
        self.assertTrue((self.root / "My lecture-summary.md").exists())
        self.assertTrue((self.root / "My lecture-summary.uk.md").exists())
        self.assertTrue((self.root / "My lecture-summary.uk.2.md").exists())
        self.assertEqual(self.source.read_text(encoding="utf-8"), self.original)

    def test_default_missing_ids_adds_standard_ids_and_backs_up_source(self):
        self.cfg["summary"]["long"]["references"]["enabled"] = True
        status, _, errors, _ = self.invoke("--type", "long", "--output", "separate")
        self.assertEqual(status, 0, errors)
        text = self.source.read_text(encoding="utf-8")
        self.assertIn("# Lecture ^txt-1", text)
        self.assertIn("### Timed [00:01:00](#t=60s) ^src-60", text)
        self.assertIn("### Untimed ^txt-2", text)
        self.assertEqual(next(self.root.glob("*-bak.md")).read_text(encoding="utf-8"), self.original)

    def test_missing_ids_error_and_omit_are_supported(self):
        self.cfg["summary"]["long"]["references"]["enabled"] = True
        status, _, errors, factory = self.invoke("--type", "long", "--missing-ids", "error")
        self.assertEqual(status, 2)
        self.assertIn("missing_source_ids", errors)
        factory.assert_not_called()
        status, _, errors, _ = self.invoke("--type", "long", "--missing-ids", "omit")
        self.assertEqual(status, 0, errors)
        self.assertIn("references_omitted", errors)
        self.assertNotIn("^src-60", self.source.read_text(encoding="utf-8"))
        self.assertNotIn("Source traceability", self.adapter.calls[-1][0][0]["content"])

    def test_missing_ids_omit_works_without_headings(self):
        self.source.write_text("Plain source paragraph.\n", encoding="utf-8")
        self.cfg["summary"]["long"]["references"]["enabled"] = True
        status, _, errors, _ = self.invoke("--type", "long", "--missing-ids", "omit")
        self.assertEqual(status, 0, errors)

    def test_invalid_references_fail_without_source_ids_or_backups(self):
        self.cfg["summary"]["long"]["references"]["enabled"] = True
        self.adapter.invalid_reference = True
        status, _, errors, _ = self.invoke("--type", "long")
        self.assertEqual(status, 1, errors)
        self.assertEqual(self.source.read_text(encoding="utf-8"), self.original)
        self.assertEqual(list(self.root.glob("*-bak.md")), [])

    def test_late_generation_failure_does_not_publish_earlier_success(self):
        self.append_existing(identifier="one")
        self.append_existing(identifier="two")
        before = self.source.read_bytes()
        self.adapter.fail_at = 2
        status, _, errors, _ = self.invoke("--type", "long", "--on-existing", "replace", "--target", "all")
        self.assertEqual(status, 1, errors)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(list(self.root.glob("*-bak.md")), [])

    def test_concurrent_source_edit_is_preserved(self):
        self.adapter.mutate = lambda: self.source.write_text("User's updated source", encoding="utf-8")
        status, _, errors, _ = self.invoke()
        self.assertEqual(status, 2)
        self.assertIn("file_changed", errors)
        self.assertEqual(self.source.read_text(encoding="utf-8"), "User's updated source")
        self.assertEqual(list(self.root.glob("*-bak.md")), [])

    def test_backup_can_be_disabled_and_template_can_be_changed(self):
        self.cfg["summary_regeneration"]["backups"] = {"enabled": False, "filename": "copy-{name}"}
        status, _, errors, _ = self.invoke("--type", "short")
        self.assertEqual(status, 0, errors)
        self.assertFalse((self.root / "copy-My lecture.md").exists())
        status, _, errors, _ = self.invoke("--type", "short", "--on-existing", "replace", "--backup")
        self.assertEqual(status, 0, errors)
        self.assertTrue((self.root / "copy-My lecture.md").exists())
        status, _, errors, factory = self.invoke("--type", "short", "--on-existing", "replace", "--backup")
        self.assertEqual(status, 2)
        self.assertIn("backup_exists", errors)
        factory.assert_not_called()

    def test_diff_calls_model_but_writes_nothing(self):
        before = self.source.read_bytes()
        status, output, errors, _ = self.invoke("--diff")
        self.assertEqual(status, 0, errors)
        self.assertIn("@@", output)
        self.assertIn("LECTURE_CLEANUP_SHORT_SUMMARY_START", output)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(list(self.root.glob("*-bak.md")), [])

    def test_malformed_markers_and_duplicate_ids_are_errors(self):
        for text in (
            self.original + LONG_SUMMARY_START + "\nUnclosed\n",
            self.original + LONG_SUMMARY_END + "\n",
            "### First ^src-60\n### Second ^src-60\n",
        ):
            with self.subTest(text=text):
                self.source.write_text(text, encoding="utf-8")
                self.cfg["summary"]["long"]["references"]["enabled"] = True
                status, _, _, factory = self.invoke()
                self.assertEqual(status, 2)
                factory.assert_not_called()

    def test_maximum_source_never_silently_truncates(self):
        self.cfg["summary_regeneration"]["max_source_chars"] = 10
        status, _, errors, factory = self.invoke()
        self.assertEqual(status, 2)
        self.assertIn("source_too_large", errors)
        factory.assert_not_called()

    def test_source_permissions_bom_and_crlf_survive(self):
        original = "\ufeff" + self.original.replace("\n", "\r\n")
        self.source.write_bytes(original.encode("utf-8"))
        self.source.chmod(0o640)
        status, _, errors, _ = self.invoke()
        self.assertEqual(status, 0, errors)
        after = self.source.read_bytes()
        self.assertTrue(after.startswith(original.encode("utf-8")))
        self.assertNotIn(b"\n", after.replace(b"\r\n", b""))
        self.assertEqual(self.source.stat().st_mode & 0o777, 0o640)
        self.assertEqual(next(self.root.glob("*-bak.md")).read_bytes(), original.encode("utf-8"))

    def test_startme_dry_run_preserves_caller_paths_without_api(self):
        local = self.root / "settings.yaml"
        local.write_text(yaml.safe_dump({"summary": {"short": {"enabled": True, "lang": "en"}, "long": {"enabled": False}}, "llm": {"provider": "invalid-provider"}}), encoding="utf-8")
        result = subprocess.run(
            [str(PROJECT / "StartMe.sh"), "add-summary", self.source.name, "--config", str(local), "--dry-run"],
            cwd=self.root, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(self.source), result.stdout)
        self.assertIn("action=append", result.stdout)
        self.assertIn("llm_requests=0", result.stdout)
        self.assertEqual(self.source.read_text(encoding="utf-8"), self.original)

    def test_write_failure_rolls_back_even_without_backups(self):
        external = self.root / "external.md"
        external.write_bytes(b"Original external\n")
        originals = {self.source: self.source.read_bytes(), external: external.read_bytes()}
        updates = {self.source: "New source\n", external: "New external\n"}
        real_replace = os.replace
        count = 0
        def failing_replace(source, destination):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("simulated filesystem failure")
            return real_replace(source, destination)
        with patch("scripts.summary_storage.os.replace", side_effect=failing_replace):
            with self.assertRaises(OSError):
                publish(updates, originals, {})
        for path, before in originals.items():
            self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.root.glob(".*.tmp")), [])

    def test_failed_generation_never_saves_planned_ids_for_external_output(self):
        self.cfg["summary"]["long"]["references"]["enabled"] = True
        self.adapter.fail_at = 1
        status, _, errors, _ = self.invoke("--type", "long", "--output", "separate")
        self.assertEqual(status, 1, errors)
        self.assertEqual(self.source.read_text(encoding="utf-8"), self.original)
        self.assertFalse((self.root / "My lecture-longsummary.md").exists())
        self.assertEqual(list(self.root.glob("*-bak.md")), [])

    def test_list_does_not_require_language_or_call_model(self):
        self.append_existing(identifier="inspect")
        self.cfg["summary"]["short"]["lang"] = "default"
        self.cfg["summary"]["long"]["lang"] = "default"
        status, output, errors, factory = self.invoke("--list")
        self.assertEqual(status, 0, errors)
        self.assertIn("inspect", output)
        factory.assert_not_called()

    def test_old_marked_unknown_language_is_skipped_or_explicitly_replaced(self):
        old = _summary_block("long", "Unknown language summary", "## Summary")
        self.source.write_text(self.original + "\n" + old + "\n", encoding="utf-8")
        status, _, errors, factory = self.invoke("--type", "long", "--lang", "en")
        self.assertEqual(status, 0, errors)
        self.assertIn("unknown_existing_language", errors)
        factory.assert_not_called()
        status, _, errors, _ = self.invoke("--type", "long", "--lang", "en", "--on-existing", "replace")
        self.assertEqual(status, 0, errors)
        self.assertEqual(self.blocks()[0].language, "en")

    def test_fenced_summary_marker_example_does_not_hide_real_source(self):
        text = self.original + "```md\n" + LONG_SUMMARY_START + "\n```\n### Real source\nVisible facts\n"
        self.source.write_text(text, encoding="utf-8")
        status, output, errors, _ = self.invoke("--print-source")
        self.assertEqual(status, 0, errors)
        self.assertIn("Visible facts", output)

    def test_existing_foreign_external_file_is_not_overwritten(self):
        external = self.root / "My lecture-summary.md"
        external.write_text("Unrelated personal notes\n", encoding="utf-8")
        status, _, errors, factory = self.invoke("--type", "short", "--output", "separate")
        self.assertEqual(status, 2)
        self.assertIn("foreign_output", errors)
        factory.assert_not_called()
        self.assertEqual(external.read_text(encoding="utf-8"), "Unrelated personal notes\n")

    def test_external_replace_preserves_id_and_backs_up_file(self):
        status, _, errors, _ = self.invoke("--type", "short", "--output", "separate")
        self.assertEqual(status, 0, errors)
        external = self.root / "My lecture-summary.md"
        before = external.read_bytes()
        identifier = self.blocks(external)[0].identifier
        status, _, errors, _ = self.invoke("--type", "short", "--output", "separate", "--on-existing", "replace")
        self.assertEqual(status, 0, errors)
        self.assertEqual(self.blocks(external)[0].identifier, identifier)
        self.assertEqual(next(self.root.glob("*-bak.md")).read_bytes(), before)

    def test_external_edit_after_inventory_is_not_overwritten(self):
        status, _, errors, _ = self.invoke("--type", "short", "--output", "separate")
        self.assertEqual(status, 0, errors)
        external = self.root / "My lecture-summary.md"
        original_inventory = TOOL.external_inventory

        def edit_after_inventory(*args):
            result = original_inventory(*args)
            external.write_text("Concurrent user edit\n", encoding="utf-8")
            return result

        with patch.object(TOOL, "external_inventory", side_effect=edit_after_inventory):
            status, _, errors, factory = self.invoke("--type", "short", "--output", "separate", "--on-existing", "replace")
        self.assertEqual(status, 2, errors)
        self.assertIn("file_changed", errors)
        factory.assert_not_called()
        self.assertEqual(external.read_text(encoding="utf-8"), "Concurrent user edit\n")

    def test_cli_language_and_output_override_regeneration_config(self):
        self.cfg["summary_regeneration"]["short"] = {"lang": "de", "output": "separate"}
        status, _, errors, _ = self.invoke(
            "--type", "short", "--short-summary-lang", "en", "--output", "append"
        )
        self.assertEqual(status, 0, errors)
        self.assertEqual(self.blocks()[0].language, "en")
        self.assertFalse((self.root / "My lecture-summary.md").exists())

    def test_type_specific_language_flags_work_for_both_regenerated_summaries(self):
        status, _, errors, _ = self.invoke(
            "--type", "both",
            "--short-summary-lang", "en",
            "--long-summary-lang", "de",
        )

        self.assertEqual(status, 0, errors)
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertEqual(
            {(block.kind, block.language) for block in self.blocks()},
            {("short", "en"), ("long", "de")},
        )
        system = self.adapter.calls[0][0][0]["content"]
        long_prompt, short_prompt = system.split("[SHORT SUMMARY SYSTEM INSTRUCTIONS]")
        self.assertIn("code `de`", long_prompt)
        self.assertIn("`en`", short_prompt)

    def test_type_specific_language_rejects_disabled_regenerated_summary(self):
        for kind in ("short", "long"):
            self.cfg["summary_regeneration"][kind] = {"enabled": False}
            status, _, errors, factory = self.invoke(
                f"--{kind}-summary-lang", "en"
            )
            self.assertEqual(status, 2)
            self.assertIn(f"--{kind}-summary-lang was provided", errors)
            self.assertIn(f"summary_regeneration.{kind}.enabled", errors)
            self.assertIn(f"--type {kind}|both", errors)
            factory.assert_not_called()
            self.cfg["summary_regeneration"].pop(kind)

    def test_removed_short_language_option_is_rejected(self):
        errors = io.StringIO()
        with redirect_stderr(errors), self.assertRaises(SystemExit) as raised:
            TOOL.parser().parse_args([str(self.source), "--short-lang", "en"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("unrecognized arguments: --short-lang en", errors.getvalue())

    def test_comment_line_mapping_retains_correct_ids(self):
        text = '<!-- rephrased: first\nsecond -->\n' + self.original + '<!-- END: final -->'
        self.source.write_text(text, encoding="utf-8")
        self.cfg["summary"]["long"]["references"]["enabled"] = True
        status, _, errors, _ = self.invoke("--type", "long")
        self.assertEqual(status, 0, errors)
        result = self.source.read_text(encoding="utf-8")
        self.assertIn('<!-- rephrased: first\nsecond -->', result)
        self.assertIn("# Lecture ^txt-1", result)
        self.assertIn("### Timed [00:01:00](#t=60s) ^src-60", result)


if __name__ == "__main__":
    unittest.main()

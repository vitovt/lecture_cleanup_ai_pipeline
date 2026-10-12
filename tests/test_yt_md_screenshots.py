"""Network-free regression tests, with real ffmpeg coverage when installed."""
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'subtitle-utils/yt-md-screenshots'
loader = importlib.machinery.SourceFileLoader('yt_md_screenshots', str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)
VIDEO = '1ASzWklab2U'
OTHER = 'abcdefghijk'


def link(t=1, video=VIDEO):
    return f'[🎥 {t}](https://youtu.be/{video}?t={t})\n'


def image(t=1, video=VIDEO):
    return f'![](_resources/img-{video}-{t}.png)\n'


class ParsingTests(unittest.TestCase):
    def test_url_forms(self):
        for base in (f'https://youtu.be/{VIDEO}?', f'https://youtube.com/watch?v={VIDEO}&',
                     *(f'https://youtube.com/{kind}/{VIDEO}?' for kind in ('shorts', 'live', 'embed'))):
            for stamp in ('t=999', 't=999s', 't=16m39s', 'start=999', 't=16:39'):
                with self.subTest(url=base+stamp):
                    self.assertEqual(m.youtube_target(base+stamp), (VIDEO, 999))
        self.assertEqual(m.youtube_target(f'https://youtu.be/{VIDEO}#t=1h'), (VIDEO, 3600))
        self.assertIsNone(m.youtube_target(f'https://youtu.be/{VIDEO}'))
        self.assertIsNone(m.youtube_target('https://example.com/video?t=1'))

    def test_invalid_urls_and_times(self):
        for url in ('https://[broken?t=1', 'https://youtu.be/wrong?t=1',
                    f'https://youtu.be/{VIDEO}?t=', f'https://youtu.be/{VIDEO}?t=1m1m'):
            with self.subTest(url=url), self.assertRaises(m.Problem):
                m.youtube_target(url)
        for value in ('1:99', '-1', 'NaN', '1m1m', ''):
            self.assertIsNone(m.seconds_of(value))

    def test_excludes_code_comments_and_nonstandalone_links(self):
        source = ('```md\n'+link()+'```\n~~~\n'+link()+'~~~\n    '+link()+
                  '<!--\n'+link()+'-->\n- ```md\n'+link()+'  ```\n'+
                  '> ```\n'+link()+'> ```\ninline '+link()+link(2))
        entries = m.collect(source.splitlines(True), self.fail)
        self.assertEqual([e['target'][1] for e in entries], [2])

    def test_alt_angle_title_and_percent_encoded_image(self):
        for text in (image(), image().replace('![]', '![Some alt]'),
                     '![](<_resources/img-1ASzWklab2U-1.png>)',
                     '![](_resources/img-1ASzWklab2U-1.png "title")',
                     '![](%5Fresources/img-1ASzWklab2U-1.png)'):
            self.assertEqual(m.image_filename(text), f'img-{VIDEO}-1.png')
        self.assertIsNone(m.image_filename('![](_resources/photo.png)'))

    def test_reference_images_are_recognized(self):
        source = (link()+'\n![Slide][frame]\n\n'
                  f'[frame]: <_resources/img-{VIDEO}-1.png> "Title"\n')
        entries = m.collect(source.splitlines(True), self.fail)
        self.assertEqual(entries[0]['images'], [(2, f'img-{VIDEO}-1.png')])
        result, _, inserted, _ = m.render(source.splitlines(True), entries,
            {(VIDEO, 1): f'img-{VIDEO}-1.png'}, m.parser().parse_args(['note.md']))
        self.assertEqual(result, source)
        self.assertEqual(inserted, 0)

    def test_render_modes_and_first_occurrence(self):
        source = link()+'\nOther section\n'+link()+image()
        lines = source.splitlines(True)
        entries = m.collect(lines, self.fail)
        args = m.parser().parse_args(['note.md'])
        outcomes = {(VIDEO, 1): f'img-{VIDEO}-1.png'}
        result, removed, _, _ = m.render(lines, entries, outcomes, args)
        self.assertEqual(result.count('!['), 2)
        self.assertFalse(removed)
        args.deduplicate = True
        result, removed, _, _ = m.render(lines, entries, outcomes, args)
        self.assertEqual(result.count('!['), 1)
        self.assertTrue(result.startswith(link()+'!['))
        self.assertFalse(removed)  # same PNG still used at the first occurrence

    def test_removed_file_still_referenced_elsewhere_not_reported(self):
        old = f'img-{OTHER}-1.png'
        source = link()+image(video=OTHER)+f'Elsewhere: ![old](<_resources/{old}>)\n'
        args = m.parser().parse_args(['note.md'])
        result, removed, _, _ = m.render(source.splitlines(True),
            m.collect(source.splitlines(True), self.fail), {(VIDEO, 1): f'img-{VIDEO}-1.png'}, args)
        self.assertIn(old, result)
        self.assertFalse(removed)

    def test_local_names_hash_and_utf8_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder)/'Лекція ? *.mp4'
            video.write_bytes(b'video contents')
            stem, digest = m.local_identity(video)
            self.assertEqual(stem, 'Лекція')
            self.assertEqual(digest, hashlib.sha256(b'video contents').hexdigest()[:4])
            name = m.frame_name(VIDEO, 999, -0.000001, ('🙂'*64, digest))
            self.assertLessEqual(len(name.encode()), 255)
            self.assertRegex(name, m.GENERATED)
            self.assertIn('offset-m0.000001', name)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='yt-md-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.md = self.root/'note.md'
        self.workspaces = []
        real_mkdtemp = tempfile.mkdtemp
        def mkdtemp(**kwargs):
            path = real_mkdtemp(prefix='run-', dir=self.root)
            self.workspaces.append(Path(path))
            return path
        self.addCleanup(patch.stopall)
        patch.object(m.tempfile, 'mkdtemp', side_effect=mkdtemp).start()
        patch.object(m.shutil, 'which', return_value='/fake/tool').start()
        self.metadata = patch.object(m, 'metadata', return_value=10.0).start()
        self.probe = patch.object(m, 'probe', return_value=10.0).start()
        self.png = patch.object(m, 'valid_png', side_effect=lambda p,*a: p.is_file() and p.read_bytes()==b'PNG').start()
        def download(video, work, args):
            folder = work/video
            folder.mkdir()
            path = folder/'video.mp4'
            path.write_bytes(b'VIDEO')
            return path, 10.0
        self.download = patch.object(m, 'download', side_effect=download).start()
        def frame(video, seconds, duration, dest, *args):
            dest.parent.mkdir(exist_ok=True)
            dest.write_bytes(b'PNG')
        self.frame = patch.object(m, 'create_frame', side_effect=frame).start()

    def run_cli(self, source=None, *flags):
        if source is not None:
            self.md.write_bytes(source.encode())
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = m.main([str(self.md), *map(str, flags)])
        return code, out.getvalue(), err.getvalue()

    def test_unknown_and_abbreviated_options_fail_before_processing(self):
        source = link()
        for flags in (('--between-timeco',), ('--off', '2'), ('--delete-orphan',),
                      ('--unexisting-option',), ('--offset=wrong',)):
            with self.subTest(flags=flags):
                code, out, err = self.run_cli(source, *flags)
                self.assertEqual(code, 2)
                self.assertTrue(err)
                self.assertEqual(out, '')
                self.assertEqual(self.md.read_text(), source)
                self.assertFalse((self.root/'_resources').exists())
                self.assertFalse(self.workspaces)
                self.metadata.assert_not_called()
                self.probe.assert_not_called()
                self.download.assert_not_called()
                self.frame.assert_not_called()

    def test_no_arguments_prints_introduction_without_processing(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = m.main([])
        self.assertEqual(code, 0)
        self.assertEqual(err.getvalue(), '')
        self.assertIn('Add video screenshots to a Markdown document', out.getvalue())
        self.assertIn('Example: subtitle-utils/yt-md-screenshots notes.md', out.getvalue())
        self.assertIn('--help for more information', out.getvalue())
        self.assertFalse(self.workspaces)
        self.metadata.assert_not_called()
        self.probe.assert_not_called()
        self.download.assert_not_called()
        self.frame.assert_not_called()

    def test_grouped_download_idempotency_and_cleanup(self):
        code, out, err = self.run_cli(link()+link()+link(2))
        self.assertEqual(code, 0, err)
        self.assertEqual(self.download.call_count, 1)
        self.assertEqual(self.frame.call_count, 2)
        self.assertEqual(self.md.read_text().count('!['), 2)
        self.assertTrue(all(not p.exists() for p in self.workspaces))
        original = self.md.read_bytes()
        code, out, err = self.run_cli()
        self.assertEqual(code, 0, err)
        self.assertIn('PNG already exists', out)
        self.assertEqual(self.md.read_bytes(), original)
        self.assertEqual(self.download.call_count, 1)

    def test_all_occurrences_and_deduplicate(self):
        self.run_cli(link()+link(), '--all-occurrences')
        self.assertEqual(self.md.read_text().count('!['), 2)
        self.run_cli(None, '--deduplicate')
        self.assertEqual(self.md.read_text().count('!['), 1)
        self.assertEqual(self.frame.call_count, 1)

    def test_between_migration_offset_cache_and_return_to_original(self):
        source = link(1)+link(4)+link(7)
        self.assertEqual(self.run_cli(source)[0], 0)
        code, out, err = self.run_cli(None, '--between-timecodes')
        self.assertEqual(code, 0, err)
        for t in (2, 5, 8):
            self.assertIn(f'img-{VIDEO}-{t}.png', self.md.read_text())
        for t in (1, 4, 7):
            self.assertTrue((self.root/f'_resources/img-{VIDEO}-{t}.png').exists())
            self.assertIn(f'img-{VIDEO}-{t}.png', out)
        code, _, err = self.run_cli(None, '--between-timecodes', '--offset', '1')
        self.assertEqual(code, 0, err)
        for t in (3, 6, 9):
            self.assertIn(f'img-{VIDEO}-{t}.png', self.md.read_text())
        self.assertNotIn('offset', self.md.read_text())
        snapshot = self.md.read_bytes()
        self.frame.reset_mock()
        self.download.reset_mock()
        self.metadata.reset_mock()
        code, out, err = self.run_cli(None, '--between-timecodes', '--offset', '1')
        self.assertEqual(code, 0, err)
        self.assertEqual(self.md.read_bytes(), snapshot)
        self.frame.assert_not_called()
        self.download.assert_not_called()
        self.metadata.assert_called_once()
        self.assertEqual(out.count('PNG already exists'), 3)
        self.assertEqual(self.run_cli()[0], 0)
        self.frame.assert_not_called()
        for t in (1, 4, 7):
            self.assertIn(f'img-{VIDEO}-{t}.png', self.md.read_text())

    def test_between_document_order_same_video_and_duplicates(self):
        source = link(1)+link(3, OTHER)+link(1)+link(4)+link(7, OTHER)+link(7)
        code, _, err = self.run_cli(source, '--between-timecodes', '--all-occurrences')
        self.assertEqual(code, 0, err)
        self.assertEqual(self.frame.call_count, 5)
        self.assertEqual(self.download.call_count, 2)
        self.assertEqual(self.md.read_text().count(f'img-{VIDEO}-2.png'), 2)
        for video, times in ((VIDEO, (2, 5, 8)), (OTHER, (5, 8))):
            for t in times:
                self.assertIn(f'img-{video}-{t}.png', self.md.read_text())

    def test_between_rounding_offset_and_boundary_frame_sharing(self):
        self.assertEqual(m.between_time(1, 4, 10, 0)[0], 2)
        self.assertEqual(m.between_time(1, 4, 10, .75)[0], 3)
        self.assertEqual(m.between_time(7, None, 10.9, 0)[0], 8)
        self.assertEqual(m.between_time(7, None, 10, -20)[0], 0)
        self.assertEqual(m.between_time(7, None, 10, 20)[0], 10)
        code, out, err = self.run_cli(link(1)+link(4)+link(7), '--between-timecodes', '--offset', '-20')
        self.assertEqual(code, 0, err)
        self.assertEqual(self.frame.call_count, 1)
        self.assertEqual(self.md.read_text().count(f'img-{VIDEO}-0.png'), 3)
        self.assertIn('offset clamped', out)

    def test_between_backward_and_invalid_next_keep_existing_images(self):
        source = link(7)+image(7)+link(1)+link(4)
        code, _, err = self.run_cli(source, '--between-timecodes')
        self.assertEqual(code, 1)
        self.assertIn('earlier than current', err)
        self.assertIn(link(7)+image(7), self.md.read_text())
        self.frame.reset_mock()
        code, _, err = self.run_cli(link(1)+link(20)+link(4), '--between-timecodes', '--force')
        self.assertEqual(code, 1)
        self.assertIn('next timestamp 20s exceeds', err)
        self.assertEqual(self.frame.call_count, 1)
        code, _, err = self.run_cli(source, '--between-timecodes', '--fail-fast')
        self.assertEqual(code, 1)
        self.assertEqual(self.md.read_text(), source)

    def test_between_edit_next_timecode_and_local_naming(self):
        self.run_cli(link(1)+link(4)+link(7), '--between-timecodes')
        self.md.write_text(self.md.read_text().replace('?t=4)', '?t=5)'))
        self.frame.reset_mock()
        code, _, err = self.run_cli(None, '--between-timecodes')
        self.assertEqual(code, 0, err)
        self.assertEqual([call.args[1] for call in self.frame.call_args_list], [3, 6])
        local = self.root/'Lecture.mp4'
        local.write_bytes(b'VIDEO')
        code, _, err = self.run_cli(link(1), '--between-timecodes', '--offset', '1', '--local-video', local)
        self.assertEqual(code, 0, err)
        self.assertIn(f'img-local-Lecture-{hashlib.sha256(b"VIDEO").hexdigest()[:4]}-6.png', self.md.read_text())
        self.assertEqual(local.read_bytes(), b'VIDEO')

    def test_delete_orphans_after_migration_reports_deleted_and_preserves_unrelated(self):
        self.run_cli(link(1)+link(4)+link(7))
        resources = self.root/'_resources'
        unrelated = resources/f'img-{OTHER}-9.png'
        unrelated.write_bytes(b'PNG')
        code, out, err = self.run_cli(None, '--between-timecodes', '--delete-orphans')
        self.assertEqual(code, 0, err)
        commands = [line for line in out.splitlines() if line.startswith('rm --')]
        self.assertEqual(len(commands), 3)
        for command in commands:
            self.assertIn('# DELETED:', command)
            self.assertFalse(Path(shlex.split(command, comments=True)[2]).exists())
        self.assertTrue(unrelated.exists())
        for t in (2, 5, 8):
            self.assertTrue((resources/f'img-{VIDEO}-{t}.png').exists())

    def test_delete_orphans_preserves_other_references_and_handles_missing_files(self):
        resources = self.root/'_resources'
        resources.mkdir()
        old = resources/f'img-{OTHER}-1.png'
        old.write_bytes(b'PNG')
        code, out, err = self.run_cli(link()+image(video=OTHER)+f'Other use: ![](<_resources/{old.name}>)\n', '--delete-orphans')
        self.assertEqual(code, 0, err)
        self.assertTrue(old.exists())
        self.assertNotIn('rm --', out)
        code, out, err = self.run_cli(link()+image(2, OTHER), '--delete-orphans')
        self.assertEqual(code, 0, err)
        self.assertIn('# ALREADY ABSENT:', out)

    def test_between_dry_run_delete_orphans_makes_no_changes(self):
        self.run_cli(link(1)+link(4)+link(7))
        original = self.md.read_bytes()
        files = sorted(p.name for p in (self.root/'_resources').iterdir())
        self.frame.reset_mock()
        self.download.reset_mock()
        code, out, err = self.run_cli(None, '--between-timecodes', '--offset', '1', '--delete-orphans', '--dry-run')
        self.assertEqual(code, 0, err)
        self.assertEqual(self.md.read_bytes(), original)
        self.assertEqual(sorted(p.name for p in (self.root/'_resources').iterdir()), files)
        self.assertIn('midpoint 2.5s; offset 1s; frame time 3s', out)
        self.assertIn('Would delete orphan PNG:', out)
        self.assertNotIn('# DELETED:', out)
        self.frame.assert_not_called()
        self.download.assert_not_called()

    def test_delete_orphans_never_runs_on_conflict(self):
        self.run_cli(link())
        original = self.md.read_text()
        old = self.root/f'_resources/img-{VIDEO}-1.png'
        frame = self.frame.side_effect
        def edit(*args):
            frame(*args)
            self.md.write_text(original+'USER EDIT\n')
        self.frame.side_effect = edit
        code, out, err = self.run_cli(None, '--between-timecodes', '--delete-orphans')
        self.assertEqual(code, 1)
        self.assertTrue(old.exists())
        self.assertNotIn('rm --', out)

    def test_delete_orphans_never_deletes_a_local_input_even_with_png_name(self):
        resources = self.root/'_resources'
        resources.mkdir()
        local = resources/f'img-{OTHER}-1.png'
        local.write_bytes(b'VIDEO')
        code, out, err = self.run_cli(link()+image(video=OTHER), '--local-video', local,
                                      '--between-timecodes', '--delete-orphans')
        self.assertEqual(code, 0, err)
        self.assertEqual(local.read_bytes(), b'VIDEO')
        self.assertIn('# KEPT: local video input', out)

    def test_delete_failure_is_reported_after_markdown_write(self):
        self.run_cli(link())
        old = self.root/f'_resources/img-{VIDEO}-1.png'
        old.unlink()
        old.mkdir()  # unlink must fail; unrelated directory contents remain safe.
        code, out, err = self.run_cli(None, '--between-timecodes', '--delete-orphans', '--fail-fast')
        self.assertEqual(code, 1)
        self.assertTrue(old.is_dir())
        self.assertIn(f'img-{VIDEO}-5.png', self.md.read_text())
        self.assertIn('# NOT DELETED:', out)
        self.assertIn('Cannot delete orphan PNG', err)
        self.assertIn('Markdown was already written', out)

    def test_cache_preserved_on_request(self):
        code, out, err = self.run_cli(link(), '--preserve-cache')
        self.assertEqual(code, 0, err)
        self.assertTrue(self.workspaces[0].exists())
        self.assertIn(str(self.workspaces[0]/VIDEO/'video.mp4'), out)

    def test_bad_timestamp_keeps_video_and_skips_duplicate_failure(self):
        code, out, err = self.run_cli(link()+link(20)+link(20))
        self.assertEqual(code, 1)
        self.assertEqual(self.frame.call_count, 1)
        self.assertEqual(err.count('exceeds video duration'), 1)
        self.assertTrue(self.workspaces[0].exists())

    def test_offset_clamps_but_cannot_rescue_invalid_timestamp(self):
        self.run_cli(link(1)+link(10), '--offset', '-20')
        self.assertEqual(self.frame.call_count, 1)
        self.assertEqual(self.frame.call_args.args[1], 0)
        self.run_cli(link(1), '--offset', '20')
        self.assertEqual(self.frame.call_args.args[1], 10)

    def test_force_failure_keeps_old_file_and_reference(self):
        self.run_cli(link())
        original = self.md.read_bytes()
        self.frame.side_effect = m.Problem('broken frame')
        code, out, err = self.run_cli(None, '--force')
        self.assertEqual(code, 1)
        self.assertEqual(self.md.read_bytes(), original)
        self.assertEqual((self.root/f'_resources/img-{VIDEO}-1.png').read_bytes(), b'PNG')
        self.assertIn('NOT updated', err)
        self.assertTrue(self.workspaces[-1].exists())

    def test_force_success_recreates_and_corrupt_cache_regenerates(self):
        self.run_cli(link())
        self.run_cli(None, '--force')
        self.assertEqual(self.frame.call_count, 2)
        (self.root/f'_resources/img-{VIDEO}-1.png').write_bytes(b'broken')
        self.run_cli()
        self.assertEqual(self.frame.call_count, 3)

    def test_local_video_never_downloaded_or_deleted(self):
        local = self.root/'Local lecture.mp4'
        local.write_bytes(b'VIDEO')
        code, out, err = self.run_cli(link(), '--local-video', local)
        self.assertEqual(code, 0, err)
        self.download.assert_not_called()
        self.metadata.assert_not_called()
        self.assertEqual(local.read_bytes(), b'VIDEO')
        self.assertIn('img-local-Local_lecture-', self.md.read_text())
        code, out, err = self.run_cli(None, '--local-video', local, '--force')
        self.assertEqual(code, 0, err)
        self.assertEqual(local.read_bytes(), b'VIDEO')

    def test_local_mapping_and_ambiguous_short_form(self):
        local = self.root/'video.mp4'
        local.touch()
        code, _, _ = self.run_cli(link()+link(video=OTHER), '--local-video', local)
        self.assertEqual(code, 1)
        code, _, err = self.run_cli(None, '--local-video', f'{VIDEO}={local}')
        self.assertEqual(code, 0, err)
        self.assertEqual(self.download.call_count, 1)

    def test_fail_fast_does_not_write_partial_markdown(self):
        source = link()+link(20)
        code, _, err = self.run_cli(source, '--fail-fast')
        self.assertEqual(code, 1)
        self.assertEqual(self.md.read_text(), source)
        self.frame.assert_not_called()

    def test_malformed_url_continues_or_stops(self):
        source = '[🎥](https://[broken?t=1)\n'+link()
        code, _, err = self.run_cli(source)
        self.assertEqual(code, 1)
        self.assertIn('line 1: Malformed URL', err)
        self.assertIn('![', self.md.read_text())
        self.frame.reset_mock()
        code, _, _ = self.run_cli(source, '--fail-fast')
        self.assertEqual(code, 1)
        self.frame.assert_not_called()
        self.assertEqual(self.md.read_text(), source)

    def test_conflict_file_and_no_removal_commands(self):
        old = image(video=OTHER)
        source = link()+old
        frame = self.frame.side_effect
        def edit(*args):
            frame(*args)
            self.md.write_text(source+'USER EDIT\n')
        self.frame.side_effect = edit
        code, out, err = self.run_cli(source)
        self.assertEqual(code, 1)
        self.assertEqual(self.md.read_text(), source+'USER EDIT\n')
        conflicts = list(self.root.glob('note-conflict-*.md'))
        self.assertEqual(len(conflicts), 1)
        self.assertNotIn(f'img-{OTHER}', conflicts[0].read_text())
        self.assertNotIn('rm --', out)
        self.assertTrue(self.workspaces[0].exists())

    def test_deleted_markdown_is_saved_as_conflict(self):
        frame = self.frame.side_effect
        def delete(*args):
            frame(*args)
            self.md.unlink()
        self.frame.side_effect = delete
        code, out, err = self.run_cli(link())
        self.assertEqual(code, 1)
        self.assertFalse(self.md.exists())
        conflicts = list(self.root.glob('note-conflict-*.md'))
        self.assertEqual(len(conflicts), 1)
        self.assertIn('![', conflicts[0].read_text())

    def test_removed_report_is_shell_command_and_png_stays(self):
        resources = self.root/'_resources'
        resources.mkdir()
        old = resources/f'img-{OTHER}-1.png'
        old.write_bytes(b'PNG')
        code, out, err = self.run_cli(link()+image(video=OTHER))
        self.assertEqual(code, 0, err)
        command = next(line for line in out.splitlines() if line.startswith('rm --'))
        self.assertEqual(shlex.split(command, comments=True), ['rm', '--', str(old)])
        self.assertTrue(old.exists())

    def test_dry_run_no_mutations(self):
        source = link()+image(video=OTHER)
        code, out, err = self.run_cli(source, '--dry-run')
        self.assertEqual(code, 0, err)
        self.assertEqual(self.md.read_text(), source)
        self.assertFalse((self.root/'_resources').exists())
        self.assertFalse(self.workspaces)
        self.download.assert_not_called()
        self.frame.assert_not_called()
        self.metadata.assert_called_once()
        self.assertIn('Would remove', out)
        self.assertNotIn('rm --', out)

    def test_dry_run_checks_cached_remote_duration(self):
        self.run_cli(link())
        self.metadata.reset_mock()
        self.metadata.return_value = .5
        code, out, err = self.run_cli(None, '--dry-run')
        self.assertEqual(code, 1)
        self.metadata.assert_called_once()
        self.assertIn('exceeds video duration', err)

    def test_partial_download_is_not_accepted(self):
        download = self.download.side_effect
        self.download.side_effect = lambda *a: (download(*a)[0], 3)
        code, out, err = self.run_cli(link())
        self.assertEqual(code, 1)
        self.assertIn('duration differs', err)
        self.frame.assert_not_called()
        self.assertTrue(self.workspaces[0].exists())

    def test_symlink_requires_opt_in(self):
        target = self.root/'real.md'
        target.write_text(link())
        self.md.symlink_to(target)
        code, _, err = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn('--follow-symlinks', err)
        self.frame.assert_not_called()
        code, out, err = self.run_cli(None, '--follow-symlinks')
        self.assertEqual(code, 0, err)
        self.assertTrue(self.md.is_symlink())
        self.assertIn('![', target.read_text())

    def test_quiet_error_and_debug(self):
        self.metadata.side_effect = m.Problem('failed')
        for flags, stdout, stderr in [(('--log-level','quiet'),False,False),
                                      (('--log-level','error'),False,True),
                                      (('--debug',),True,True), (('--trace',),True,True)]:
            code, out, err = self.run_cli(link(), *flags)
            self.assertEqual(code, 1)
            self.assertEqual(bool(out), stdout)
            self.assertEqual(bool(err), stderr)
            if flags[0] in ('--debug','--trace'):
                self.assertIn('Traceback', err)
        code, out, err = self.run_cli(link(), '--log-level', 'quiet', '--invalid-option')
        self.assertEqual(code, 2)
        self.assertEqual(out+err, '')

    def test_crlf_bom_permissions_and_no_final_newline(self):
        self.md.write_bytes(('\ufeff'+link()).replace('\n','\r\n').encode())
        self.md.chmod(0o640)
        code, _, err = self.run_cli()
        self.assertEqual(code, 0, err)
        result = self.md.read_bytes()
        self.assertTrue(result.startswith(b'\xef\xbb\xbf'))
        self.assertNotIn(b'\n', result.replace(b'\r\n',b''))
        self.assertEqual(self.md.stat().st_mode & 0o777, 0o640)
        self.run_cli(link().rstrip())
        self.assertIn('\n![', self.md.read_text())


class CommandTests(unittest.TestCase):
    def test_metadata_extra_config_output_and_live_rejection(self):
        args = m.parser().parse_args(['note.md'])
        args.log = m.Log('quiet')
        data = {'id': VIDEO, 'duration': 10, 'formats': [{'height': 1080}]}
        with patch.object(m, 'run_command', return_value='extra config output\n'+json.dumps(data)):
            self.assertEqual(m.metadata(VIDEO, args), 10)
        data['is_live'] = True
        data['duration'] = None
        with patch.object(m, 'run_command', return_value=json.dumps(data)):
            with self.assertRaisesRegex(m.Problem, 'livestreams'):
                m.metadata(VIDEO, args)

    def test_retry_count_and_permanent_failure(self):
        with patch.object(m.time, 'sleep'), patch.object(m, 'probe') as operation:
            operation.side_effect = [m.Problem('HTTP 403', True), 10]
            self.assertEqual(m.retry(operation, 2, m.Log('quiet')), 10)
            self.assertEqual(operation.call_count, 2)
            operation.reset_mock()
            operation.side_effect = m.Problem('bad timestamp')
            with self.assertRaises(m.Problem):
                m.retry(operation, 2, m.Log('quiet'))
            self.assertEqual(operation.call_count, 1)

    def test_command_stderr_only_in_debug(self):
        for level in ('info', 'debug'):
            err = io.StringIO()
            with contextlib.redirect_stderr(err), self.assertRaises(m.Problem) as raised:
                m.run_command([sys.executable, '-c', 'import sys; print("private diagnostics 403",file=sys.stderr);sys.exit(1)'], 5, m.Log(level))
            self.assertNotIn('private diagnostics', str(raised.exception))
            self.assertTrue(raised.exception.retryable)
            self.assertEqual('private diagnostics' in err.getvalue(), level=='debug')

    def test_timeout(self):
        with self.assertRaisesRegex(m.Problem, 'timed out'):
            m.run_command([sys.executable,'-c','import time;time.sleep(5)'], .05, m.Log('quiet'))

    def test_binary_stdout_is_saved_without_decoding_or_logging(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)/'video.part'
            result = m.run_command([sys.executable, '-c',
                'import sys;sys.stdout.buffer.write(bytes(range(256)))'], 5,
                m.Log('quiet'), output_path=destination)
            self.assertEqual(result, '')
            self.assertEqual(destination.read_bytes(), bytes(range(256)))

    def test_snap_streams_without_passing_host_tmp_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            args = m.parser().parse_args(['note.md'])
            args.log = m.Log('quiet')
            def command(cmd, *unused, output_path=None):
                self.assertEqual(cmd[cmd.index('-o')+1], '-')
                self.assertNotIn('--print-to-file', cmd)
                self.assertFalse(any(directory in arg for arg in cmd))
                output_path.write_bytes(b'VIDEO')
                return ''
            with patch.object(m, 'snap_downloader', return_value=True), \
                    patch.object(m, 'run_command', side_effect=command), \
                    patch.object(m, 'probe', return_value=10):
                path, duration = m.download(VIDEO, Path(directory), args)
            self.assertEqual(path.name, 'video.media')
            self.assertEqual(path.read_bytes(), b'VIDEO')
            self.assertEqual(duration, 10)
            self.assertFalse(path.with_suffix('.media.part').exists())

    def test_download_uses_receipt_and_keeps_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            args = m.parser().parse_args(['note.md', '--debug'])
            args.log = m.Log('quiet')
            work = Path(directory)
            def command(cmd, *unused):
                receipt = Path(cmd[cmd.index('--print-to-file')+2])
                video = receipt.parent/'video.webm'
                video.write_bytes(b'video')
                receipt.write_text(json.dumps(str(video))+'\n')
                self.assertNotIn('--ignore-config', cmd)
                self.assertNotIn('--download-sections', cmd)
                self.assertIn('bv*[height<=1080]', cmd)
                return ''
            with patch.object(m, 'snap_downloader', return_value=False), \
                    patch.object(m, 'run_command', side_effect=command), \
                    patch.object(m, 'probe', return_value=10):
                path, duration = m.download(VIDEO, work, args)
            self.assertEqual(path.name, 'video.webm')
            self.assertEqual(duration, 10)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg/ffprobe required')
class RealVideoTests(unittest.TestCase):
    def test_real_between_capture_migration_and_orphan_deletion(self):
        with tempfile.TemporaryDirectory(prefix='yt-md-between-') as directory:
            root = Path(directory)
            video = root/'Lecture.mkv'
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                            'testsrc2=size=64x48:rate=2:duration=6', '-c:v', 'ffv1', str(video)], check=True)
            original_video = video.read_bytes()
            md = root/'lecture.md'
            md.write_text(link(1)+link(4))
            command = [sys.executable, str(SCRIPT), str(md), '--local-video', str(video)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            original_pngs = list((root/'_resources').glob('*.png'))
            result = subprocess.run(command+['--between-timecodes', '--delete-orphans'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(all(not p.exists() for p in original_pngs))
            self.assertEqual(result.stdout.count('# DELETED:'), 2)
            pngs = list((root/'_resources').glob('*.png'))
            self.assertEqual(len(pngs), 2)
            self.assertEqual({p.name.rsplit('-', 1)[1] for p in pngs}, {'2.png', '5.png'})
            self.assertTrue(all(m.valid_png(p, 10, m.Log('quiet')) for p in pngs))
            expected = root/'expected.png'
            m.create_frame(video, 2, 6, expected, root, 10, m.Log('quiet'))
            captured = next(p for p in pngs if p.name.endswith('-2.png'))
            self.assertEqual(captured.read_bytes(), expected.read_bytes())
            md_snapshot = md.read_bytes()
            result = subprocess.run(command+['--between-timecodes', '--delete-orphans'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.count('PNG already exists'), 2)
            self.assertEqual(md.read_bytes(), md_snapshot)
            self.assertEqual(video.read_bytes(), original_video)

    def test_remote_cli_downloads_once_and_cleans_video(self):
        with tempfile.TemporaryDirectory(prefix='yt-md-remote-') as directory:
            root = Path(directory)
            fixture = root/'fixture.mkv'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i',
                            'testsrc2=size=64x48:rate=5:duration=3','-c:v','ffv1',str(fixture)], check=True)
            executable = root/'yt-dlp'
            executable.write_text('#!'+sys.executable+'\n'+'''
import json, pathlib, shutil, sys
root = pathlib.Path(__file__).parent
args = sys.argv[1:]
with (root/'calls.txt').open('a') as out:
    out.write(('metadata' if '--simulate' in args else 'download')+'\\n')
if '--simulate' in args:
    print(json.dumps({'id':'1ASzWklab2U','duration':3,'formats':[{'height':48}]}))
else:
    output = args[args.index('-o')+1]
    if output == '-':
        sys.stdout.buffer.write((root/'fixture.mkv').read_bytes())
        sys.exit(0)
    destination = pathlib.Path(output.replace('%(ext)s','mkv'))
    shutil.copyfile(root/'fixture.mkv', destination)
    receipt = pathlib.Path(args[args.index('--print-to-file')+2])
    receipt.write_text(json.dumps(str(destination))+'\\n')
''')
            executable.chmod(0o755)
            md = root/'lecture.md'
            md.write_text(link()+link(2)+link())
            env = dict(os.environ, PATH=str(root)+os.pathsep+os.environ.get('PATH',''))
            result = subprocess.run([sys.executable,str(SCRIPT),str(md)], env=env,
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root/'calls.txt').read_text(), 'metadata\ndownload\n')
            self.assertEqual(md.read_text().count('!['), 2)
            for line in result.stdout.splitlines():
                if line.startswith('Run directory: '):
                    self.assertFalse(Path(line.removeprefix('Run directory: ')).exists())
            executable.rename(root/'snap')
            executable.symlink_to('snap')
            result = subprocess.run([sys.executable,str(SCRIPT),str(md),'--force'], env=env,
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Snap yt-dlp detected', result.stdout)
            self.assertEqual((root/'calls.txt').read_text(), 'metadata\ndownload\n'*2)
            self.assertEqual(md.read_text().count('!['), 2)
            for line in result.stdout.splitlines():
                if line.startswith('Run directory: '):
                    self.assertFalse(Path(line.removeprefix('Run directory: ')).exists())

    def test_real_cli_local_force_dry_run_and_replacement(self):
        with tempfile.TemporaryDirectory(prefix='yt-md-cli-') as directory:
            root = Path(directory)
            video = root/'Video one.mkv'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i',
                            'testsrc2=size=64x48:rate=5:duration=2','-c:v','ffv1',str(video)], check=True)
            original = video.read_bytes()
            md = root/'lecture.md'
            md.write_text(link()+link())
            def run(*flags):
                result = subprocess.run([sys.executable,str(SCRIPT),str(md),
                    '--local-video', str(video),*flags], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return result
            before = md.read_bytes()
            run('--dry-run')
            self.assertEqual(md.read_bytes(), before)
            self.assertFalse((root/'_resources').exists())
            result = run('--offset','20')
            self.assertIn('offset clamped', result.stdout)
            self.assertEqual(md.read_text().count('!['), 1)
            self.assertIn('offset-p20', md.read_text())
            run('--force','--offset','20')
            result = run('--offset','-20')
            self.assertIn('rm --', result.stdout)
            self.assertEqual(len(list((root/'_resources').glob('*.png'))), 2)
            self.assertEqual(video.read_bytes(), original)
            for line in result.stdout.splitlines():
                if line.startswith('Run directory: '):
                    self.assertFalse(Path(line.removeprefix('Run directory: ')).exists())

    def test_frames_last_boundary_and_local_preservation(self):
        with tempfile.TemporaryDirectory(prefix='yt-md-real-') as directory:
            root = Path(directory)
            video = root/'Local video.mkv'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i',
                            'testsrc2=size=64x48:rate=5:duration=2', '-c:v','ffv1',str(video)], check=True)
            original = video.read_bytes()
            duration = m.probe(video, 10, m.Log('quiet'))
            self.assertEqual(duration, 2)
            work = root/'work'
            work.mkdir()
            for seconds in (0, 1, duration):
                dest = root/'_resources'/f'frame-{seconds}.png'
                m.create_frame(video, seconds, duration, dest, work, 10, m.Log('quiet'))
                self.assertTrue(m.valid_png(dest, 10, m.Log('quiet')))
            self.assertNotEqual((root/'_resources/frame-0.png').read_bytes(),
                                (root/'_resources/frame-2.0.png').read_bytes())
            self.assertEqual(video.read_bytes(), original)
            broken = root/'broken.png'
            broken.write_bytes(b'\x89PNG\r\n\x1a\nbroken')
            self.assertFalse(m.valid_png(broken, 10, m.Log('quiet')))


if __name__ == '__main__':
    unittest.main()

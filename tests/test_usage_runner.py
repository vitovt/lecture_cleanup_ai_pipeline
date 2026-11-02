"""Workflow accounting across subprocesses, without API calls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class UsageRunnerTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_workflow_collects_children_preserves_status_and_removes_journal(self):
        code = '''import os, sys, subprocess
from accounting.usage import EVENT_FILE, report_usage, usage_session
from accounting.models import TokenUsage
from decimal import Decimal
with usage_session(emit=lambda line: print('DUPLICATE', line)):
    report_usage(TokenUsage(10, 2, 12, cost=Decimal('0.1'), currency='USD'), scope='stt', provider='example', model='speech', stage='transcription', emit=lambda line: None)
subprocess.run([sys.executable, '-c', "from accounting.usage import report_usage; from accounting.models import TokenUsage; from decimal import Decimal; report_usage(TokenUsage(20,3,23,cost=Decimal('0.2'),currency='USD'),scope='cleanup',provider='example',model='text',stage='cleanup',emit=lambda line:None)"], check=True)
print(os.environ[EVENT_FILE])
raise SystemExit(7)
'''
        # Child stdout remains a real stream; run the runner as the actual CLI.
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/usage_runner.py'), 'cleanup', sys.executable, '-c', code],
                                cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertNotIn('DUPLICATE', result.stdout)
        self.assertIn('scope=all provider=all model=all requests=2 input_tokens=30 output_tokens=5 total_tokens=35 cost=0.3 currency=USD', result.stdout)
        path = result.stdout.splitlines()[0]
        self.assertFalse(Path(path).exists())

    def test_stt_runner_preserves_json_stdout_and_quiet_suppresses_totals(self):
        code = "from accounting.usage import report_usage; from accounting.models import TokenUsage; report_usage(TokenUsage(total_tokens=1),scope='stt',provider='x',model='y',stage='transcription',emit=lambda line:None,visible=VISIBLE); print('{}')"
        for visible in (True, False):
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/usage_runner.py'), 'stt-api',
                                     sys.executable, '-c', code.replace('VISIBLE', str(visible))], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(json.loads(result.stdout), {})
            self.assertEqual('USAGE_TOTAL' in result.stderr, visible)

    def test_startme_owns_workflow_totals_without_changing_arguments(self):
        import shutil
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copy2(ROOT / 'StartMe.sh', root / 'StartMe.sh')
            shutil.copytree(ROOT / 'accounting', root / 'accounting', ignore=shutil.ignore_patterns('__pycache__'))
            (root / 'scripts').mkdir()
            shutil.copy2(ROOT / 'scripts/usage_runner.py', root / 'scripts/usage_runner.py')
            (root / '.venv/bin').mkdir(parents=True)
            (root / '.venv/bin/python').symlink_to(sys.executable)
            child = root / 'process_localaudiovideo_via_groq.sh'
            child.write_text(f'#!{sys.executable}\n' + '''import json, sys
from accounting.usage import report_usage
from accounting.models import TokenUsage
report_usage(TokenUsage(10,2,12),scope='cleanup',provider='test',model='x',stage='cleanup',emit=print)
print(json.dumps(sys.argv[1:]))
raise SystemExit(7)
''')
            child.chmod(0o755)
            result = subprocess.run([str(root / 'StartMe.sh'), 'local-groq', '--llm-profile', 'chosen', 'audio file.mp3'],
                                    cwd='/tmp', text=True, capture_output=True)
            self.assertEqual(result.returncode, 7, result.stderr)
            self.assertIn('["--llm-profile", "chosen", "audio file.mp3"]', result.stdout)
            self.assertEqual(result.stdout.count('USAGE_TOTAL'), 1)
            self.assertIn('requests=1 input_tokens=10 output_tokens=2 total_tokens=12', result.stdout)

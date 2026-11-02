"""Exercise setup recovery without installing packages or touching real venvs."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]


class SetupTests(unittest.TestCase):
    def test_setup_recovery_and_reuse(self):
        for script in ('init_once.sh', 'stt-api/setup_venv.sh'):
            with self.subTest(script=script), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                shutil.copy(PROJECT / script, root / 'setup.sh')
                for name in ('.env_default', 'config.yaml.example', 'requirements.txt'):
                    (root / name).write_text('template\n')
                (root / '.env').write_text('keep local settings\n')
                bindir = root / 'bin'
                bindir.mkdir()
                # Fake interpreter: first package installation fails; retry succeeds.
                interpreter = '''#!/bin/bash
printf '%s\\n' "$*" >> "$SETUP_LOG"
if [[ "$1" == -c ]]; then
    exit "${OLD_PYTHON:-0}"
fi
if [[ "$1 $2" == '-m venv' ]]; then
    mkdir -p "$3/bin"
    cp "$0" "$3/bin/python"
elif [[ "$*" == *'install -r'* && ! -f "$SETUP_MARKER" ]]; then
    touch "$SETUP_MARKER"
    exit 1
fi
'''
                (bindir / 'python3').write_text(interpreter)
                (bindir / 'python3').chmod(0o755)
                env = dict(os.environ, PATH=f'{bindir}:{os.environ["PATH"]}',
                           SETUP_LOG=str(root / 'log'), SETUP_MARKER=str(root / 'marker'))
                # Simulate interruption leaving an empty .venv directory.
                (root / '.venv').mkdir()
                def run():
                    return subprocess.run(['bash', str(root / 'setup.sh')], cwd='/tmp',
                                          env=env, capture_output=True, text=True)
                self.assertNotEqual(run().returncode, 0)
                self.assertEqual(run().returncode, 0)
                self.assertEqual(run().returncode, 0)
                calls = (root / 'log').read_text()
                self.assertEqual(calls.count('-m venv '), 1)
                self.assertEqual(calls.count('-m pip install -r '), 3)
                self.assertEqual((root / '.env').read_text(), 'keep local settings\n')
                self.assertEqual((root / 'config.yaml').read_text(), 'template\n')
                # Old system Python must fail before trying to create a venv.
                shutil.rmtree(root / '.venv')
                (root / 'log').write_text('')
                env['OLD_PYTHON'] = '1'
                result = run()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Python 3.10', result.stderr)
                self.assertNotIn('-m venv', (root / 'log').read_text())

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests import test_e2e

ROOT = Path(__file__).resolve().parents[1]


class PluginTests(unittest.TestCase):
    # BSC-SKILL-001
    def test_generated_bundle_matches_canonical_sources(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/build_plugin.py'), '--check'], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    # BSC-SKILL-010
    def test_manifest_follows_codex_plugin_spec(self):
        manifest = json.loads((ROOT / 'plugins/book-studio/.codex-plugin/plugin.json').read_text(encoding='utf-8'))
        self.assertEqual('book-studio', manifest['name'])
        self.assertTrue(manifest['skills'].startswith('./'))
        prompts = manifest['interface']['defaultPrompt']
        self.assertIsInstance(prompts, list)
        self.assertTrue(1 <= len(prompts) <= 3)
        self.assertTrue(all(isinstance(prompt, str) and 0 < len(prompt) <= 128 for prompt in prompts))
        self.assertTrue(manifest['keywords'])

    # BSC-SKILL-003
    def test_standalone_bundle_runs_complete_guided_flow(self):
        with tempfile.TemporaryDirectory(prefix='bookstudio plugin ') as directory:
            bundle = Path(directory) / 'book-studio'
            shutil.copytree(ROOT / 'plugins/book-studio', bundle)
            def run_cli(*args):
                env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
                env.pop('PYTHONPATH', None)
                return subprocess.run([sys.executable, '-I', str(bundle / 'scripts/bookstudio.py'), *args], cwd=directory, env=env, capture_output=True, text=True)
            self.assertEqual(0, run_cli('doctor', '--json').returncode)
            with patch('tests.test_e2e.run_cli', run_cli):
                test_e2e.SyntheticCliEndToEndTests('test_complete_guided_pilot_gated_cli_flow').test_complete_guided_pilot_gated_cli_flow()

    # BSC-SKILL-002
    def test_check_rejects_modified_bundle_without_repairing_it(self):
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / 'checkout'
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns('.git', '__pycache__'))
            runner = copy / 'plugins/book-studio/scripts/bookstudio.py'
            runner.write_text('raise SystemExit(9)\n')
            result = subprocess.run([sys.executable, str(copy / 'scripts/build_plugin.py'), '--check'], capture_output=True, text=True)
            self.assertEqual(1, result.returncode)
            self.assertEqual('raise SystemExit(9)\n', runner.read_text())

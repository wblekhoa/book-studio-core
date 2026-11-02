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
    # BSC-CHAT-006
    def test_portable_plugin_starts_its_local_tools_without_claude_placeholders(self):
        plugin = ROOT / 'plugins/book-studio'
        manifest = json.loads((plugin / 'plugin.json').read_text())
        self.assertEqual('book-studio', manifest['name'])
        self.assertTrue(manifest['extensions']['com.openai']['requires_local_executor'])
        server = json.loads((plugin / 'mcp.json').read_text())['mcpServers']['book-studio']
        self.assertEqual('stdio', server['type'])
        arguments = [value.replace('${PLUGIN_ROOT}', str(plugin)) for value in server['args']]
        request = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}) + '\n'
        run = subprocess.run([server['command'], *arguments], input=request, capture_output=True, text=True)
        self.assertEqual(0, run.returncode, run.stderr)
        tools = json.loads(run.stdout)['result']['tools']
        self.assertTrue({'start', 'view', 'review', 'pilot', 'finish'} <= {tool['name'] for tool in tools})

    # BSC-SKILL-001
    def test_generated_bundle_matches_canonical_sources(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/build_plugin.py'), '--check'], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    # BSC-SKILL-013
    def test_every_plugin_manifest_carries_the_package_version(self):
        import tomllib

        version = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
        plugin = ROOT / 'plugins/book-studio'
        for manifest in ('plugin.json', '.codex-plugin/plugin.json', '.claude-plugin/plugin.json'):
            self.assertEqual(version, json.loads((plugin / manifest).read_text())['version'], manifest)

    # BSC-SKILL-013
    def test_check_reports_and_build_repairs_manifest_version_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / 'checkout'
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns('.git', '__pycache__'))
            manifest = copy / 'plugins/book-studio/plugin.json'
            manifest.write_text(manifest.read_text().replace(json.loads(manifest.read_text())['version'], '0.0.1', 1))
            script = str(copy / 'scripts/build_plugin.py')
            check = subprocess.run([sys.executable, script, '--check'], capture_output=True, text=True)
            self.assertEqual(1, check.returncode)
            self.assertIn('plugin.json', check.stdout)
            self.assertEqual(0, subprocess.run([sys.executable, script], capture_output=True, text=True).returncode)
            self.assertEqual(0, subprocess.run([sys.executable, script, '--check'], capture_output=True, text=True).returncode)

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

    # BSC-SKILL-015
    def test_manifest_artwork_exists_as_png_under_assets(self):
        manifest = json.loads((ROOT / 'plugins/book-studio/.codex-plugin/plugin.json').read_text(encoding='utf-8'))
        interface = manifest['interface']
        paths = [interface['logo'], interface['composerIcon'], *interface['screenshots']]
        self.assertTrue(interface['screenshots'])
        self.assertRegex(interface['brandColor'], r'^#[0-9A-Fa-f]{6}$')
        for path in paths:
            with self.subTest(path=path):
                self.assertTrue(path.startswith('./assets/') and path.endswith('.png'))
                data = (ROOT / 'plugins/book-studio' / path[2:]).read_bytes()
                self.assertEqual(b'\x89PNG\r\n\x1a\n', data[:8])

    # BSC-SKILL-016
    def test_claude_plugin_wiring_targets_the_bundled_runner(self):
        plugin = ROOT / 'plugins/book-studio'
        manifest = json.loads((plugin / '.claude-plugin/plugin.json').read_text(encoding='utf-8'))
        self.assertEqual('book-studio', manifest['name'])
        self.assertEqual('directory', manifest['userConfig']['projects_dir']['type'])
        market = json.loads((ROOT / '.claude-plugin/marketplace.json').read_text(encoding='utf-8'))
        self.assertEqual([('book-studio', './plugins/book-studio')], [(p['name'], p['source']) for p in market['plugins']])
        runner = '"${CLAUDE_PLUGIN_ROOT}/scripts/bookstudio.py"'
        hooks = json.loads((plugin / 'hooks/hooks.json').read_text(encoding='utf-8'))['hooks']
        commands = [h['command'] for groups in hooks.values() for group in groups for h in group['hooks']]
        self.assertEqual({f'python3 {runner} hook guard', f'python3 {runner} hook session-start'}, set(commands))
        self.assertIn('Bash', hooks['PreToolUse'][0]['matcher'].split('|'))
        server = json.loads((plugin / '.mcp.json').read_text(encoding='utf-8'))['mcpServers']['book-studio']
        self.assertEqual(['${CLAUDE_PLUGIN_ROOT}/scripts/bookstudio.py', 'mcp'], server['args'])
        for folder, keys in (('agents', ('name:', 'description:', 'tools:')), ('commands', ('description:',))):
            files = sorted((plugin / folder).glob('*.md'))
            self.assertTrue(files)
            for path in files:
                with self.subTest(path=path.name):
                    head = path.read_text(encoding='utf-8').split('---')[1]
                    self.assertTrue(all(key in head for key in keys))
        self.assertNotIn('Bash', (plugin / 'agents/editorial-reviewer.md').read_text(encoding='utf-8').split('---')[1])

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


class CodexInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='book studio install ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.checkout = self.root / 'checkout'
        shutil.copytree(ROOT / 'plugins', self.checkout / 'plugins')
        (self.checkout / 'scripts').mkdir()
        script = ROOT / 'scripts/install_codex_plugin.py'
        if script.exists():
            shutil.copy2(script, self.checkout / 'scripts')
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        fake = self.bin / 'codex'
        fake.write_text(f'#!{sys.executable}\n' + '''import json, os, pathlib, shutil, sys
root = pathlib.Path(os.environ['INSTALL_TEST_ROOT'])
with (root / 'commands.jsonl').open('a') as stream:
    stream.write(json.dumps(sys.argv[1:])+'\\n')
if sys.argv[1:4] == ['plugin', 'marketplace', 'add']:
    print('{}')
elif sys.argv[1:3] == ['plugin', 'add']:
    target = root / 'installed plugin'
    shutil.copytree(pathlib.Path.cwd() / 'plugins/book-studio', target)
    if os.environ.get('INSTALL_TEST_CORRUPT'):
        (target / 'runtime/bookstudio/mcp_server.py').write_text('corrupt')
    print(json.dumps({'installedPath': str(target)}))
else:
    raise SystemExit(4)
''')
        fake.chmod(0o755)
        (self.bin / 'python3').symlink_to(sys.executable)

    def run_install(self, *args, corrupt=False, missing_codex=False, missing_python=False):
        env = dict(os.environ, PATH=str(self.bin), PYTHONDONTWRITEBYTECODE='1', INSTALL_TEST_ROOT=str(self.root))
        if corrupt:
            env['INSTALL_TEST_CORRUPT'] = '1'
        if missing_codex:
            env['PATH'] = str(self.root / 'missing')
        if missing_python:
            (self.bin / 'python3').unlink()
        run = subprocess.run([sys.executable, str(self.checkout / 'scripts/install_codex_plugin.py'), '--json', *args],
                             cwd=self.root, env=env, capture_output=True, text=True)
        self.assertTrue(run.stdout, run.stderr)
        return run.returncode, json.loads(run.stdout)

    # BSC-CHAT-009: dry-run must not register a marketplace or touch plugin state.
    def test_dry_run_preflights_without_calling_codex(self):
        code, result = self.run_install('--dry-run')
        self.assertEqual(0, code, result)
        self.assertEqual('ready', result['status'])
        self.assertFalse((self.root / 'commands.jsonl').exists())
        self.assertFalse((self.root / 'installed plugin').exists())

    def test_installs_from_any_directory_and_checks_the_actual_copied_runner(self):
        code, result = self.run_install()
        self.assertEqual(0, code, result)
        self.assertEqual('pass', result['status'])
        self.assertEqual(12, result['tools'])
        self.assertGreater(result['verified_files'], 80)
        calls = [json.loads(line) for line in (self.root / 'commands.jsonl').read_text().splitlines()]
        self.assertEqual([['plugin', 'marketplace', 'add', str(self.checkout.resolve()), '--json'],
                          ['plugin', 'add', 'book-studio@book-studio', '--json']], calls)
        self.assertFalse((self.checkout / 'plugins/book-studio/projects').exists())

    def test_corrupt_install_is_not_reported_as_success(self):
        code, result = self.run_install(corrupt=True)
        self.assertEqual(1, code)
        self.assertEqual('CODEX_INSTALL_MISMATCH', result['code'])
        self.assertIn('runtime/bookstudio/mcp_server.py', result['message'])
        self.assertIn('plugin_install', result['completed'])

    def test_missing_codex_explains_requirement_without_mutation(self):
        code, result = self.run_install(missing_codex=True)
        self.assertEqual(1, code)
        self.assertEqual('CODEX_NOT_FOUND', result['code'])
        self.assertFalse((self.root / 'commands.jsonl').exists())

    def test_missing_declared_python_does_not_pass_with_another_interpreter(self):
        code, result = self.run_install(missing_python=True)
        self.assertEqual(1, code)
        self.assertEqual('PLUGIN_COMMAND_NOT_FOUND', result['code'])
        self.assertFalse((self.root / 'commands.jsonl').exists())

    def test_non_object_codex_response_produces_a_failure_receipt(self):
        fake = self.bin / 'codex'
        fake.write_text(fake.read_text().replace("print(json.dumps({'installedPath': str(target)}))", "print('[]')"))
        code, result = self.run_install()
        self.assertEqual(1, code)
        self.assertEqual('CODEX_INSTALL_RESPONSE_INVALID', result['code'])

"""Install this checkout's bundled Codex plugin and verify its actual cached runner."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'plugins/book-studio'


class InstallError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


def run(command, *, data=None, env=None, cwd=ROOT):
    result = subprocess.run(command, cwd=cwd, input=data, capture_output=True, text=True, timeout=60, env=env)
    if result.returncode:
        raise InstallError('CODEX_INSTALL_COMMAND_FAILED', (result.stderr or result.stdout).strip() or 'Command failed.')
    return result.stdout


def object_json(text):
    value = json.loads(text)
    if not isinstance(value, dict):
        raise InstallError('CODEX_INSTALL_RESPONSE_INVALID', 'Expected a JSON object from a manifest or command; installation is not verified.')
    return value


def transport(plugin):
    server = object_json((plugin / 'mcp.json').read_text())['mcpServers']['book-studio']
    if not isinstance(server, dict) or not isinstance(server.get('command'), str):
        raise InstallError('PLUGIN_TRANSPORT_INVALID', 'The plugin has no valid local command.')
    command = shutil.which(server['command'])
    if not command:
        raise InstallError('PLUGIN_COMMAND_NOT_FOUND', 'Install Python 3.11+ and make ' + server['command'] + ' available in Terminal and Codex.')
    args = server['args']
    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        raise InstallError('PLUGIN_TRANSPORT_INVALID', 'The plugin has invalid command arguments.')
    return [command, *[arg.replace('${PLUGIN_ROOT}', str(plugin)) for arg in args]]


def install(dry_run=False):
    completed = []
    try:
        if sys.version_info < (3, 11):
            raise InstallError('PYTHON_TOO_OLD', 'Install Python 3.11 or newer, then retry.')
        if sys.platform == 'win32':
            raise InstallError('PLATFORM_UNSUPPORTED', 'This build supports macOS and Linux.')
        codex = shutil.which('codex')
        if not codex:
            raise InstallError('CODEX_NOT_FOUND', 'Install Codex with plugin support and make its codex command available in Terminal.')
        # Check generated runtime before allowing a stale checkout to register itself.
        bundle = object_json((PLUGIN / 'bundle.json').read_text())
        hashes = bundle['sha256']
        if not isinstance(hashes, dict):
            raise InstallError('PLUGIN_BUNDLE_INVALID', 'The bundle has no valid hash manifest.')
        for name, digest in hashes.items():
            file = PLUGIN / name
            if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != digest:
                raise InstallError('PLUGIN_BUNDLE_STALE', 'Bundle differs: ' + name + '. Obtain a complete release or regenerate it from canonical sources.')
        command = transport(PLUGIN)
        doctor = object_json(run([command[0], '-I', str(PLUGIN / 'scripts/bookstudio.py'), 'doctor', '--json']))
        if doctor.get('status') != 'pass':
            raise InstallError('PLUGIN_DOCTOR_FAILED', 'The bundled engine did not pass doctor.')
        completed.append('preflight')
        commands = [[codex, 'plugin', 'marketplace', 'add', str(ROOT), '--json'],
                    [codex, 'plugin', 'add', 'book-studio@book-studio', '--json']]
        if dry_run:
            return {'status': 'ready', 'completed': completed, 'commands': commands,
                    'message': 'Preflight passed. No Codex plugin settings were changed.'}
        run(commands[0])
        completed.append('marketplace_registration')
        added = object_json(run(commands[1]))
        completed.append('plugin_install')
        location = added.get('installedPath')
        if not isinstance(location, str) or not Path(location).is_absolute():
            raise InstallError('CODEX_INSTALL_PATH_UNKNOWN', 'Codex did not return an absolute installedPath; installation is not verified.')
        installed = Path(location)
        verified = 0
        for file in sorted(PLUGIN.rglob('*')):
            if not file.is_file() or '__pycache__' in file.parts or file.suffix == '.pyc':
                continue
            target = installed / file.relative_to(PLUGIN)
            if not target.is_file() or target.read_bytes() != file.read_bytes():
                raise InstallError('CODEX_INSTALL_MISMATCH', 'Cached plugin differs: ' + file.relative_to(PLUGIN).as_posix())
            verified += 1
        completed.append('cache_parity')
        # Exercise the installed copy, without importing the checkout or touching a book.
        request = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}) + '\n'
        env = dict(os.environ, PLUGIN_ROOT=str(installed), PYTHONDONTWRITEBYTECODE='1')
        env.pop('PYTHONPATH', None)
        payload = object_json(run(transport(installed), data=request, env=env, cwd=installed))
        if not isinstance(payload.get('result'), dict) or not isinstance(payload['result'].get('tools'), list) or not all(isinstance(tool, dict) for tool in payload['result']['tools']):
            raise InstallError('CODEX_INSTALL_RESPONSE_INVALID', 'The installed server returned an invalid tools result.')
        names = {tool['name'] for tool in payload['result']['tools']}
        if not {'start', 'view', 'review', 'pilot', 'next_packet', 'apply_response', 'finish', 'verify'} <= names:
            raise InstallError('CODEX_INSTALL_TOOLS_MISSING', 'The installed server is missing required book tools.')
        completed.append('installed_transport')
        return {'status': 'pass', 'completed': completed, 'installed_path': str(installed),
                'verified_files': verified, 'tools': len(names),
                'message': 'Book Studio installed and checked. Open a chat, select Book Studio, and attach your book. Keep book projects in your own folder outside the plugin.'}
    except (InstallError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        return {'status': 'error', 'code': getattr(error, 'code', 'CODEX_INSTALL_CHECK_FAILED'),
                'message': getattr(error, 'message', str(error)), 'completed': completed,
                'next_action': 'Resolve the reported requirement or Codex error and rerun this installer. Earlier completed steps may remain registered; private book files are untouched.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='Check prerequisites without registering or installing.')
    parser.add_argument('--json', action='store_true', help='Print the installation receipt as JSON.')
    args = parser.parse_args()
    result = install(args.dry_run)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(result['message'])
        if result['status'] == 'error':
            print(result['next_action'])
        elif result['status'] == 'pass':
            print(f"Verified {result['verified_files']} files and {result['tools']} local tools.")
    return int(result['status'] == 'error')


if __name__ == '__main__':
    raise SystemExit(main())

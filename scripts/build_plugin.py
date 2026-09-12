"""Materialize the portable plugin from canonical sources; --check never writes."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'plugins/book-studio'
RUNNER = '''"""Run the engine shipped with this plugin, without pip or a global CLI."""
import sys
from pathlib import Path
if sys.version_info < (3, 11):
    raise SystemExit("Book Studio requires Python 3.11 or newer.")
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from bookstudio.cli import main
if __name__ == "__main__":
    raise SystemExit(main())
'''
RUNTIME_GUIDANCE = '''
## Plugin runtime

This plugin includes its matching Python engine. Resolve this skill's location
to the plugin root (two parent directories above this skill folder). For every
`bookstudio ...` command in this skill and its references, execute
`python3 "<plugin-root>/scripts/bookstudio.py" ...` instead. Use an absolute,
quoted path and Python 3.11 or newer. Do not use a separately installed global
CLI or pip-install another engine. Run the bundled `doctor --json` first.
If Python is missing, explain the requirement and help the user install it.
Optional PDF tools are reported by doctor and are needed only for PDF input.
Keep all private project files outside the plugin installation directory.

'''


def expected_files():
    files = {'scripts/bookstudio.py': RUNNER.encode(), 'LICENSE': (ROOT / 'LICENSE').read_bytes()}
    for source, target in [('src/bookstudio', 'runtime/bookstudio'), ('skills/book-translation', 'skills/book-translation')]:
        for path in sorted((ROOT / source).rglob('*')):
            if path.is_symlink():
                raise ValueError('Symlink in canonical plugin input')
            if not path.is_file() or '__pycache__' in path.parts or path.suffix == '.pyc':
                continue
            relative = path.relative_to(ROOT / source).as_posix()
            data = path.read_bytes()
            if source.startswith('skills') and relative == 'SKILL.md':
                text = data.decode()
                end = text.index('\n---', 3) + 4
                data = (text[:end] + '\n' + RUNTIME_GUIDANCE + text[end:]).encode()
            files[target + '/' + relative] = data
    files['bundle.json'] = (json.dumps({'schema_version': 1, 'sha256': {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}}, indent=2) + '\n').encode()
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    files = expected_files()
    existing = {p.relative_to(DEST).as_posix() for p in DEST.rglob('*') if p.is_file()}
    extras = existing - files.keys() - {'.codex-plugin/plugin.json'}
    if extras:
        print('Unexpected bundle files; inspect manually: ' + ', '.join(sorted(extras)))
        return 1
    drift = [name for name, data in files.items() if not (DEST / name).is_file() or (DEST / name).read_bytes() != data]
    if args.check:
        print('Bundle matches canonical sources.' if not drift else 'Bundle drift: ' + ', '.join(drift))
        return int(bool(drift))
    for name in drift:
        target = DEST / name
        if target.is_symlink() or any(p.is_symlink() for p in target.parents):
            raise ValueError('Symlink in bundle destination')
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + '.tmp')
        with temporary.open('xb') as stream:
            stream.write(files[name])
        temporary.replace(target)
    print(f'Generated {len(files)} files from canonical sources.')
    return 0


if __name__ == '__main__':
    sys.exit(main())

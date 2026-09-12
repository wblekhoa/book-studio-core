# Book Studio Codex plugin

The plugin contains the canonical translation skill and its matching Python
engine. Only Python 3.11+ and Codex plugin support are required for EPUB work.
Run commands from Terminal, not from a Python prompt.

## Install from a checkout

```bash
git clone https://github.com/wblekhoa/book-studio-core.git
cd book-studio-core
python3 plugins/book-studio/scripts/bookstudio.py doctor --json
codex plugin marketplace add .
codex plugin add book-studio@book-studio
codex plugin list
```

Open a new thread, select the Book Studio plugin and provide your source file.
The AI asks about missing preferences, prepares a representative pilot and waits
for your review before full translation. Keep book projects outside the clone.
No separate CLI installation is necessary. The plugin uses its own runner even
when a different `bookstudio` executable is installed globally.

If the standalone `book-translation` skill is also installed, select the plugin
explicitly to avoid ambiguity. Installing this plugin does not remove it.

## Update and remove

Pull updates into a clean checkout, rerun doctor, and rerun the marketplace-add
and plugin-add commands above to refresh the local snapshot. Start a new thread.
Preserve private book projects separately. Remove only the installed plugin with:

```bash
codex plugin remove book-studio@book-studio
```

If Codex cannot load its own configuration before running a plugin command,
resolve that Codex version/configuration mismatch first. It is not a Book Studio
runtime error. Do not overwrite user configuration during installation.

## Maintainer contract

`src/bookstudio/` and `skills/book-translation/` own runtime and workflow changes.
`plugins/book-studio/` is a generated distribution, except its plugin manifest.
Regenerate after editing either source:

```bash
python3 scripts/build_plugin.py
python3 scripts/build_plugin.py --check
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m bookstudio public-audit . --json
```

The generator records file hashes in `bundle.json`. The check detects stale,
missing, or unexpected files without changing them. CI runs this check, and
tests execute the complete guided synthetic workflow from a standalone copy
with no source checkout or global CLI in its import path. Generated files are
committed so users do not need a build step. Do not hand-edit generated files.
The plugin manifest version is its distribution version, separate from the
legacy CLI version; update it for subsequent plugin releases.

PDF preparation is limited to supported text-layer documents and needs local
Poppler tools. OCR, rendering, and image generation are not bundled. All use
remains subject to the repository's current personal-use license. Structural
tests do not replace editorial review or visual inspection of a real book.

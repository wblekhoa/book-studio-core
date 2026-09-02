# Contributing

Book Studio Core favors small, reversible changes backed by an executable
receipt.

1. Keep all examples synthetic and provider-neutral.
2. Add a failing test before changing behavior.
3. Preserve stable error codes and source-aligned hashes.
4. Use only the Python standard library unless a dependency decision is
   explicitly approved.
5. Run the full unit suite and public-boundary audit.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m bookstudio public-audit . --json
```

Never add source books, translated passages, covers, project caches, model
credentials, account addresses, or personal filesystem paths. The package is
source-available under the Book Studio Personal Use License 1.0. Contributions
and forks must remain under that license; commercial licensing, release tags,
package-index publication, and hosted services remain separate maintainer
decisions.

# AGENTS.md - Book Studio Core

## Mission

Build a safe, deterministic, provider-neutral EPUB translation engine and CLI.

## Public Boundary

- This repository contains reusable code, documentation, and synthetic tests
  only.
- Never add commercial books, translated prose, source-derived block maps,
  covers, provider responses, personal paths, account addresses, or secrets.
- `.gitignore` is defense in depth. `bookstudio public-audit` is the publication
  gate.

## Implementation Rules

- Python 3.11+ standard library only unless the user explicitly approves a
  dependency.
- Follow red-green-refactor for every behavior change.
- Source EPUBs are read-only and must never be modified in place.
- Keep guided intake language-neutral; never add a universal target-language
  recommendation.
- Write generated files atomically.
- Reject unsafe archive paths, unsafe inline XHTML, stale source hashes, and
  incomplete release state.
- State-reading commands support JSON output and stable error codes.
- `skills/book-translation/` is the canonical public orchestration skill. Keep
  provider/model integration and private book content outside it.

## Verification

Run from this directory:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m bookstudio public-audit . --json
```

Run package install smoke tests from a copied checkout under a temporary
directory. A direct local build creates `build/` and `*.egg-info`, which the
public audit intentionally reports until those generated artifacts are removed.

Do not claim public readiness, packaging, licensing, installation, or release
unless its dedicated gate has passed.

If this checkout lives under `~/JAK` (the owner's workspace), read `~/JAK/AGENTS.md` first (map + floor rules), then `~/JAK/companies/publishing/AGENTS.md`. Standalone clones can ignore this line.

# AGENTS.md - Book Studio Core

## Mission

Build a safe, deterministic, provider-neutral EPUB translation engine and CLI,
with a fail-closed PDF source gateway that prepares reviewable semantic EPUBs.

## Public Boundary

- This repository contains reusable code, documentation, and synthetic tests
  only.
- Never add commercial books, translated prose, source-derived block maps,
  covers, provider responses, personal paths, account addresses, or secrets.
- `.gitignore` is defense in depth. `bookstudio public-audit` is the publication
  gate.
- The book-processing workflow and its generated book artifacts are for the
  user's private, personal, non-commercial use only. Follow
  [`personal-use-and-rights.md`](skills/book-translation/references/personal-use-and-rights.md):
  do not sell, monetize, publish, upload, share, redistribute, or build shared
  archives from them. Private local storage is allowed only for the user's own
  use.
- Stop any proposed commercial use for maintainer review. It may proceed only
  under a separate written commercial license from the software Licensor and
  binding written authorization from every applicable rights holder for the
  material being processed.

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

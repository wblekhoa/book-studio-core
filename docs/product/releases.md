---
id: book-studio-core-releases
type: release
product: book-studio-core
title: "Book Studio Core — Releases"
status: active
updated: 2026-10-13
relations:
  presentedBy: [github:wblekhoa/book-studio-core/releases]
---

# Book Studio Core — Releases (newest first)

Source of truth for details: `CHANGELOG.md` (repo root) and `gh release list -R wblekhoa/book-studio-core`.

**No GitHub release and no git tag exist.** `gh release list -R wblekhoa/book-studio-core` and `git tag` both returned
nothing on 2026-10-11. Readers install from the repository (`README.md` › Install). `CONTRIBUTING.md` keeps release
tags and package-index publication as separate maintainer decisions. Add an entry here only when a release is
actually published - never ahead of it.

## Unreleased (after 0.1.0, not published)

- **What changed for users**: the fail-closed PDF Source Gateway, book-specific production briefs and final-EPUB
  audits, localized navigation labels, the portable skill installer, the personal-use licence (`CHANGELOG.md`,
  Unreleased; commit `1671d21`), the installable Codex plugin with a bundled engine (commit `e027d96`), and the
  read-only `bookstudio review` page plus a spec-conformant plugin manifest (2026-10-13).
- **REQ-IDs it will ship**: BSC-PIPE-014, BSC-SKILL-001…010, BSC-REVIEW-001…007 and the PDF gateway (no REQ-IDs yet), plus everything
  below; all `live` on `main` as of 2026-10-11.
- **Channel**: none yet.
- **Shown in**: none yet.

## 0.1.0 · 2026-08-30 (CHANGELOG version, never published as a release)

- **What changed for users**: the first public source tree (commit `6abd800`, "Initial public release"): project
  initialization, archive preflight and inspection, stable block maps, provider-neutral packets and cache, guided
  intake with a representative pilot, inline XHTML and image safety gates, deterministic target-only and bilingual
  builds, the public-boundary audit and the portable `book-translation` skill. `pyproject.toml` still reports
  version `0.1.0`.
- **REQ-IDs shipped**: BSC-PIPE-001…013, 015, 016 and BSC-PILOT-001…013 correspond to behaviour first listed under 0.1.0
  in `CHANGELOG.md`; later refinements (for example the production brief in the policy identity) are Unreleased.
- **Channel**: public GitHub repository only (`main`); no tag, no GitHub release, no package index.
- **Shown in**: none yet.

---
id: book-studio-core-releases
type: release
product: book-studio-core
title: "Book Studio Core — Releases"
status: active
updated: 2026-11-02
summary: "Published Book Studio Core releases, newest first: 0.4.0 chat-first workflow with in-host progress views, 0.3.1 inline-markup hints in packets, 0.3.0 Claude Code plus Codex plugin, 0.2.0 Codex plugin with hardened edits for macOS and Linux, and the unpublished 0.1.0 initial source tree."
tags: [area/release, stack/python, surface/cli]
relations:
  presentedBy: [github:wblekhoa/book-studio-core/releases]
---

# Book Studio Core — Releases (newest first)

Source of truth for details: `CHANGELOG.md` (repo root) and `gh release list -R wblekhoa/book-studio-core`.

`CONTRIBUTING.md` keeps package-index publication a separate maintainer decision. Add an entry here only when a
release is actually published, never ahead of it.

## 0.4.0 · 2026-11-02 (tag `v0.4.0`, GitHub Release)

- **What changed for users**:
  - chat-first intake: the agent sees bounded source excerpts before asking for missing choices; sample review,
    pause and continue happen in chat, with the existing approval and finishing gates;
  - experimental in-host progress: a read-only `view` tool, a Claude Code Mods progress line and a Codex MCP Apps
    panel; no view can accept a sample;
  - `review` fails on an invalid cache instead of showing zero progress, reports `REVIEW_BUSY` on a moving project,
    and the MCP result uses one snapshot and no longer embeds the HTML page;
  - portable `plugin.json`/`mcp.json`, manifest versions owned by `pyproject.toml`, a checked one-command Codex
    install from a checkout, and refusal of book paths inside the installed plugin.
- **REQ-IDs shipped**: BSC-CHAT-001…011, BSC-REVIEW-008, BSC-SKILL-013 (all manifests), BSC-MCP-002 (updated).
- **Evidence**:
  - 288 tests; CI run 41429425562 green on macOS and Linux × Python 3.11–3.14;
  - `claude plugin validate --strict` and `claude plugin test` (5/5) pass;
  - an independent review found doc overclaims, a broken review fallback and manifest version drift; all fixed and
    re-reviewed before release;
  - the Codex panel was checked on one macOS Codex desktop build (spec `specs/2026-10-24-visual-workspace.md`).
  - **Not yet run**: the live Claude eval suite (`docs/behavior-evals.md`).
- **Channel**: GitHub tag and Release.
- **Shown in**: `github:wblekhoa/book-studio-core/releases/tag/v0.4.0`.

## 0.3.1 · 2026-11-02 (tag `v0.3.1`, GitHub Release)

- **What changed for users**:
  - packet blocks whose source holds inline emphasis, links, superscripts, subscripts or code carry an advisory
    `inline_markup` list, so the AI keeps that formatting in `translation_xhtml` instead of dropping it silently;
    noterefs and anchors stay with the builder, and packet IDs, block maps and caches are unchanged;
  - the public-boundary audit accepts the top-level `CLAUDE.md`;
  - install instructions point to `v0.3.1`; Python 3.14 is declared.
- **REQ-IDs shipped**: BSC-PIPE-017.
- **Evidence**:
  - 268 tests; CI run 41410718930 green on macOS and Linux × Python 3.11–3.14;
  - an independent review found a noteref-duplication bug in the first draft, fixed before release with an
    end-to-end check (one marker in the finished EPUB);
  - prepared block maps of the private dogfood projects re-extract identically.
  - **Not yet run**: the live Claude eval suite (`docs/behavior-evals.md`).
- **Channel**: GitHub tag and Release.
- **Shown in**: `github:wblekhoa/book-studio-core/releases/tag/v0.3.1`.

## 0.3.0 · 2026-10-13 (tag `v0.3.0`, GitHub Release)

- **What changed for users**:
  - the same plugin installs in **Claude Code** (`claude plugin marketplace add wblekhoa/book-studio-core`,
    `claude plugin install book-studio@book-studio`) and in Codex;
  - commands `/book-studio:translate`, `:review`, `:finish` and `:capture`;
  - `book-translator` and `editorial-reviewer` agents;
  - hooks that refuse direct edits to the certified EPUB, its receipt and the cache, and show project status at
    session start;
  - an MCP server with 11 tools plus an experimental in-chat review view;
  - an optional `projects_dir` setting;
  - an official eval suite.
- **REQ-IDs shipped**: BSC-HOOK-001…004, BSC-MCP-001…003, BSC-SKILL-016…017.
- **Evidence**:
  - 262 tests and CI on macOS and Linux;
  - `claude plugin validate --strict` passes for the plugin and the marketplace;
  - clean-room installs from GitHub in Claude Code and Codex.
  - **Not yet run**: the live Claude eval suite. The local CLI was logged out, so its results are pending in
    `docs/behavior-evals.md`.
- **Channel**: GitHub tag and Release.
- **Shown in**: `github:wblekhoa/book-studio-core/releases/tag/v0.3.0`.

## 0.2.0 · 2026-10-13 (tag `v0.2.0`, GitHub Release)

- **What changed for users**:
  - an installable Codex plugin with a bundled engine, installable straight from GitHub
    (`codex plugin marketplace add wblekhoa/book-studio-core@v0.2.0`);
  - the read-only `bookstudio review` page;
  - declared post-build edits (`edits.json`) certified by `finish`, plus `edits capture`;
  - `apply-drafts`;
  - the fail-closed PDF Source Gateway;
  - production briefs and final-EPUB audits;
  - localized navigation labels;
  - the skill installer;
  - the personal-use licence;
  - plugin artwork.
- **Platforms**: macOS and Linux, Python 3.11-3.14 (CI). Windows is not supported yet.
- **REQ-IDs shipped**: BSC-PIPE-014, BSC-SKILL-001…015, BSC-REVIEW-001…007, BSC-EDIT-001…011, BSC-DRAFT-001…004 and the PDF
  gateway (no REQ-IDs yet).
- **Evidence**:
  - 253 unit tests;
  - a clean-room GitHub install;
  - three live Codex behaviour scenarios (`docs/behavior-evals.md`);
  - a security review with every high and medium finding fixed;
  - four real books re-certified in the private workspace.
- **Channel**: GitHub tag and Release; no package index.
- **Shown in**: `github:wblekhoa/book-studio-core/releases/tag/v0.2.0`.

## 0.1.0 · 2026-08-30 (CHANGELOG version, never published as a release)

- **What changed for users**: the first public source tree (commit `6abd800`, "Initial public release"): project
  initialization, archive preflight and inspection, stable block maps, provider-neutral packets and cache, guided
  intake with a representative pilot, inline XHTML and image safety gates, deterministic target-only and bilingual
  builds, the public-boundary audit and the portable `book-translation` skill. `pyproject.toml` reported
  version `0.1.0`.
- **REQ-IDs shipped**: BSC-PIPE-001…013, 015, 016 and BSC-PILOT-001…013 correspond to behaviour first listed under 0.1.0
  in `CHANGELOG.md`; later refinements (for example the production brief in the policy identity) are Unreleased.
- **Channel**: public GitHub repository only (`main`); no tag, no GitHub release, no package index.
- **Shown in**: none yet.

# Changelog

## Unreleased

- Chat-first intake with bounded source excerpts before the agent asks unresolved questions; explicit chat sample
  review and pause/continue guidance, preserving the existing acceptance and final-book gates.
- Read-only MCP `view` plus optional live sample/progress UI, with bounded content, coherent snapshot retries and
  protection against late responses from a previously selected project.
- Claude Code Mods progress inside the conversation, with official-runner terminal/desktop tests.
- Portable plugin and local stdio MCP manifests, alongside the existing compatibility manifests.
- Checked one-command Codex checkout installation with dry-run, cache parity and installed MCP transport probes.
- Refuse private book paths inside an installed plugin; resolve private absolute paths in the conversation.
- Explicit in-host review presentation for Codex: the panel shows saved progress after `apply` without another
  `review` call. Experimental; host support varies.
- `bookstudio review` now fails with the cache or coverage error instead of rendering a page without coverage, and
  returns `REVIEW_BUSY` if the project keeps changing while it reads.
- The MCP `review` result no longer embeds the HTML page; it returns the written report path and the `view` data.
- Live Claude model evals have not been run for these changes.

## 0.3.1 - 2026-11-02

- Packet blocks whose source holds inline emphasis, links, superscripts,
  subscripts, or code now carry an advisory `inline_markup` list, so the AI can
  return a matching `translation_xhtml` instead of silently dropping the
  markup. Packet IDs and existing caches are unchanged.
- The public-boundary audit allows the top-level `CLAUDE.md`.
- Install instructions point to `v0.3.1`; Python 3.14 is declared (CI already
  tested it); `.pytest_cache/` is ignored.

## 0.3.0 - 2026-10-13

- Claude Code plugin from the same folder as the Codex plugin: repository marketplace, commands
  (`/book-studio:translate`, `:review`, `:finish`, `:capture`), `book-translator` and `editorial-reviewer` agents,
  an optional `projects_dir` setting, and an official eval suite.
- `bookstudio hook guard|session-start`: refuse direct writes to the certified EPUB, its receipt and the cache
  inside projects, and list nearby projects with their next command.
- `bookstudio mcp`: a stdlib MCP server with 11 tools that reuse the CLI gates, plus an experimental MCP Apps
  review view.

## 0.2.0 - 2026-10-13

- Added a fail-closed PDF source gateway that prepares supported text-layer
  PDFs as review-required semantic EPUBs without adding OCR or model-provider
  dependencies.
- Added book-specific production briefs, contextual packet binding, front-matter
  coverage, candidate-bound editorial receipts, and deterministic final-EPUB
  audit scripts.
- Preserved target-only anchors and pagebreaks, localized navigation labels,
  and added conservative reader-compatible image annotation and companion
  styling.
- Added a portable skill installer with dry-run, parity-check, backup, and
  rollback behavior.
- Added an installable Codex plugin that bundles its matching engine, with a
  manifest that follows the Codex plugin spec (starter prompts as a list).
- Added `bookstudio review`, which writes a read-only, self-contained HTML page
  with the project stage, progress, the sample beside its source, the recorded
  choices, the final-gate status, and the exact next command.
- Added declared post-build edits: hash-pinned operations in `edits.json` are
  applied inside `build`, so `finish` certifies the delivered book.
- Added `bookstudio apply-drafts`, which preflights a whole drafts file and
  applies it packet by packet, stopping at the sample review.
- Updated the skill references so post-build corrections go through
  `edits.json`, with drafts and review guidance and contract tests.
- Added `bookstudio edits capture`, which writes `edits.json` from an EPUB
  edited elsewhere.
- Hardened declared edits: markup is checked by manifest media-type with an
  allowlist for links and resources; capture refuses symlinked, colliding,
  or reserved destinations; `apply-drafts` checks inline markup before any
  write.
- Plugin artwork (logo, two synthetic screenshots); the plugin and engine now
  share one release version. CI covers macOS and Linux with Python 3.11-3.14.
- Replaced the MIT license for current and future distributions with the
  source-available Book Studio Personal Use License 1.0. Personal,
  non-commercial use remains permitted; commercial use requires separate
  written authorization from both the software Licensor and every applicable
  rights holder for processed material.

## 0.1.0 - 2026-08-30

- Added zero-dependency project initialization and AI-friendly CLI contracts.
- Added bounded EPUB archive preflight, inspection, and stable block maps.
- Added provider-neutral packet, response, cache, and coverage contracts.
- Added guided intake, deterministic representative pilots, and explicit pilot
  acceptance before full-book translation.
- Added detailed human-readable question choices, recommendations, and error
  recovery actions without changing the JSON contract.
- Added descriptive root and nested command help, including the pilot
  confirmation boundary, and stopped advertising the unimplemented `clean`
  placeholder.
- Added inline XHTML and image companion safety gates.
- Added deterministic target-only and bilingual builds, including the legacy
  `vi_only` compatibility spelling, with independent integrity and
  reproducibility validation.
- Added allowlist-first public-boundary audit and synthetic tests.
- Added a dependency-free installable CLI package, MIT license, and Python
  3.11-3.13 CI contract.
- Added a root `bookstudio --version` receipt for installation checks.
- Added the portable `book-translation` AI skill for guided intake, editorial
  pilot review, and provider-neutral packet orchestration.
- Added explicit, scope-bound pilot revision before acceptance.
- Bound every pre-acceptance pilot load to the locked guided language, output,
  and complete profile policy.
- Added project-wide managed-path validation so internal directory and artifact
  symlinks cannot redirect canonical reads or writes outside the project.
- Made CLI defaults, glossary guidance, and image validation language-neutral.
- Hardened the publication audit to inspect cache directories and moved its CI
  preflight ahead of package installation.
- Bound packet IDs and accepted rows to content-free hashes of policy, prompt,
  glossary, reference notes, and image-manifest context so stale pilot work
  cannot satisfy acceptance after editorial inputs change.
- Bound packet IDs to the source name, whole-file identity, and neighboring
  context; rejected stale in-memory config snapshots and cache rows whose
  packet/context identity pair is missing, partial, or null.
- Made the publication audit reject compiled artifacts and recognize Linux plus
  arbitrary-drive Windows personal paths; CI compiles only a temporary copy.
- Made structured application errors compatible with Python's normal traceback
  lifecycle.

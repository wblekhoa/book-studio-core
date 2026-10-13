# Changelog

## Unreleased

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

---
id: book-studio-core-goal
type: goal
product: book-studio-core
title: "Book Studio Core — Product goal"
status: active
updated: 2026-10-13
---

# Book Studio Core — Product goal

## Problem

- A reader who wants an EPUB (or a text-layer PDF) in another language for their own use has two poor options:
  paste chapters into a chat window by hand, losing structure, images, links and consistency; or hand the whole
  book to an opaque service. Neither leaves a checkable record of what was translated, against which source, with
  which editorial choices.

## Audience

- Primary: one person translating a book they have the right to process, for their own private reading, study,
  accessibility or research, with an AI assistant of their choice. The workflow has been dogfooded most deeply on
  English to Vietnamese, but nothing in it assumes a target language.
- Secondary: an AI agent (Codex, or any agent that reads directory-based skills) that drives the workflow for that
  person through the CLI's JSON contracts.
- Who pays: nobody. The code is source-available under the Book Studio Personal Use License 1.0; commercial use
  needs a separate written licence (`LICENSE`, `README.md`).

## Promise

- Turn a source EPUB into a reviewed, structurally valid translated EPUB through bounded AI packets, without the
  engine ever calling a model, uploading the book or modifying the source - and refuse to finish when anything is
  unsafe, stale or incomplete.

## Success measures

| Measure                         | Today (observed 2026-10-11)                                                                                       | Target   | How it is measured (command, dashboard, store data)                                          |
| ------------------------------- | ----------------------------------------------------------------------------------------------------------------- | -------- | -------------------------------------------------------------------------------------------- |
| Unit test suite                 | 253 of 253 pass locally (2026-10-13)                                                                              | all pass | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v`          |
| CI on `main` (Python 3.11-3.13) | last 3 runs green (latest on commit `e027d96`)                                                                    | green    | `gh run list -R wblekhoa/book-studio-core`                                                   |
| Public-boundary audit           | passes in a clean checkout and in CI (before install and after tests)                                             | passes   | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m bookstudio public-audit . --json`       |
| Public releases                 | 0 (no GitHub release, no git tag)                                                                                 | not set  | `gh release list -R wblekhoa/book-studio-core`                                               |
| GitHub stars / forks            | 0 / 0 (GitHub API, 2026-10-11)                                                                                    | not set  | `gh api repos/wblekhoa/book-studio-core --jq '{stars:.stargazers_count,forks:.forks_count}'` |
| Books translated end to end     | not measured                                                                                                      | not set  | no method: the engine keeps no usage record and book projects live outside the repo by design |

## Non-goals

- No bundled model or provider client: the engine emits packets and accepts responses as local JSON only.
- No OCR, no scanned or image-only PDFs, no exact fixed-layout reproduction, tables or equations from PDF.
- No book content in this repository: no source books, translated prose, block maps, covers or provider responses.
- No sharing, publishing or selling of generated books; private local use only.
- No third-party Python dependency without an explicit maintainer decision.

## Links

- UX: `ux/translation-pipeline.md` · `ux/guided-pilot.md` · `ux/portable-skill.md`
- Logic: `logic/translation-pipeline.md` · `logic/guided-pilot.md` · `logic/portable-skill.md`
- Decisions: `decisions.md` · Releases: `releases.md`
- Engineering detail (not duplicated here): `docs/architecture.md`, `docs/ai-packets.md`, `docs/safety.md`,
  `docs/guided-intake.md`, `docs/pdf-source-preparation.md`, `docs/codex-plugin.md`

## Change log

- 2026-10-11: created (doc-engine rollout); measures read from the test run, `gh` and the GitHub API on this date.

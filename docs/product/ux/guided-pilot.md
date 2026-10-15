---
id: book-studio-core-ux-guided-pilot
type: ux
product: book-studio-core
title: "Book Studio Core — Guided intake and pilot (UX)"
status: active
updated: 2026-10-11
summary: "How a new translation starts: start asks only the missing questions and proposes one representative chapter, which the reader approves, reviews and confirms before the rest of the book is translated."
tags: [area/translation, area/book, stack/python, surface/cli]
relations:
  specifies:
    - book-studio-core:src/bookstudio/intake.py
    - book-studio-core:src/bookstudio/pilot.py
    - book-studio-core:src/bookstudio/cli.py
  dependsOn: [book-studio-core-logic-guided-pilot]
  sharesSurfaceWith: [book-studio-core-ux-translation-pipeline]
---

# Book Studio Core — Guided intake and pilot (UX)

> Feature master: read this file first to understand how a new translation starts and how the reader approves a
> sample before the whole book is translated. Rules live in `logic/guided-pilot.md`; the full command walkthrough is
> `docs/guided-intake.md`.

## Purpose

- Problem: a reader cannot judge tone, terminology or image treatment until they see a real chapter, and a whole-book
  run with the wrong choices wastes the run.
- Audience: the reader, usually talking to an AI agent that turns the conversation into `start` answers.
- Success signal: the reader sees and accepts one representative chapter before anything else is translated.

## Scope

- Included: `start` (questions and project creation), `pilot status`, `pilot approve`, `pilot revise`,
  `pilot accept --confirm`, and the way `next` / `build` / `finish` are held back until acceptance.
- Excluded: the packet loop itself (`ux/translation-pipeline.md`).

## Current truth

- `start PROJECT --source BOOK.epub` first only looks: if decisions are missing it exits 2 with numbered questions
  (stable ID, choices, recommendation) and creates nothing. An agent rephrases them naturally, collects the replies
  and reruns `start --answers answers.json`.
- Questions cover target language, output (target-only or bilingual), audience, translation approach, market context,
  layout, and - only when the book has images - image text and image annotation policy. The target language is never
  recommended.
- With complete answers, `start` creates the project and proposes one pilot chapter chosen deterministically - a real
  chapter, not the title page or legal front matter.
- The reader approves the pilot, the agent translates just that chapter, and `next` then stops with "review required".
  The reader can ask for revisions of pilot rows, and finally accepts with an explicit `--confirm`. Only then do
  packets for the rest of the book appear.
- After acceptance, changing the locked choices (for example the target language or glossary) is refused rather than
  silently mixed into the book; a material change starts a new guided project.

## Screens and states

| Screen (CLI step)        | States                                              | Entry                         | Exit / next                         |
| ------------------------ | --------------------------------------------------- | ----------------------------- | ----------------------------------- |
| `start`                  | needs input (exit 2) · ready · not owned            | source EPUB, optional answers | `pilot status`                      |
| `pilot status`           | `pilot_proposed` · `pilot_active` · `pilot_review_required` · `full_active` | project | the "Next action" it prints |
| `pilot approve`          | `pilot_active`                                      | `pilot_proposed`              | `next` / `apply` for pilot targets  |
| `pilot revise`           | revised · locked after acceptance                   | `pilot_review_required`       | review again                        |
| `pilot accept --confirm` | `full_active` · confirmation required · incomplete  | `pilot_review_required`       | `next` for the rest of the book     |

## Flow

```mermaid
flowchart LR
  A[start] -- missing answers --> B[questions, nothing created]
  B --> C[agent asks the reader]
  C --> A
  A -- complete --> D[pilot_proposed]
  D --> E[pilot approve]
  E --> F[translate pilot chapter]
  F --> G[pilot_review_required]
  G -- revise --> G
  G -- accept --confirm --> H[full_active]
  H --> I[rest of the book]
```

## Reading order

| File                     | Role                                   |
| ------------------------ | -------------------------------------- |
| this file                | current truth                          |
| `logic/guided-pilot.md`  | rules + REQ-IDs                        |
| `docs/guided-intake.md`  | full command walkthrough (engineering) |

## Change log

- 2026-10-11: created.

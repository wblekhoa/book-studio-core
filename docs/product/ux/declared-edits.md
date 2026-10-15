---
id: book-studio-core-ux-declared-edits
type: ux
product: book-studio-core
title: "Book Studio Core — Declared edits (UX)"
status: active
updated: 2026-10-13
summary: "How a person declares post-build corrections in edits.json, or captures them from an EPUB edited elsewhere, so finish certifies the corrected book and the review page reports the number of declared edits."
tags: [area/book, area/build, stack/python, surface/cli]
relations:
  specifies: [book-studio-core:src/bookstudio/epub/edits.py]
  dependsOn: [book-studio-core-ux-translation-pipeline]
  sharesSurfaceWith: [book-studio-core-ux-review-page]
figma: []
---

# Book Studio Core — Declared edits (UX)

> Feature master: read this file first. The rules live in `logic/declared-edits.md`.

## Purpose

- Problem: corrections made after the build happened outside the gate, so the book you read was not the book that was
  checked.
- Audience: the person finishing a translated book, or the AI acting for them.
- Success signal: `finish` succeeds with the edits, and the review page shows "Matches the gate receipt" with the
  number of declared edits.

## Scope

- Included: a project file `edits.json` with three operations, applied by `build`, `finish` and `release`;
  `bookstudio edits capture PROJECT --from EDITED.epub` writes it from an EPUB edited elsewhere.
- Excluded: deleting members, changing the source EPUB, and editing `output/final.epub` after `finish`.

## Current truth

```json
{
  "schema_version": 1,
  "operations": [
    {"op": "replace_text", "member": "OEBPS/bookstudio/bookstudio.css", "find": "…", "replace": "…", "count": 1},
    {"op": "replace_member", "member": "OEBPS/xhtml/02-contents.xhtml", "base_sha256": "…", "from": "assets/edits/02-contents.xhtml", "sha256": "…", "note": "linked contents page"},
    {"op": "add_member", "member": "OEBPS/images/cover-marked.png", "from": "assets/cover/cover-marked.png", "sha256": "…"}
  ]
}
```

- Every failure names the operation number, the member and the next action. Nothing is written until every operation
  succeeds.
- A mark added to a cover is a new image plus `replace_text` edits to the OPF and the cover page. The original cover
  stays in the book.

## Screens and states

| Surface       | States                                        | Entry                 | Exit / next                       |
| ------------- | --------------------------------------------- | --------------------- | --------------------------------- |
| CLI `finish`  | pass with `edits.applied` · stable error code | `bookstudio finish`   | `verify`, `review`                |
| Review page   | Final book: "Declared edits: N"               | `bookstudio review`   | rerun after any change            |

## Flow

```mermaid
flowchart LR
  A[Translation complete] --> B[Write replacement files + edits.json]
  B --> C[bookstudio finish]
  C -->|stable error| B
  C --> D[final.epub certified with edits]
  D --> E[bookstudio review]
```

## Reading order

| File                       | Role            |
| -------------------------- | --------------- |
| this file                  | current truth   |
| `logic/declared-edits.md`  | rules + REQ-IDs |

## Change log

- 2026-10-13: created.

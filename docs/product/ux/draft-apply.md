---
id: book-studio-core-ux-draft-apply
type: ux
product: book-studio-core
title: "Book Studio Core — Draft apply (UX)"
status: active
updated: 2026-10-13
relations:
  specifies: [book-studio-core:src/bookstudio/translation/drafts.py]
  dependsOn: [book-studio-core-ux-guided-pilot]
  sharesSurfaceWith: []
figma: []
---

# Book Studio Core — Draft apply (UX)

> Feature master: read this file first. The rules live in `logic/draft-apply.md`.

## Purpose

- Problem: applying whole-chapter drafts one packet at a time is slow and was scripted separately for each book.
- Audience: an AI agent that has drafted chapters ahead, acting for the person translating.
- Success signal: one command per lifecycle phase, with a clear stop reason.

## Scope

- Included: `bookstudio apply-drafts PROJECT DRAFTS.json [--json]`.
- Excluded: producing drafts, skipping the sample review, and partial packets.

## Current truth

```json
{
  "schema_version": 1,
  "source_sha256": "<the project's source EPUB hash>",
  "drafts": [
    {"source_document": "OEBPS/text/chapter.xhtml", "block_index": 4, "source_sha256": "<block text hash>", "translation": "…", "translation_xhtml": "optional"}
  ]
}
```

- Result statuses: `pilot_review_required`, `complete`, or `draft_missing` (with up to 20 missing blocks). Each status
  comes with `applied_packets`, `applied_blocks` and `next_action`.

## Screens and states

| Surface            | States                                              | Entry                        | Exit / next                         |
| ------------------ | --------------------------------------------------- | ---------------------------- | ----------------------------------- |
| CLI `apply-drafts` | pilot_review_required · complete · draft_missing · error code | after `pilot approve` or `accept` | `review`, `pilot accept`, `finish` |

## Flow

```mermaid
flowchart LR
  A[pilot approve] --> B[apply-drafts]
  B --> C[pilot_review_required]
  C --> D[review + pilot accept --confirm]
  D --> E[apply-drafts]
  E --> F[complete]
  F --> G[finish]
```

## Reading order

| File                    | Role            |
| ----------------------- | --------------- |
| this file               | current truth   |
| `logic/draft-apply.md`  | rules + REQ-IDs |

## Change log

- 2026-10-13: created.

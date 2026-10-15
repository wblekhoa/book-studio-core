---
id: book-studio-core-logic-draft-apply
type: logic
product: book-studio-core
title: "Book Studio Core — Draft apply (logic)"
status: active
updated: 2026-10-13
summary: "Rules for apply-drafts: preflight a whole-chapter drafts file before any write, apply it packet by packet with next/apply semantics, stop at the sample review gate, and stop with draft_missing at the first gap."
tags: [area/translation, area/ai, stack/python, surface/cli]
reqPrefix: BSC-DRAFT
relations:
  specifiedBy: [book-studio-core-ux-draft-apply]
  implements:
    - book-studio-core:src/bookstudio/translation/drafts.py
    - book-studio-core:src/bookstudio/cli.py
  dependsOn: [book-studio-core-logic-translation-pipeline, book-studio-core-logic-guided-pilot]
---

# Book Studio Core — Draft apply (logic)

## Purpose

- Problem: when an AI drafts whole chapters ahead, each project wrote its own loop around `next`/`apply`.
- Success signal: one command applies a prepared drafts file through the unchanged packet contract and stops at the
  same boundaries a person would.

## Rules

Status column: `live`, `not built`, or `blocked`. A live rule has its REQ-ID as a one-line `# BSC-…` comment next to
the test named in Evidence.

| REQ-ID        | Rule (behaviour-changing)                                                                                                                                                       | Status | Evidence (code path or test)                                                            |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ | --------------------------------------------------------------------------------------- |
| BSC-DRAFT-001 | `apply-drafts` applies drafts packet by packet with `next`/`apply` semantics. It stops at `pilot_review_required` (the sample gate is never skipped), and after acceptance it continues to `complete`. | live   | `tests/test_drafts.py` (`test_drafts_stop_at_pilot_review_then_finish_full_book`)       |
| BSC-DRAFT-002 | When the next packet needs a block with no draft, the command stops before that packet, exits 2 with `draft_missing`, and lists the missing blocks.                              | live   | `tests/test_drafts.py` (`test_missing_draft_stops_before_that_packet`)                  |
| BSC-DRAFT-003 | The whole file is preflighted before any write. A stale source hash, an unknown or ineligible block, another source EPUB, or a duplicate row each fail with a stable code and an empty cache. | live   | `tests/test_drafts.py` (`test_stale_or_unknown_drafts_fail_before_any_write`)           |
| BSC-DRAFT-004 | Every row's `translation_xhtml` passes the inline XHTML allowlist during preflight, so one unsafe row fails the whole file before any packet is applied (the cache stays empty).                       | live   | `tests/test_drafts.py` (`test_unsafe_inline_markup_is_rejected_by_the_packet_gate`)     |

## States and transitions

| State                 | Trigger          | Result                         | Edge case                                   |
| --------------------- | ---------------- | ------------------------------ | ------------------------------------------- |
| pilot_active          | `apply-drafts`   | `pilot_review_required` (exit 0) | only sample blocks are applied             |
| full_active / legacy  | `apply-drafts`   | `complete` (exit 0)            | `draft_missing` (exit 2) at the first gap  |
| pilot_proposed        | `apply-drafts`   | `PILOT_APPROVAL_REQUIRED`      | approval is never implied                   |

## Fixed vs flexible

- Fixed: same packet IDs, context binding, cache validation, and sample gate as manual `next`/`apply`. Each applied
  response is kept under `packets/drafts/`.
- Flexible: how drafts are produced, and their optional `note` field.

## Open questions

- None.

## Change log

- 2026-10-13: created with BSC-DRAFT-001…004.

---
id: book-studio-core-logic-review-page
type: logic
product: book-studio-core
title: "Book Studio Core — Review page (logic)"
status: active
updated: 2026-10-13
reqPrefix: BSC-REVIEW
relations:
  specifiedBy: [book-studio-core-ux-review-page]
  implements:
    - book-studio-core:src/bookstudio/review.py
    - book-studio-core:src/bookstudio/cli.py
  dependsOn: [book-studio-core-logic-guided-pilot, book-studio-core-logic-translation-pipeline]
---

# Book Studio Core — Review page (logic)

## Purpose

- Problem: the reader has to judge the sample and follow progress through JSON receipts and terminal text. Reading
  the source and the translation side by side in a terminal is slow, and it is easy to miss which step comes next.
- Audience: the person translating a book for their own reading, working alone or through an AI agent.
- Success signal: one command produces a page that shows where the project is, how much is done, the sample next to
  its source, and the exact next command. The project's lifecycle state never changes as a result.

## Rules

Status column: `live`, `not built`, or `blocked`. A live rule has its REQ-ID as a one-line `# BSC-…` comment next to
the test named in Evidence.

| REQ-ID         | Rule (behaviour-changing)                                                                                                                                                                                       | Status | Evidence (code path or test)                                                                          |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ | ----------------------------------------------------------------------------------------------------- |
| BSC-REVIEW-001 | `bookstudio review PROJECT` writes `reports/review.html`. The page shows each sample block's source and its translation side by side, the recorded choices, and the next command for the current stage.     | live   | `tests/test_review.py` (`test_pilot_review_page_shows_source_and_translation_side_by_side`)           |
| BSC-REVIEW-002 | Review is read-only for lifecycle state. Every project file outside `reports/` keeps its exact bytes.                                                                                                          | live   | `tests/test_review.py` (`test_review_is_read_only_for_lifecycle_state`)                               |
| BSC-REVIEW-003 | All book text is HTML-escaped. The page carries a `default-src 'none'` Content-Security-Policy, has no script, loads no external resource, and contains no absolute local path.                             | live   | `tests/test_review.py` (`test_book_text_is_escaped_and_page_is_self_contained`)                       |
| BSC-REVIEW-004 | A proposed sample lists its untranslated target blocks and points to `pilot approve`.                                                                                                                          | live   | `tests/test_review.py` (`test_proposed_pilot_page_lists_untranslated_targets_and_approve_command`)    |
| BSC-REVIEW-005 | An expert project with no sample gate still renders a page and points to `next`.                                                                                                                                | live   | `tests/test_review.py` (`test_expert_project_without_pilot_still_renders`)                            |
| BSC-REVIEW-006 | A missing project fails with a stable JSON error code.                                                                                                                                                          | live   | `tests/test_review.py` (`test_missing_project_fails_with_stable_code`)                                |
| BSC-REVIEW-007 | The page shows "Finished" only while `output/final.epub` matches the SHA-256 in `reports/release.json`. A changed output falls back to the full-book stage and points to `finish`.                         | live   | `tests/test_review.py` (`test_finished_page_reports_gate_and_detects_changed_output`)                 |

## States and transitions

The page reflects the pilot lifecycle; it never moves it.

| State shown           | Derived from                                               | Next command shown           | Edge case                                      |
| --------------------- | ---------------------------------------------------------- | ---------------------------- | ---------------------------------------------- |
| Expert project        | no `state/pilot.json` (`legacy`)                           | `next`, or `finish` when 0 remain | no intake: choices come from `bookstudio.toml` |
| Sample proposed       | `pilot_proposed`                                           | `pilot approve`              | every sample block marked "Not translated yet" |
| Sample in translation | `pilot_active`                                             | `next`                       |                                                |
| Sample review         | `pilot_review_required`                                    | `pilot accept --confirm`     |                                                |
| Full book             | `full_active`                                              | `next`, or `finish` when 0 remain | a cached block whose source hash changed is marked "Source changed" |
| Finished              | coverage complete and `release.json` matches `final.epub`  | `verify`                     | changed `final.epub`: back to Full book        |

## Fixed vs flexible

- Fixed: read-only; escaped text only; no script, network, or external asset; output only at `reports/review.html`
  inside the private project; progress numbers come from the same coverage receipt that `status` uses.
- Flexible: layout, wording, and visual style; the sample block cap (60); which extra receipts the page summarizes.

## Open questions

- Should the page show source images and their localized companions? This needs a size budget, because images would
  be embedded as data URIs.

## Change log

- 2026-10-13: created with BSC-REVIEW-001…007.

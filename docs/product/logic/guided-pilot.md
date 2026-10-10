---
id: book-studio-core-logic-guided-pilot
type: logic
product: book-studio-core
title: "Book Studio Core — Guided intake and pilot (logic)"
status: active
updated: 2026-10-11
reqPrefix: BSC-PILOT
relations:
  specifiedBy: [book-studio-core-ux-guided-pilot]
  implements:
    - book-studio-core:src/bookstudio/intake.py
    - book-studio-core:src/bookstudio/pilot.py
    - book-studio-core:src/bookstudio/cli.py
  dependsOn: [book-studio-core-logic-translation-pipeline]
---

# Book Studio Core — Guided intake and pilot (logic)

## Purpose

- Ask the reader only the decisions the book actually needs, lock them, translate one representative chapter first,
  and unlock the rest of the book only after the reader explicitly accepts that sample.
- Success signal: no full-book packet, build or finish is possible before an explicit `pilot accept --confirm`, and
  any later change to the locked editorial policy fails closed instead of silently changing the book.

## Rules

Status column: `live`, `not built`, or `blocked`. A live rule has its REQ-ID as a one-line `# BSC-…` comment next to
the test named in Evidence.

| REQ-ID        | Rule (behaviour-changing)                                                                                                                                                                         | Status | Evidence (code path or test)                                                                                                                                 |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| BSC-PILOT-001 | `start` with missing answers exits 2 with `status: needs_input` and a `questions` list, creates no project folder, and prints no local path.                                                      | live   | `tests/test_cli.py` (`test_start_missing_answers_returns_questions_without_creating_project`)                                                                |
| BSC-PILOT-002 | Answered questions are not asked again; the two image questions appear only when the source has images; the source language is taken from metadata when it is unambiguous; questions come in a fixed order. | live   | `tests/test_intake.py` (`test_assessment_omits_known_answers_and_image_questions_without_images`, `test_assessment_infers_single_metadata_language_and_orders_missing_questions`) |
| BSC-PILOT-003 | Every question exposes stable `accepted_values` and a `recommendation`; the target language has neither, so no target language is ever suggested.                                                | live   | `tests/test_intake.py` (`test_missing_questions_expose_stable_accepted_values_and_recommendations`)                                                          |
| BSC-PILOT-004 | Unknown answer keys, non-string answers and invalid language codes are rejected (`INTAKE_ANSWER_UNKNOWN`, `INTAKE_ANSWER_INVALID`, `CONFIG_LANGUAGE_INVALID`).                                    | live   | `tests/test_intake.py` (`test_assessment_rejects_unknown_non_string_and_invalid_language_answers`)                                                           |
| BSC-PILOT-005 | `start` into a non-empty folder Book Studio does not own fails `PROJECT_NOT_OWNED` and leaves the user's files untouched.                                                                         | live   | `tests/test_cli.py` (`test_start_refuses_nonempty_unowned_target_without_mutation`)                                                                          |
| BSC-PILOT-006 | With complete answers, `start` writes the locked intake, the block map and a deterministic `pilot_proposed` proposal for one representative chapter, never the title page or legal front matter. | live   | `tests/test_intake.py` (`test_start_project_writes_deterministic_pilot_after_prepared_artifacts`); `tests/test_pilot.py` (`test_selector_chooses_chapter_not_title_or_legal`) |
| BSC-PILOT-007 | Before approval, `next` exits 2 with `PILOT_APPROVAL_REQUIRED`; `pilot approve` moves to `pilot_active` and the translation scope becomes exactly the pilot targets.                              | live   | `tests/test_cli.py` (`test_pilot_status_and_approve_report_canonical_status_and_next_action`); `tests/test_pilot.py` (`test_approve_creates_translation_scope_and_derived_review_requirement`) |
| BSC-PILOT-008 | When every pilot target is translated, `next` exits 2 with `PILOT_REVIEW_REQUIRED` and status reads `pilot_review_required`, derived without rewriting `state/pilot.json`.                         | live   | `tests/test_cli.py` (`test_cli_requires_review_after_last_pilot_packet`)                                                                                     |
| BSC-PILOT-009 | `pilot accept` needs `--confirm` (`PILOT_CONFIRMATION_REQUIRED`) and complete pilot rows (`PILOT_INCOMPLETE`); accepting records `full_active` with a policy identity, and old pilot responses become stale. | live   | `tests/test_cli.py` (`test_accept_requires_confirm_then_unlocks_full_scope`); `tests/test_pilot.py` (`test_accept_fails_without_complete_pilot_and_preserves_state`) |
| BSC-PILOT-010 | `pilot revise` replaces existing pilot rows only before acceptance; afterwards it fails `PILOT_REVISION_LOCKED` and the cache is unchanged.                                                       | live   | `tests/test_cli.py` (`test_completed_pilot_can_be_revised_before_acceptance_but_not_after`)                                                                  |
| BSC-PILOT-011 | Before acceptance, a config edit that departs from the locked intake (target language, audience) fails `PILOT_CONFIG_DRIFT`; after acceptance, drift in any policy component fails without mutation. | live   | `tests/test_pilot.py` (`test_pre_acceptance_pilot_rejects_config_drift_from_locked_intake`, `test_full_active_load_rejects_each_policy_component_drift_without_mutation`) |
| BSC-PILOT-012 | Before acceptance, a cache row outside the pilot targets fails `CACHE_SCOPE_INVALID`; after acceptance such rows are allowed.                                                                     | live   | `tests/test_pilot.py` (`test_pilot_cache_scope_is_strict_until_acceptance_then_allows_global_rows`)                                                         |
| BSC-PILOT-013 | `build` and `finish` on a guided project before acceptance fail `PILOT_FULL_SCOPE_BLOCKED`; with its pilot state missing they fail `PILOT_STATE_MISSING` and write nothing.                       | live   | `tests/test_epub_pipeline.py` (`test_direct_build_and_finish_reject_unaccepted_guided_project`)                                                              |

## States and transitions

| State                   | Trigger                               | Next state              | Edge case                                                              |
| ----------------------- | ------------------------------------- | ----------------------- | ---------------------------------------------------------------------- |
| no project              | `start` without complete answers      | no project (exit 2)     | questions returned; nothing written                                     |
| no project              | `start --answers` complete            | `pilot_proposed`        | folder not owned: `PROJECT_NOT_OWNED`                                   |
| `pilot_proposed`        | `pilot approve`                       | `pilot_active`          | `next` before this: `PILOT_APPROVAL_REQUIRED`                           |
| `pilot_active`          | last pilot target applied             | `pilot_review_required` | derived on read; `state/pilot.json` not rewritten                       |
| `pilot_review_required` | `pilot revise RESPONSE`               | `pilot_review_required` | replaces existing pilot rows only                                       |
| `pilot_review_required` | `pilot accept --confirm`              | `full_active`           | without `--confirm`: `PILOT_CONFIRMATION_REQUIRED`                      |
| `full_active`           | remaining `next` / `apply`, `finish`  | finished book           | any locked-policy drift fails closed; `pilot revise` locked             |

## Fixed vs flexible

- Fixed: the reader must explicitly accept the pilot before full scope; the core, not the AI caller, validates and
  owns the answers; no universal target-language recommendation; a direct `init` project (no pilot state) keeps the
  original full-scope behaviour.
- Flexible: how an AI caller phrases the questions, the conversation order, and how the pilot sample is presented for
  review.

## Open questions

- None recorded.

## Change log

- 2026-10-11: created; REQ-IDs added as one-line `# BSC-PILOT-…` comments next to the tests in the same commit.

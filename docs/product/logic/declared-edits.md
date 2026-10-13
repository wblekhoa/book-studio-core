---
id: book-studio-core-logic-declared-edits
type: logic
product: book-studio-core
title: "Book Studio Core — Declared edits (logic)"
status: active
updated: 2026-10-13
reqPrefix: BSC-EDIT
relations:
  specifiedBy: [book-studio-core-ux-declared-edits]
  implements:
    - book-studio-core:src/bookstudio/epub/edits.py
    - book-studio-core:src/bookstudio/epub/build.py
  dependsOn: [book-studio-core-logic-translation-pipeline]
---

# Book Studio Core — Declared edits (logic)

## Purpose

- Problem: editorial fixes made after the build (wording, a contents page, CSS, a private-reading cover mark) were
  applied by per-book scripts after `finish`. The delivered EPUB was then never the one the gate certified.
- Success signal: the SHA-256 in `reports/release.json` equals the delivered `output/final.epub`, including every
  post-build correction, and two builds stay byte-identical.

## Rules

Status column: `live`, `not built`, or `blocked`. A live rule has its REQ-ID as a one-line `# BSC-…` comment next to
the test named in Evidence.

| REQ-ID       | Rule (behaviour-changing)                                                                                                                                                                                             | Status | Evidence (code path or test)                                                    |
| ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ | ------------------------------------------------------------------------------- |
| BSC-EDIT-001 | `PROJECT/edits.json` operations run inside `build`, in order, before the file is published. `finish`, `verify` and `reports/release.json` therefore certify the edited book; the receipt records the operation count and the edits file SHA-256. | live   | `tests/test_edits.py` (`test_finish_certifies_the_edited_book`)                 |
| BSC-EDIT-002 | Without `edits.json`, the build is byte-identical to a build made before this feature existed (`edits.applied` = 0).                                                                                                    | live   | `tests/test_edits.py` (`test_without_edits_file_build_is_unchanged`)            |
| BSC-EDIT-003 | `replace_text` must match exactly `count` times, or the build fails and writes no output.                                                                                                                            | live   | `tests/test_edits.py` (`test_text_count_mismatch_fails_closed`)                 |
| BSC-EDIT-004 | `replace_member` fails when the built member no longer matches `base_sha256`. A changed translation can never be silently overwritten by an old replacement.                                                         | live   | `tests/test_edits.py` (`test_stale_member_base_fails_closed`)                   |
| BSC-EDIT-005 | `replace_member` and `add_member` read only regular, non-symlink files inside the project whose SHA-256 matches the declared `sha256`.                                                                                  | live   | `tests/test_edits.py` (`test_asset_hash_and_location_are_pinned`)               |
| BSC-EDIT-006 | An edited or added markup member must be well-formed and contain no `script`, no `on*` attribute and no `javascript:` link.                                                                                              | live   | `tests/test_edits.py` (`test_unsafe_markup_is_rejected`)                        |
| BSC-EDIT-007 | Only `replace_text`, `replace_member` and `add_member` exist, plus an optional `note`. Unsafe member paths, adding an existing member, and editing a missing member each fail with a stable code.                     | live   | `tests/test_edits.py` (`test_schema_and_member_rules`)                          |

## States and transitions

| State               | Trigger                          | Next state            | Edge case                                                       |
| ------------------- | -------------------------------- | --------------------- | --------------------------------------------------------------- |
| no edits            | `build` / `finish`               | plain core output     | identical bytes to earlier releases                             |
| edits declared      | `build` / `finish`               | edited, certified     | all integrity checks in `verify` still apply to the edited book |
| edits declared      | translation or core output changes | build fails `EDITS_BASE_STALE` / `EDITS_TEXT_COUNT_MISMATCH` | refresh the replacement and its hashes |

## Fixed vs flexible

- Fixed: edits are applied inside the gate, pinned by hashes, never applied to the source EPUB, and cannot delete
  members. Source images stay byte-identical, so a cover mark is added as a new member (`verify` still checks this).
- Flexible: how a project produces its replacement files (by hand, an editor, or a tool such as a cover-mark script).

## Open questions

- Should the core offer a `capture` helper that writes `edits.json` from an EPUB edited elsewhere? The Zero to One
  migration used a scratch script for this.

## Change log

- 2026-10-13: created with BSC-EDIT-001…007. Proven on a private copy of a real book: 14 operations, the gate hash
  equals `final.epub`, every member is byte-identical to the previously delivered edition, and a second `finish`
  produces the same hash.

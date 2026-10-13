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
| BSC-EDIT-008 | `bookstudio edits capture PROJECT --from EDITED.epub` expresses an edited EPUB as `edits.json` plus `assets/edits/` against the plain core build; the next `finish` reproduces the edited book member for member. | live   | `tests/test_edits.py` (`test_capture_turns_an_edited_epub_into_certified_edits`) |
| BSC-EDIT-009 | Capture writes nothing for an unchanged book (`no_changes`), refuses deletions (`EDITS_CAPTURE_DELETION`), and never overwrites an existing `edits.json` (`EDITS_ALREADY_DECLARED`). | live   | `tests/test_edits.py` (`test_capture_refuses_deletions_existing_edits_and_no_change`) |
| BSC-EDIT-010 | A member is checked as markup when its name has a markup suffix or when the edited OPF gives it a markup media-type, so renaming cannot skip the check. Active elements (script, iframe, object, embed, form, `meta http-equiv`, SVG animation, foreignObject) are rejected, as are `on*` and `srcdoc` attributes and active styles. Links allow only relative, http(s) and mailto targets; resources must be files inside the book. | live   | `tests/test_edits.py` (`test_markup_check_follows_manifest_media_type_and_blocks_active_content`) |
| BSC-EDIT-011 | Before writing anything, capture refuses destinations under a symlinked folder, names that collide after case folding or Unicode normalisation, file-versus-folder clashes, and names with `:`, Windows reserved names or a trailing dot or space. On refusal nothing is written. | live   | `tests/test_edits.py` (`test_capture_never_writes_through_symlinks_or_colliding_names`) |

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

- None.

## Change log

- 2026-10-13: hardened after a security review (BSC-EDIT-010…011). All four real migrated books still rebuild to their certified hashes.
- 2026-10-13: added `edits capture` (BSC-EDIT-008…009), replacing the scratch migration script.
- 2026-10-13: created with BSC-EDIT-001…007. Proven on a private copy of a real book: 14 operations, the gate hash
  equals `final.epub`, every member is byte-identical to the previously delivered edition, and a second `finish`
  produces the same hash.

---
id: book-studio-core-logic-translation-pipeline
type: logic
product: book-studio-core
title: "Book Studio Core — Translation pipeline (logic)"
status: active
updated: 2026-10-11
reqPrefix: BSC-PIPE
relations:
  specifiedBy: [book-studio-core-ux-translation-pipeline]
  implements:
    - book-studio-core:src/bookstudio/epub/archive.py
    - book-studio-core:src/bookstudio/epub/inspect.py
    - book-studio-core:src/bookstudio/epub/extract.py
    - book-studio-core:src/bookstudio/translation/packets.py
    - book-studio-core:src/bookstudio/translation/cache.py
    - book-studio-core:src/bookstudio/translation/coverage.py
    - book-studio-core:src/bookstudio/safety/xhtml.py
    - book-studio-core:src/bookstudio/images/manifest.py
    - book-studio-core:src/bookstudio/epub/build.py
    - book-studio-core:src/bookstudio/epub/validate.py
---

# Book Studio Core — Translation pipeline (logic)

## Purpose

- Move a book from source EPUB to translated EPUB through untrusted AI output, so that every accepted line is tied to
  an exact source block and editorial context, and nothing unsafe or incomplete reaches `output/final.epub`.
- Success signal: two builds from the same inputs are byte-identical, and every failure leaves the source, cache and
  previous final output exactly as they were.

## Rules

Status column: `live`, `not built`, or `blocked`. A live rule has its REQ-ID as a one-line `# BSC-…` comment next to
the test named in Evidence (all evidence lives in `tests/`, so the generated plugin bundle stays byte-identical).

| REQ-ID       | Rule (behaviour-changing)                                                                                                                                                                                            | Status | Evidence (code path or test)                                                                                                                                      |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| BSC-PIPE-001 | Archive preflight reads ZIP metadata first and rejects parent-traversal, absolute and backslash member paths (`ARCHIVE_UNSAFE_PATH`); nothing is extracted and the source bytes are unchanged.                       | live   | `tests/test_archive_safety.py` (`test_preflight_rejects_parent_traversal`, `test_preflight_rejects_absolute_and_backslash_paths`)                                   |
| BSC-PIPE-002 | Preflight rejects duplicate member names and archives over the entry-count, single-entry size, total expanded size or compression-ratio limits, each with its own stable error code.                                 | live   | `tests/test_archive_safety.py` (`test_preflight_rejects_duplicate_names`, `test_preflight_enforces_entry_count`, `…_expanded_bytes`, `…_compression_ratio`)       |
| BSC-PIPE-003 | Inspection and block extraction are deterministic: the same source gives an identical block map with a hash per block and the whole-file SHA-256, and no receipt contains the local source path.                     | live   | `tests/test_epub_pipeline.py` (`test_inspect_measures_structure_without_absolute_source_path`, `test_extract_uses_stable_source_hashes_and_canonical_nesting`)     |
| BSC-PIPE-004 | An EPUB without a container fails with `EPUB_CONTAINER_MISSING` and the source file is not modified.                                                                                                                | live   | `tests/test_epub_pipeline.py` (`test_inspect_rejects_missing_container_without_mutating_source`)                                                                  |
| BSC-PIPE-005 | One packet holds blocks from only one source document and never more than `max_blocks`.                                                                                                                             | live   | `tests/test_packets.py` (`test_next_packet_never_crosses_source_document_or_max_blocks`)                                                                          |
| BSC-PIPE-006 | A packet carries the book profile, only glossary terms matched to its blocks, reference notes for its own document, neighbouring context marked `translate: false`, a block hash per target and the response schema; no local path. | live   | `tests/test_packets.py` (`test_packet_contains_bounded_context_glossary_reference_and_schema`)                                                                    |
| BSC-PIPE-007 | The packet ID is a stable 64-hex value bound to scope; a response applied under a different scope identity fails `RESPONSE_PACKET_STALE`.                                                                            | live   | `tests/test_packets.py` (`test_packet_id_is_stable_and_guided_packet_id_binds_scope`, `test_apply_rechecks_the_identical_target_scope_and_identity`)              |
| BSC-PIPE-008 | When `bookstudio.toml` changes after it was loaded, `next` and `apply` fail with `CONFIG_STALE` and no cache is written; a fresh load emits a new packet ID.                                                         | live   | `tests/test_packets.py` (`test_stale_loaded_config_cannot_emit_or_apply_a_mixed_snapshot`)                                                                         |
| BSC-PIPE-009 | AI-authored inline XHTML allows only a small inline tag set; scripts, event handlers, inline style, `javascript:` or remote URLs and embedded images fail `XHTML_UNSAFE`, malformed markup fails `XHTML_INVALID`, before any cache write. | live   | `tests/test_xhtml_safety.py` (`test_script_event_style_and_unsafe_url_fail_closed`, `test_malformed_markup_fails_closed`, `test_apply_validates_xhtml_before_cache_mutation`) |
| BSC-PIPE-010 | `apply` is append-only: a different translation for a row already in cache fails `CACHE_COLLISION` with the cache bytes unchanged; replaying the same response applies 0 rows.                                      | live   | `tests/test_packets.py` (`test_valid_apply_merges_and_collision_fails_closed`, `test_legacy_unscoped_response_replay_remains_idempotent`)                         |
| BSC-PIPE-011 | A cache row stripped of its packet ID and context hash is invalid (`CACHE_ROW_INVALID`), never trusted as a legacy row, and the cache is not rewritten.                                                              | live   | `tests/test_packets.py` (`test_cache_rows_cannot_downgrade_by_removing_context_identity`)                                                                         |
| BSC-PIPE-012 | While blocks remain, `status` exits 2 with `PROJECT_INCOMPLETE`; once all are translated, `next` exits 3 with `NO_WORK_REMAINS` and `status` exits 0.                                                               | live   | `tests/test_packets.py` (`test_coverage_and_no_work_exit_contract`)                                                                                               |
| BSC-PIPE-013 | Two builds from the same inputs are byte-identical: `mimetype` first and stored, fixed timestamps, original images copied byte for byte.                                                                            | live   | `tests/test_epub_pipeline.py` (`test_two_builds_are_byte_identical_and_self_identified`)                                                                          |
| BSC-PIPE-014 | A target-only build keeps anchor IDs and pagebreak markers and localises document titles and EPUB 3 / NCX navigation labels; a bilingual build keeps the source titles and marks source and translation blocks.       | live   | `tests/test_epub_pipeline.py` (`test_target_only_build_preserves_nested_anchor_and_pagebreak_markers`, `…_localizes_document_titles_and_navigation_labels`, `test_bilingual_build_marks_source_and_translation_blocks`) |
| BSC-PIPE-015 | `finish` refuses a candidate that fails independent integrity checks (for example a link to a missing fragment: `INTEGRITY_FAILED`) and leaves the previous `output/final.epub` untouched.                           | live   | `tests/test_epub_pipeline.py` (`test_broken_fragment_fails_and_finish_preserves_previous_final`)                                                                  |
| BSC-PIPE-016 | A localized image companion must live inside the project (`IMAGE_COMPANION_OUTSIDE_PROJECT`) and match the original image's pixel canvas exactly (`IMAGE_CANVAS_MISMATCH`).                                         | live   | `tests/test_epub_pipeline.py` (`test_companion_must_be_project_owned_and_match_source_canvas`)                                                                    |

## States and transitions

| State                 | Trigger                                  | Next state            | Edge case                                                                  |
| --------------------- | ---------------------------------------- | --------------------- | -------------------------------------------------------------------------- |
| source EPUB           | `inspect` / `prepare`                    | block map + coverage  | unsafe archive or missing container: stop, source unchanged                |
| block map             | `next`                                   | packet emitted        | no eligible block: exit 3 `NO_WORK_REMAINS`                                |
| packet emitted        | `apply RESPONSE`                         | rows in cache         | stale packet, unsafe XHTML, collision: error, cache unchanged              |
| cache incomplete      | `status`                                 | exit 2                | invalid cache row fails before counts are reported                         |
| cache complete        | `build` / `finish`                       | candidate EPUB        | integrity or reproducibility failure: previous `final.epub` kept           |
| candidate passes      | `finish`                                 | `output/final.epub`   |                                                                            |

## Fixed vs flexible

- Fixed (logic no caller may change): the source is read-only; every write is atomic; AI output is untrusted until
  validated; a failure never mutates the cache or the previous final output; packets and receipts never contain local
  paths; builds are deterministic.
- Flexible: how an agent phrases prompts, which model it uses, packet size within `max_blocks`, and the visual styling
  of image annotations and companions.

## Open questions

- None recorded.

## Change log

- 2026-10-11: created; REQ-IDs added as one-line `# BSC-PIPE-…` comments next to the tests in the same commit.

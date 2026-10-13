---
id: book-studio-core-logic-portable-skill
type: logic
product: book-studio-core
title: "Book Studio Core — Portable skill and Codex plugin (logic)"
status: active
updated: 2026-10-13
reqPrefix: BSC-SKILL
relations:
  specifiedBy: [book-studio-core-ux-portable-skill]
  implements:
    - book-studio-core:scripts/build_plugin.py
    - book-studio-core:skills/book-translation/scripts/install.py
    - book-studio-core:plugins/book-studio
  dependsOn: [book-studio-core-logic-guided-pilot]
---

# Book Studio Core — Portable skill and Codex plugin (logic)

## Purpose

- Ship the same engine and the same `book-translation` skill to an AI agent in two forms - an installable Codex plugin
  with a bundled engine, and a standalone skill folder - without either form drifting from the canonical sources or
  leaving a half-installed skill behind.
- Success signal: the bundle check is green in CI, and a failed install or update always leaves the previous install
  in place.

## Rules

Status column: `live`, `not built`, or `blocked`. A live rule has its REQ-ID as a one-line `# BSC-…` comment next to
the test named in Evidence.

| REQ-ID        | Rule (behaviour-changing)                                                                                                                                                         | Status | Evidence (code path or test)                                                                       |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ | -------------------------------------------------------------------------------------------------- |
| BSC-SKILL-001 | The plugin bundle is generated from `src/bookstudio` and `skills/book-translation`; `scripts/build_plugin.py --check` exits 0 only when every bundled byte matches those sources. | live   | `tests/test_plugin.py` (`test_generated_bundle_matches_canonical_sources`)                         |
| BSC-SKILL-002 | `--check` on a modified bundle exits 1 and does not repair or rewrite it.                                                                                                         | live   | `tests/test_plugin.py` (`test_check_rejects_modified_bundle_without_repairing_it`)                 |
| BSC-SKILL-003 | A copy of the plugin runs `doctor` and the full guided pilot flow through its own runner in isolated Python, with no `PYTHONPATH` and no pip install.                            | live   | `tests/test_plugin.py` (`test_standalone_bundle_runs_complete_guided_flow`)                        |
| BSC-SKILL-004 | The skill installer installs to `$CODEX_HOME/skills/book-translation` with an exact tree match, and `--check` then reports `current`.                                              | live   | `tests/test_skill_install.py` (`test_default_codex_home_install_and_current_check`)                |
| BSC-SKILL-005 | `--check` with no install exits 2 with `missing` and creates nothing.                                                                                                             | live   | `tests/test_skill_install.py` (`test_check_reports_missing_without_creating_destination`)          |
| BSC-SKILL-006 | `--dry-run` over a stale install reports `would_update`, changes nothing and makes no backup.                                                                                     | live   | `tests/test_skill_install.py` (`test_dry_run_reports_stale_without_mutating_or_backing_up`)        |
| BSC-SKILL-007 | An update moves the previous install to a timestamped backup and replaces the destination with an exact copy of the source.                                                       | live   | `tests/test_skill_install.py` (`test_update_keeps_backup_and_replaces_destination_exactly`)        |
| BSC-SKILL-008 | If verification after an update fails, the previous install is restored and no backup or staging folder is left behind.                                                          | live   | `tests/test_skill_install.py` (`test_failed_post_install_verification_restores_previous_install`)  |
| BSC-SKILL-009 | An invalid skill source (a required file missing, a broken reference link) never creates the destination.                                                                         | live   | `tests/test_skill_install.py` (`test_invalid_source_never_creates_destination`)                    |
| BSC-SKILL-010 | The plugin manifest follows the Codex `plugin.json` spec: `skills` is a `./` path, `interface.defaultPrompt` is a list of 1-3 prompts of at most 128 characters, and `keywords` is set. | live   | `tests/test_plugin.py` (`test_manifest_follows_codex_plugin_spec`)                                 |

## States and transitions

| State              | Trigger                    | Next state          | Edge case                                                    |
| ------------------ | -------------------------- | ------------------- | ------------------------------------------------------------ |
| not installed      | `install.py --check`       | not installed (exit 2) | destination not created                                   |
| not installed      | `install.py`               | installed (current) | invalid source: nothing created                              |
| installed (stale)  | `install.py --dry-run`     | installed (stale)   | reports `would_update`; no backup                            |
| installed (stale)  | `install.py`               | installed (current) | verification failure: previous install restored              |
| bundle             | source edit                | bundle drift        | `build_plugin.py --check` fails in CI until regenerated      |

## Fixed vs flexible

- Fixed: the bundle is generated, never hand-edited; the skill bundles no AI provider, OCR engine, Poppler or renderer
  and never bypasses the CLI's safety gates; installs are atomic with a recoverable backup.
- Flexible: which agent loads the skill, and the wording of the skill's conversational guidance.

## Open questions

- None recorded.

## Change log

- 2026-10-11: created; REQ-IDs added as one-line `# BSC-SKILL-…` comments next to the tests in the same commit.

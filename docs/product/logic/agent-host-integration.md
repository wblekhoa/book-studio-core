---
id: book-studio-core-logic-agent-host-integration
type: logic
product: book-studio-core
title: "Book Studio Core — Agent-host integration (logic)"
status: active
updated: 2026-11-25
summary: "Rules for the plugin hooks and MCP server: a guard denies direct writes to gate-owned files inside projects, session start lists nearby projects, 14 MCP tools reuse the CLI dispatch with stable error codes, `bookstudio install` wires other AI hosts, and Windows I/O is UTF-8 with LF."
tags: [area/ai, area/security, stack/python, surface/cli]
reqPrefix: [BSC-HOOK, BSC-MCP, BSC-HOST, BSC-WIN]
relations:
  specifiedBy: [book-studio-core-ux-agent-host-integration]
  implements:
    - book-studio-core:src/bookstudio/hooks.py
    - book-studio-core:src/bookstudio/mcp_server.py
    - book-studio-core:src/bookstudio/install.py
    - book-studio-core:plugins/book-studio
  dependsOn: [book-studio-core-logic-portable-skill, book-studio-core-logic-declared-edits, book-studio-core-logic-review-page]
---

# Book Studio Core — Agent-host integration (logic)

## Purpose

- Problem: the gates live in the CLI, but an agent can still write the certified EPUB, its receipt or the cache
  directly, and every host had to rediscover project state. Claude users had no plugin at all.
- Success signal: one plugin folder installs in both Claude Code and Codex. Direct writes to gate-owned files are
  refused before they happen, and structured tools return the same results as the CLI.

## Rules

Status column: `live`, `not built`, or `blocked`. A live rule has its REQ-ID as a one-line `# BSC-…` comment next to
the test named in Evidence.

| REQ-ID       | Rule (behaviour-changing)                                                                                                                                                                              | Status | Evidence (code path or test)                                                              |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------ | ----------------------------------------------------------------------------------------- |
| BSC-HOOK-001 | The PreToolUse guard denies Write/Edit/MultiEdit/NotebookEdit on `output/final.epub`, `reports/release.json` and `cache/translations.json`, but only inside a folder that has `.bookstudio-project`. Other files and other repositories pass. | live   | `tests/test_hooks.py` (`test_guard_blocks_direct_writes_to_gate_owned_files_only_inside_projects`) |
| BSC-HOOK-002 | The guard denies shell writes that resolve to those files: redirection, `cp`/`mv`/`rsync`/`install`/`ln` into them, `rm`/`zip`/`tee`/`truncate`/`dd`/`shred`, `sed -i`, inline Python writes. Reads and copies out (delivery) pass. This is a heuristic, not a sandbox. | live   | `tests/test_hooks.py` (`test_guard_blocks_shell_writes_but_allows_reads_and_copies_out`)  |
| BSC-HOOK-003 | Hooks never break the host: malformed or empty input exits 0 with no output.                                                                                                                         | live   | `tests/test_hooks.py` (`test_hooks_never_break_the_host_on_bad_input`)                    |
| BSC-HOOK-004 | At session start, nearby projects are listed read-only, with stage, progress and the exact next command: the current folder, its children, `projects/*`, and the optional `projects_dir` user setting. | live   | `tests/test_hooks.py` (`test_session_note_lists_nearby_projects_with_next_command`)        |
| BSC-MCP-001  | `bookstudio mcp` speaks newline-delimited JSON-RPC: it negotiates a supported protocol version and lists 14 tools plus the optional MCP Apps review view (`ui://book-studio/chat-review-v1.html`, `text/html;profile=mcp-app`). | live   | `tests/test_mcp.py` (`test_protocol_surface_lists_tools_and_the_review_app`)               |
| BSC-MCP-002  | MCP tools run the CLI dispatch or the same engine function (`review`), so they have the same gates and files. A pilot is accepted only with `user_confirmed: true`. The review result carries a bounded `view` for the panel, not the HTML page, and keeps the view out of the model-visible text. | live   | `tests/test_mcp.py` (`test_guided_flow_through_tools_with_confirmation_gate`)              |
| BSC-MCP-003  | Every failure is a tool result with `isError: true` and a stable code. stdout carries only JSON-RPC lines.                                                                                            | live   | `tests/test_mcp.py` (`test_errors_are_tool_results_with_stable_codes`)                     |
| BSC-MCP-004  | `pilot` with `action: revise` and `response_path` replaces sample rows before acceptance, through the same gate as `bookstudio pilot revise`; without `response_path` it fails with `MCP_ARGUMENT_INVALID`. | live   | `tests/test_mcp.py` (`test_sample_can_be_revised_through_mcp_alone`) |
| BSC-MCP-005  | `pdf_inspect` and `pdf_prepare` run the PDF gateway; `source_language` is optional and never defaulted; failures are tool errors and write no output. | live   | `tests/test_mcp.py` (`test_pdf_tools_are_listed_and_return_stable_errors`) |
| BSC-HOST-001 | `bookstudio install --host cursor\|antigravity\|kimi\|opencode` copies the hash-checked engine to a per-user folder (`~/.book-studio/engine/<version>`, Windows `%LOCALAPPDATA%\\BookStudio\\engine\\<version>`), the skill to the host's skills folder with absolute run commands, and one `book-studio` MCP entry (absolute Python, runner, `PLUGIN_ROOT`) into the host config. Other entries and fields are kept; the old file is backed up first. | live   | `tests/test_install.py` (`test_each_host_gets_engine_skill_and_one_mcp_entry_and_keeps_the_rest`) |
| BSC-HOST-002 | A rerun with nothing to change writes nothing and makes no backup; an entry Book Studio wrote earlier (other version or Python) is replaced. | live   | `tests/test_install.py` (`test_rerun_changes_nothing_and_makes_no_backup`, `test_new_python_or_version_replaces_our_own_entry`) |
| BSC-HOST-003 | `bookstudio uninstall --host …` removes only the `book-studio` entry (after a backup) and a skill folder that carries the install marker; the engine folder stays. | live   | `tests/test_install.py` (`test_uninstall_restores_the_config_and_removes_only_our_skill`) |
| BSC-HOST-004 | Install refuses, writing nothing, on malformed JSON, a non-object config or server map, a skill folder it did not create, someone else's `book-studio` entry, or an OpenCode `opencode.jsonc`. A UTF-8 BOM or empty file is read; a symlinked config is written through to its target. | live   | `tests/test_install.py` (`test_unsafe_configs_and_folders_are_refused_untouched`, `test_bom_and_empty_configs_are_read_and_symlinks_survive`) |
| BSC-HOST-005 | `--dry-run` reports the same plan and writes nothing. | live   | `tests/test_install.py` (`test_dry_run_writes_nothing`) |
| BSC-HOST-006 | The written entry starts a working MCP server that lists its tools and refuses project paths inside the engine folder. | live   | `tests/test_install.py` (`test_the_installed_entry_starts_a_working_server_that_guards_its_folder`) |
| BSC-WIN-001  | MCP stdio is UTF-8 with LF line endings whatever the console code page; CLI output is reconfigured to UTF-8. | live   | `tests/test_mcp.py` (`test_stdio_frames_are_utf8_and_lf_whatever_the_locale`) |
| BSC-WIN-002  | On Windows the engine lives under `%LOCALAPPDATA%` (fallback `~\\AppData\\Local`). | live   | `tests/test_install.py` (`test_windows_engine_lives_in_local_app_data`) |
| BSC-WIN-003  | A production brief saved with CRLF binds the same packet identity as LF. | live   | `tests/test_packets.py` (`test_crlf_production_brief_binds_the_same_packet_as_lf`) |

## States and transitions

| Event                         | Inside a project                      | Outside any project |
| ----------------------------- | ------------------------------------- | ------------------- |
| Write to `output/final.epub`  | denied with the `edits.json` route    | allowed             |
| `cp output/final.epub ~/Books/` | allowed (copy out)                  | allowed             |
| Session start                 | status lines for up to 8 projects     | silent              |

## Fixed vs flexible

- Fixed: hooks and MCP tools add no gates of their own beyond the CLI's, except refusing direct writes to gate-owned
  files. They never change project state on their own.
- Flexible: tool descriptions, the agents' and commands' wording, and the MCP Apps view (experimental: rendering
  depends on the host).

## Open questions

- Do Cursor, Antigravity and Kimi Code load the installed entry in their desktop apps? The entry was started from each real config on macOS; the apps were not opened.
- Does Claude desktop render the MCP Apps review view from a plugin server? Not verified. The text result works
  everywhere.

## Change log

- 2026-11-25: BSC-MCP-004…005 (revise and PDF tools over MCP); `/book-studio:start` job menu.
- 2026-11-24: BSC-HOST-001…006 and BSC-WIN-001…003 (other AI hosts, Windows I/O). Windows CI result pending a pushed branch.
- 2026-11-02: BSC-MCP-002 updated for 0.4.0 (review returns a bounded view, no HTML page).
- 2026-10-13: created with BSC-HOOK-001…004 and BSC-MCP-001…003.

- 2026-10-24: chat-first projections and read-only `view`; detailed rules and verification limits in `chat-workflow.md`.

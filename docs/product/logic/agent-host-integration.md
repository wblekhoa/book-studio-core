---
id: book-studio-core-logic-agent-host-integration
type: logic
product: book-studio-core
title: "Book Studio Core — Agent-host integration (logic)"
status: active
updated: 2026-10-13
summary: "Rules for the plugin hooks and MCP server: a guard denies direct writes to gate-owned files inside projects, session start lists nearby projects, and 11 MCP tools reuse the CLI dispatch with stable error codes."
tags: [area/ai, area/security, stack/python, surface/cli]
reqPrefix: [BSC-HOOK, BSC-MCP]
relations:
  specifiedBy: [book-studio-core-ux-agent-host-integration]
  implements:
    - book-studio-core:src/bookstudio/hooks.py
    - book-studio-core:src/bookstudio/mcp_server.py
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
| BSC-MCP-001  | `bookstudio mcp` speaks newline-delimited JSON-RPC: it negotiates a supported protocol version and lists 11 tools plus the experimental MCP Apps review view (`ui://book-studio/review.html`, `text/html;profile=mcp-app`). | live   | `tests/test_mcp.py` (`test_protocol_surface_lists_tools_and_the_review_app`)               |
| BSC-MCP-002  | MCP tools run the CLI dispatch, so they have the same gates and files. A pilot is accepted only with `user_confirmed: true`. The review result carries the page for the view, but not in the model-visible text. | live   | `tests/test_mcp.py` (`test_guided_flow_through_tools_with_confirmation_gate`)              |
| BSC-MCP-003  | Every failure is a tool result with `isError: true` and a stable code. stdout carries only JSON-RPC lines.                                                                                            | live   | `tests/test_mcp.py` (`test_errors_are_tool_results_with_stable_codes`)                     |

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

- Does Claude desktop render the MCP Apps review view from a plugin server? Not verified. The text result works
  everywhere.

## Change log

- 2026-10-13: created with BSC-HOOK-001…004 and BSC-MCP-001…003.

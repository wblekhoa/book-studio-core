---
id: book-studio-core-logic-chat-workflow
type: logic
product: book-studio-core
title: "Book Studio Core — Chat workflow rules"
status: active
updated: 2026-11-02
summary: "Source-grounded intake, consistent read-only chat snapshots, conversational approval and pause semantics, optional host adapters, and narrow public-source exceptions for the owned Mods code."
tags: [area/book, area/translation, area/ai, area/security, stack/python, surface/cli, surface/web]
reqPrefix: BSC-CHAT
relations:
  specifiedBy: [book-studio-core-ux-chat-workflow]
  implements: [book-studio-core:src/bookstudio/intake.py, book-studio-core:src/bookstudio/review.py, book-studio-core:src/bookstudio/mcp_server.py, book-studio-core:plugins/book-studio]
  dependsOn: [book-studio-core-logic-guided-pilot, book-studio-core-logic-agent-host-integration]
---
# Chat workflow rules

| REQ-ID | Rule | Status | Evidence |
|---|---|---|---|
| BSC-CHAT-001 | Initial assessment returns untrusted excerpts from at most three source documents, at most three blocks each and 800 characters per block, without accepting preferences, modifying the source or creating an incomplete project. | live | `tests/test_intake.py::test_assessment_supplies_bounded_untrusted_source_context_before_asking` |
| BSC-CHAT-002 | MCP `view` reads current source/cache-aligned progress and sample without writing project files. It retries up to three times if watched files change, then reports `REVIEW_BUSY`. Invalid cache is an error, never fake zero progress. UI payloads show at most 12 sample pairs (800/1000 source/target characters) and 20 chapter rows with truncation disclosed. | live | `tests/test_mcp.py::test_view_reads_live_sample_and_progress_without_writing_project_files`, `test_view_retries_when_cache_changes_while_reading`; `tests/test_review.py::test_snapshot_reports_review_busy_when_the_project_keeps_changing` |
| BSC-CHAT-003 | Agent inspects `source_preview`, separates facts/recommendations/accepted choices, omits already answered questions, and presents short samples and approval choices in chat without requiring a browser. Existing pilot and editing gates remain authoritative. | live | `tests/test_skill_contract.py::test_chat_workflow_covers_source_evidence_review_and_conversational_pause`; independent skill pressure scenarios |
| BSC-CHAT-004 | Conversational pause stops new packet/apply operations, retains successful atomic work and acknowledges actual saved counts. Continue rechecks state and does not imply pilot acceptance or background execution. There is no new pause CLI command or lifecycle receipt. | live | Same contract test and pressure scenarios; existing pilot tests prove the engine gate |
| BSC-CHAT-005 | Native Mods and MCP Apps views are read-only presentation adapters. Refresh failures are visible; project identity and update revisions bind requests and discard stale responses; tool observation preserves the original result. | live | `plugins/book-studio/evals/chat-view.test.ts` (five official-runner tests); browser bridge probes; actual Codex MCP Apps DOM/screenshots show the same tab polling 0/8 to 4/8 without another review. |
| BSC-CHAT-006 | Portable plugin metadata declares local execution and a bundled stdio server using the plugin-root placeholder, without Claude-specific configuration variables. Existing Claude wiring and source/cache/final guards are preserved. | live | `tests/test_plugin.py::test_portable_plugin_starts_its_local_tools_without_claude_placeholders`; clean-copy runner tests. This is packaging evidence, not a public-directory or desktop UI claim. |
| BSC-CHAT-007 | Public audit allows JavaScript/TypeScript only at the exact owned Mods source/test paths; those files still undergo text privacy/secret scanning. Other scripts remain rejected. | live | `tests/test_public_audit.py::test_only_owned_mod_source_and_its_test_have_script_exceptions` |
| BSC-CHAT-008 | MCP rejects private book/project paths inside the installed plugin, including relative paths when the server starts there, with `MCP_PRIVATE_PATH_REQUIRED`. Explicit private absolute paths and configured private workspaces remain supported. | live | `tests/test_mcp.py::test_installed_plugin_never_creates_private_books_in_its_installation`; installed Codex probe |
| BSC-CHAT-009 | The checkout installer preflights Python, Codex and bundle integrity before registration, uses official plugin commands, compares the installed copy and exercises its actual stdio tool transport. Dry-run makes no Codex changes. Failed checks never report installation success or overwrite private books. | live | `tests/test_plugin.py::CodexInstallTests`; local Codex installation receipt |
| BSC-CHAT-010 | `review` declares the standard UI resource plus OpenAI's explicit fullscreen presentation preference, allowing Codex to open a reachable in-host view. Polling `view` stays data-only and cannot reopen the panel. Generic hosts retain the standard resource contract. | live | `tests/test_mcp.py::test_review_declares_explicit_host_presentation_for_the_local_app`; actual Codex desktop panel/sample/polling proof |
| BSC-CHAT-011 | MCP `review` reads one project snapshot for both the saved page and the bounded `view`, and does not embed the HTML page in its result. | live | `tests/test_review.py` (`test_mcp_review_reads_one_snapshot_and_omits_the_html_page`); `tests/test_mcp.py` (`test_guided_flow_through_tools_with_confirmation_gate`) |

## Seams

- Existing `start` CLI and `assess_intake`: bounded source evidence; cannot prove the AI's semantic judgment.
- MCP `view`: read-only status/sample tied to validated project state; cannot prove a host rendered it.
- MCP Apps bridge: plain-text rendering, tool polling and selection identity; browser evidence is separate from host support.
- Claude Mods event/render seam: official runner proves event/presentation behaviour without model, auth or network.

## Fixed decisions

No new AI provider, Python dependency, browser requirement, standalone app, background job, automatic approval or
parallel source of project truth. The optional view is a projection; files owned by the existing engine remain canon.

## Open verification

Local installation and the real Codex chat MCP flow have passed through source assessment, sample application,
read-only review and refusal to continue without approval. A newly created Codex desktop chat after the update
called the installed MCP tools successfully, recovered 4/8 passages at the same approval gate and preserved all
14 project files and the source bytes. Later diagnosis found missing explicit host presentation metadata. With
that preference, Codex desktop runtime 0.164.0-alpha.11.1 exposed the real MCP Apps panel: screenshots and DOM
showed source/translation pairs and the same tab polling 0/8 to 4/8 after an atomic apply. The PATH CLI used
for installation was 0.154.0; it is not the desktop runtime version. Existing-thread reload and live Claude agent
evals remain unverified.
macOS/Linux are the existing supported platform scope. Do not report Windows or public directory availability
from these local checks.

## Change log

- 2026-11-02: BSC-CHAT-011; REVIEW_BUSY test added to BSC-CHAT-002.

---
id: book-studio-core-spec-2026-10-24-visual-workspace
type: spec
product: book-studio-core
title: "Book Studio Core — Visual workspace (spec)"
status: building
approvedBy: "Project owner (chat authorization)"
approvedAt: 2026-10-24
updated: 2026-11-02
summary: "Research Claude Code Mods and Codex UI for a chat-driven local book plugin with in-host sample and progress visuals; distinguish confirmed direction, documented capabilities, and outstanding live-host verification."
tags: [area/translation, area/book, area/ai, stack/python, surface/cli, surface/web]
# owner gate 1 — add both lines when the owner approves (required from 'approved' on):
#   approvedBy: <name>
#   approvedAt: <date of the approval>
figma: []
relations:
  changes: [book-studio-core-ux-chat-workflow, book-studio-core-logic-chat-workflow]
  # owner gate 2 — when shipped add:  releasedTo: [book-studio-core-releases @ <release id>]
---
# Book Studio Core — In-host visual workspace research

Research date: 2026-10-24. The research sections describe documented host capabilities, not a passed Book Studio
UI demo; the implementation checks that followed are recorded in order further down and are limited to the hosts
and builds named there.
The owner authorized autonomous implementation on this date. This does not certify untested desktop support.

## Outcome

A new reader installs the plugin, supplies a book in chat, receives content-informed advice, reviews a representative
sample, and follows actual progress inside the AI application. All decisions and requests are made in chat;
visuals support understanding and do not introduce a required dashboard. Translation and editing an existing edition need
appropriate workflows. The engine and book state remain local; model processing follows the selected host and
provider. This is not a claim that the AI works offline.

## Locked decisions and open choices

| Item | Status | Decision |
|---|---|---|
| Distribution | DECIDED | Plugin for Codex/Claude with local UI; no standalone product or hosted website in this iteration. |
| UI placement | DECIDED | Inside the host conversation; the earlier in-host-panel choice excludes an external browser. |
| Interaction | DECIDED | Latest clarification: chat only for requests, approvals, revisions and pause/continue instructions. Visual controls are not required. |
| Host mechanism | BUILT, EXPERIMENTAL | Claude Code Mods adapter (covered by `claude plugin test` only); Codex MCP Apps adapter (checked on one macOS Codex desktop build). |
| Initial operating systems | DECIDED | AI implementation default under autonomous authorization: retain macOS/Linux; no new Windows support claim. |
| Visual presentation | DECIDED | Reuse restrained book styling: compact progress and sample comparison, no required workflow controls. |

Implementation freedom: reuse existing engine contracts; choose small adapters after capability validation. Do
not introduce a second source of book state or a provider client merely to draw progress.

## Research: documented capabilities

### Claude Code

Mods are officially supported plugins with in-process event handlers. They can draw panes, buttons, inputs and
tabs, observe turns/tool calls, and run commands independently of an AI turn. UI runs in the CLI, Desktop Code
tab and supported VS Code extension versions, with surface differences. Headless/SDK sessions do not draw it.
Sources: [Mods overview](https://code.claude.com/docs/en/plugins/mods/overview),
[announcement, 2026-10-01](https://claude.com/resources/articles/claude-code-mods).

The UI API offers `ui.render`, `$.ui.open`, `$.ui.invalidate`, callbacks, and persistent plugin storage. Timers
and process/MCP access can refresh real engine status while a session is open. Calling `$.prompt.submit` can
request a turn; timers and visual updates alone do not translate a book. Source:
[Draw in the interface](https://code.claude.com/docs/en/plugins/mods/interface),
[Use the mods API](https://code.claude.com/docs/en/plugins/mods/api).

Recommended route: a thin native Mods UI over the existing engine, with user actions validated through engine
commands. Do not write canonical cache or final EPUB bytes from a UI callback. At research time Book Studio
shipped settings hooks and MCP tools, not a Mods module; the module `hooks/chat-view.js` was added afterwards.

For the latest chat-only interaction decision, a compact status or tool-result representation is sufficient;
do not add a permanent pane or approval buttons merely because Mods support them.

### Codex desktop

OpenAI documents plugin packaging, bundled local MCP servers and MCP Apps UI resources. The UI bridge supports
tool results, tool calls and messages. Many UI guide examples explicitly target ChatGPT, so they alone do not
establish every Codex surface's behaviour. The official desktop changelog also records embedded MCP app panels.
Sources: [Plugin UI](https://developers.openai.com/plugins/build/chatgpt-ui),
[desktop changelog](https://learn.chatgpt.com/docs/changelog).

Recommended candidate: an optional MCP Apps view over local Book Studio tools. Prove that a manually installed local
plugin mounts its resource in Codex desktop, refreshes status, and survives a thread reload.
Do not infer this from tool availability, a manifest, a returned HTML string, or a browser screenshot.
No officially documented equivalent to Claude's in-process Mods API was established in this research.

Codex app-server is for embedding the agent into a custom client; that is a different product route from adding
a panel to the installed desktop application. It is not the proposed implementation. Source:
[App Server](https://learn.chatgpt.com/docs/app-server).

### Distribution

Git/local marketplaces and official directory publication are different routes. OpenAI documents portable
plugin manifests and MCP configuration, while preserving the existing compatibility layout. Directory
submission for a local MCP plugin currently requires approved-partner eligibility. Do not promise directory
availability as an ordinary result of adding a Git marketplace. Sources:
[Package your plugin](https://developers.openai.com/plugins/build/plugins),
[Desktop-only submission](https://developers.openai.com/plugins/deploy/desktop-only).

## Research evidence before implementation

- Read-only probe: `codex --version` reports 0.154.0; `claude --version` reports 2.1.287.
- `codex features list` reports plugins/apps enabled and `enable_mcp_apps` under development and false in the CLI
  probe. This is not a reliable statement about every desktop-side renderer or hosted connector path.
- `src/bookstudio/mcp_server.py` already registers a `ui://` review resource and handles host tool-result events.
  Its current view inserts a static review snapshot; it has no interactive controls or status polling.
- `plugins/book-studio/hooks/hooks.json` had settings hooks and no Mods `modules` entry (at research time).
- Book Studio's current behavioural-eval record leaves the Claude live scenarios pending. Earlier clean-room
  install evidence does not establish that the requested interactive panel works.
- No live Mods pane or local Codex MCP Apps panel was installed or exercised during this research. Published
  Mods API references describe newer builds too; use the target build's generated declarations when implementing.

## Proposed product requirements

Implementation rules and test evidence now live in `../logic/chat-workflow.md`. Desktop-specific acceptance remains open.

| Proposed ID | User-visible requirement | Evidence required |
|---|---|---|
| BSC-VIS-001 | Installation checks prerequisites and leads to a usable chat workflow. | Fresh-profile installation on each claimed host/OS. |
| BSC-VIS-002 | AI inspects representative content, explains its recommendations, and asks only material missing choices. | Synthetic prose, technical and illustrated inputs; declared choices are not asked again. |
| BSC-VIS-003 | User can compare source/sample in the conversation and approve or request revision in chat. | Real chat instruction plus engine state transition; no self-approval by the AI. |
| BSC-VIS-004 | Chat and any optional visual show actual stage, completed/remaining work, current chapter and actionable errors. | Progress changes from engine state, without fabricated percentages or required page regeneration. |
| BSC-VIS-005 | Pause/continue requests have explicit pending/acknowledged states and preserve completed work. | Interrupt/restart test at a packet boundary; no claim of instantaneous model cancellation. |
| BSC-VIS-006 | The workspace reopens from durable local project state and identifies the certified output. | Close/reopen test; artifact matches its release receipt. |

## Execution route and verification

1. **Capability probe [ROUTE]**: use a synthetic project to prove an in-chat sample/progress view, one read-only
   status call, a chat-approved transition and an update/reload in each host. Record host version, evidence and limitations. Do not modify shared
   host settings or install dependencies without authorization.
2. **Interaction design [LOCKED]**: preserve chat-only interaction and in-host visual placement; confirm the
   visual direction and OS scope. Define content-informed intake and the editing branch before implementation.
3. **Implementation [ROUTE]**: share engine status/action contracts, with separate host renderers if needed. Use
   meaningful failing tests for new logic; update UX/logic docs and generated plugin from canonical sources.
4. **Verification [LOCKED]**: run the existing unit suite, public audit, bundle freshness and doc-index check;
   exercise actual chat approvals, visible state changes and restart. A green engine suite alone is insufficient.

## Constraints and escalation

Preserve source files, private projects, accepted translations, existing safety gates and unrelated work. Use
synthetic content in reusable tests and public UI evidence. No full-book run, paid API use, new dependency,
host-settings change, release or publication is included in this research.

If Codex cannot render a local plugin UI, report the exact host/version and failed step; preserve useful progress
and sample comparison through chat text, and do not claim a custom view ran or switch to an external browser.
Rich visual alternatives still need a product decision. Routine adapter
bugs can be fixed within the subsequently authorized scope.

## Done and stop conditions

Research and local adapter implementation are complete when their checks pass. End-user desktop verification is
complete only after the selected host/OS installation, chat interaction, progress and restart tests pass. A missing
live-host result stays UNKNOWN. Do not label this draft or its proposed requirements shipped.

## Report-back and next action

Report the documented Claude Mods route, the Codex MCP Apps candidate, the existing static-view gap, and the
distribution boundary. The bounded synthetic probes, local implementation and later Codex installation/chat test
are recorded below. Fresh-desktop-chat state recovery has now passed. Remaining acceptance covers custom desktop
rendering and authenticated Claude evaluation, without changing the chat-only product.

## Change log

- 2026-10-24: recorded owner direction and interaction choices; researched official host mechanisms and local versions.
- 2026-10-24: latest owner clarification makes chat the sole required interaction surface; visuals are supporting views.

## Implementation checkpoint before local installation

The owner authorized autonomous completion after the research. Canonical changes add source excerpts before intake
questions, a bounded read-only MCP `view`, a polling MCP Apps projection, a native Claude Mods progress projection,
portable local MCP packaging, and chat-only review/pause guidance. Existing guard hooks remain unchanged.

Red/green seams were exercised for intake, MCP view, package transport, the audit exceptions and the skill contract.
The official Mods runner covered terminal/desktop rendering, disconnect handling, switching from a finished book
and delayed responses from a previous book or an older revision of the same book. An independent review identified wrong-book and mixed-cache-revision
risks; regression tests cover the fixes.

Browser bridge evidence covers real synthetic engine progress from 0/8 to 4/8 without reload, 390px reflow,
reload restoring the saved snapshot, ignored forged child messages and ignored late previous-project replies.
This is a bridge harness, not a successful Codex or Claude desktop installation. Claude Code was not signed in on the test machine.
Live host rendering and live model evals remain UNKNOWN; do not silently turn them green.

At that earlier checkpoint the source remained unreleased and no installed user plugin or book project had been
changed. The subsequently authorized Codex installation and synthetic chat project are recorded separately below.
No real source book, remote repository or deployment was changed.

## Verification receipt (before local installation)

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests`: 269 tests passed.
- `claude plugin test plugins/book-studio`: five native Mods tests passed, including stale-poll regressions.
- `claude plugin validate plugins/book-studio --strict --json`: passed with no errors or warnings.
- `python3 scripts/build_plugin.py --check`: canonical bundle matches.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m bookstudio public-audit . --json`: passed.
- `doc-index.mjs --check --product book-studio-core`: zero errors/warnings.
- Browser bridge: real synthetic progress 0/8 to 4/8, read-only polling, sample display, reload, 390px reflow,
  forged-child-message rejection, old-project response rejection, same-project old-revision rejection, and
  refresh failure/recovery without resetting counts. No console errors in the checked flow.
- Skill pressure scenarios: content-informed questions and chat sample review; pause/ambiguous continue at a
  sample gate; standalone EPUB editing without invented Core state. Explicit Core/standalone completion routes.

Standards review found wrong-book/stale-response and mixed-cache risks; the fixes have regression evidence. Spec
review found a standalone-edit routing ambiguity; the guidance now distinguishes independent editing verification
from Core certification. Unverified desktop and model checks are not presented as passed.

## Codex installation and actual chat checkpoint

The owner explicitly authorized installing and testing the preview in Codex. The local marketplace snapshot was
refreshed through the official `codex plugin` commands. The checkout installer now checks the declared transport's
Python command, bundle integrity, the copied plugin files and the installed stdio tool list. Its dry-run does not
register or install anything. Existing installation data was backed up privately before the first refresh.

- Codex CLI 0.154.0: installation passed, 93 source files matched the cached copy, 12 tools were available.
- Actual Book Studio MCP calls in the existing Codex chat assessed a synthetic EPUB before preferences, returned
  bounded source excerpts and missing questions, and created a project using explicitly declared test settings.
- The agent applied four Vietnamese sample passages atomically. `review` and `view` returned 4/8 saved passages
  at `pilot_review_required`. No real reader's preferences or real book were used.
- `pilot accept` without confirmation returned `PILOT_CONFIRMATION_REQUIRED`; `next_packet` before acceptance
  returned `PILOT_REVIEW_REQUIRED`. No sample was self-approved and no full-book run was started.
- Installation exposed a real host-path issue: Codex starts a local MCP server in the installed plugin folder.
  The server now rejects private paths there with `MCP_PRIVATE_PATH_REQUIRED`, and the agent resolves absolute
  private workspace paths. Red/green regressions cover relative and absolute installation descendants.
- Updating the plugin during the active turn closed its old MCP transport. A fresh process from the installed
  copy recovered the same 4/8 progress, retained the approval gate, rejected an unsafe relative path, and confirmed
  the source SHA-256 was unchanged. This proves durable state and fresh transport, not a desktop-thread reload.
- Native Codex UI control returned a tool safety denial. The supported MCP Apps side-panel inventory was empty
  after `review`. Inline view mounting, visual progress and desktop reload remain UNKNOWN; no native-control
  workaround or external-browser product fallback was used.
- Independent installer review found interpreter mismatch and unexpected-JSON handling issues. Both have
  red/green regression tests. Partial install failures retain a structured receipt instead of reporting success.

The local source remains unreleased. Installation changed only the authorized Book Studio plugin snapshot and
marketplace registration. Claude live model evaluation still requires authentication. Public GitHub tags and
releases do not contain this preview until a separate approved publication.

Final local checks for this checkpoint: 276 Python tests passed, five official Mods tests passed, strict Claude
plugin validation passed with no warnings, canonical bundle parity passed, public-source audit passed, and
product doc-index reported zero errors/warnings. The checked installer itself passed dry-run and actual local
installation with 93 matching plugin files and 12 tools. These checks do not close the visual/Claude limits above.

## Fresh Codex desktop chat after update

The owner next explicitly requested a new Codex chat to verify the panel and continuation after updating.
A new local desktop chat was created and opened through the supported app tools. It invoked the installed
Book Studio MCP tools directly: `doctor`, `status`, `view`, `review`, `next_packet`, then `status` again.

Both status calls returned 4/8 saved passages and `pilot_review_required`; the source/target sample was read from
the actual view result. `next_packet` returned the expected `PILOT_REVIEW_REQUIRED`. No sample was approved,
no translation was repeated and no cached progress was lost. Independent before/after SHA-256 checks confirmed
all 14 project files and the source EPUB retained identical bytes; review could rewrite identical HTML bytes.

This closes new-chat connection and saved-state recovery after updating. It does not claim a full translation
resumed past an unapproved sample, or an existing desktop thread was reloaded. The supported MCP Apps backend
was available but exposed zero side-panel tabs before and after `review`. An inline-only visual cannot be
confirmed or disproved from this inventory. Native visual rendering, polling and reload remain UNKNOWN until
an actual host view is exposed for inspection; returned HTML alone is insufficient evidence.

The owner then confirmed expanding the Book Studio card. A second turn in the same new chat checked its own
MCP Apps backend again, including a fresh `view` call. The backend still exposed zero tabs. The owner's expansion
confirmation is recorded separately from tool observation: it does not establish rendered counts or polling,
and the empty inventory does not disprove an inline visual. DOM, screenshot and bridge polling checks remain
blocked by panel access, not marked as UI test failures. No native-control bypass or browser replacement was used.

## Actual panel diagnosis and visual verification

The owner authorized further diagnosis and completion of the Codex panel. The actual bundled desktop runtime
was 0.164.0-alpha.11.1; the PATH CLI used for earlier installation checks was 0.154.0. Protocol inspection of
the saved review item showed the correct resource URI but no explicit `mcpAppUi` display preference. OpenAI's
[app-server UI contract](https://github.com/openai/codex/blob/970111f6cb62cc02fe36a82ea7d71b37a2889c97/codex-rs/app-server/README.md#mcp-app-ui)
and matching generated types explain this distinction.

The narrow fix keeps `_meta.ui.resourceUri` and adds
`_meta['openai/ui'].preferredModelDisplayMode = 'fullscreen'` to `review`. Polling `view` stays data-only.
BSC-CHAT-010 failed before the change and passed after it. The bundle was regenerated and the installed copy
matched 93 source files with 12 tools. No approval, cache, source or provider contract changed.

A new desktop chat exposed actual Book Studio MCP Apps tabs through the supported CUA backend. DOM and viewport
JPEGs confirmed the saved 4/8 sample, chapter counts, source/translation pairs and pending approval. A separate
synthetic project then displayed 0/8; the agent prepared and applied its four-passage sample. The same panel
changed to 4/8 through five-second polling, with zero review calls after apply. After more than 21 seconds,
all four pairs were readable, including the expanded fourth pair, and no polling error appeared in the DOM.
The existing sample's protected files were preserved and neither sample was accepted.

A project-only UI feature flag was tested during diagnosis, then removed. A fresh-chat control without that
override still exposed the panel and showed an advancing Updated timestamp with stable 4/8 counts. This does
not establish the desktop's internal feature value; it establishes that no added project setting is required
for the tested route. No global configuration or permission setting was changed. The control's screenshot
attempts timed out; its evidence is DOM/inventory, separate from the successful actual-host JPEG captures above.

The full Python suite passed 277 tests at this checkpoint (before rebasing onto 0.3.1). Native Mods tests remain separate from actual Codex evidence.
The actual panel/sample/polling acceptance requested here is passed on this macOS desktop build. Existing-thread
reload, other native host builds/OS versions and authenticated Claude evaluation remain outside this proof.
Source remains unreleased and no commit/push/publication occurred.

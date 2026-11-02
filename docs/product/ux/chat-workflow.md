---
id: book-studio-core-ux-chat-workflow
type: ux
product: book-studio-core
title: "Book Studio Core — Chat workflow"
status: active
updated: 2026-10-24
summary: "Readers supply a book, discuss source-informed recommendations, review samples and pause or continue in chat; optional host visuals show actual progress without a required dashboard."
tags: [area/book, area/translation, area/ai, surface/cli, surface/web]
relations:
  specifies: [book-studio-core:src/bookstudio/intake.py, book-studio-core:src/bookstudio/mcp_server.py]
  dependsOn: [book-studio-core-logic-chat-workflow]
  sharesSurfaceWith: [book-studio-core-ux-agent-host-integration, book-studio-core-ux-guided-pilot]
---
# Chat workflow

## Reader experience

For a downloaded preview or source checkout, the reader can ask their AI to run
`python3 scripts/install_codex_plugin.py` from that folder. The installer checks
prerequisites, installs through Codex and verifies the cached server. After
installation or update, start a new chat and select Book Studio. Updating during
an active turn can close its old tool connection; saved book progress remains
in the private project and is reread in the new session.

Install the plugin, give the AI a book and describe the desired result. The agent reads bounded source evidence,
explains an editorial proposal, and asks only meaningful missing choices in the conversation. Translation language
is a user choice; it is not inferred from the conversation language. For an already translated book, editing scope
is agreed separately and existing wording is preserved unless changes are requested. Existing Core projects use
declared edits and the normal finishing gate. Standalone EPUB edits use a private deterministic transform and
independent verification; they are not presented as Core-certified translation projects.

The reader sees short source/target sample pairs and terminology/tone tradeoffs in chat. They reply naturally to
request changes or approve the reviewed sample. Full translation remains locked until explicit acceptance. The
reader never has to manipulate JSON, type engine commands, or open a browser.

Progress reports distinguish saved passages, remaining work, sample approval and final verification. A pause request
stops new work at an atomic operation boundary. The AI acknowledges the last confirmed saved counts and waits.
A later continue request rechecks current state; it never stands in for sample acceptance.

## Optional host visuals

- Claude Code Mods add two compact, read-only progress lines above the prompt, preserving the existing host drawing.
  After a Book Studio MCP call selects a project, the adapter refreshes engine state while the session is open.
- MCP Apps-compatible hosts receive a compact book view: title, stage, passage progress, chapter counts and bounded
  sample pairs. A first few pairs are visible, with additional pairs collapsible. No workflow buttons are required.
  `review` requests the in-host fullscreen presentation explicitly; the conversation remains the control surface.
- Book text is plain text in the view. Progress is read from current project state and stale responses for a previous
  selected book cannot replace the new book. A refresh failure labels the snapshot unavailable rather than inventing
  progress.
- If a host does not render custom UI, the conversation still provides status and sample comparisons. The agent
  must not claim an embedded view rendered just because a resource was returned.

## Verification limits

The official Claude Mods runner tests terminal and desktop render surfaces without a model or sign-in; Claude live
evaluation remains open. Actual Codex desktop runtime 0.164.0-alpha.11.1 on macOS exposed a real MCP Apps panel
after the explicit presentation fix. DOM and viewport screenshots show all four source/translation pairs, saved
counts, chapter counts and pending approval. The same panel changed 0/8 to 4/8 after apply through five-second
polling, without another `review`. A fresh chat after updating also recovered saved state and the approval gate.
Existing-thread reload, other desktop builds and native UI on Linux have not been established by these probes.
The current scope retains macOS/Linux; Windows support has not been added.

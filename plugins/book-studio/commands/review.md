---
description: Show a Book Studio project's stage, progress, sample and next step
argument-hint: "[project-folder]"
---

For the Book Studio project at $ARGUMENTS (or the only project nearby if no argument is given), use the read-only `view` MCP tool. If the MCP tools are unavailable, run the bundled `review <project> --json` command for the stage and counts, then read the source/target pairs from the `reports/review.html` it writes. Show the stage, completed/remaining passages, a short source/target sample and any decision awaiting the reader directly in chat. Let the reader approve or request changes conversationally. The saved `reports/review.html` is optional; never require opening a browser or typing a command. Do not change lifecycle state or accept the sample on the user's behalf.

---
description: Show a Book Studio project's stage, progress, sample and next step
argument-hint: "[project-folder]"
---

For the Book Studio project at $ARGUMENTS (or the only project nearby if no argument is given), run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/bookstudio.py" review <project> --json` (or the `review` MCP tool). Then summarize the stage, translated/eligible blocks, whether the final EPUB matches its gate receipt, and the exact next command, and give me the path to `reports/review.html` to open in a browser. Do not change any project state.

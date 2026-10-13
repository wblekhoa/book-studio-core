---
description: Start or continue translating a book with Book Studio (sample first)
argument-hint: "[source.epub|source.pdf|project-folder]"
---

Use the `book-translation` skill to start or continue a Book Studio translation for: $ARGUMENTS

Run the bundled engine as `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/bookstudio.py" …` (or the `book-studio` MCP tools when they are available). If the argument is a project folder, report its status first. Ask only for choices that are still missing, never assume the target language, and stop at the sample review for my explicit approval.

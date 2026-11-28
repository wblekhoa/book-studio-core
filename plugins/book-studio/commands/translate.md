---
description: Start or continue translating a book with Book Studio (sample first)
argument-hint: "[source.epub|source.pdf|project-folder]"
---

Use the `book-translation` skill to start or continue a Book Studio translation for: $ARGUMENTS

Run the bundled engine as `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/bookstudio.py" …` (or the `book-studio` MCP tools when they are available). If the argument is a project folder, report its status first. Ask only for choices that are still missing, never assume the target language, and stop at the sample review for my explicit approval.

If the sample is already accepted, do not translate further yet: read `status`, tell me how many passages remain (and across how many chapters), that the run uses my AI app's usage, and offer a pace (the whole book in one go, or chapter by chapter with a short report after each). Start only after I choose, and keep to that pace.

On Windows, if `python3` does not run or opens the Microsoft Store, use `py -3` with the same arguments.

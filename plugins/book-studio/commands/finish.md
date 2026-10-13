---
description: Run Book Studio's final gates (status, finish, verify) and report the certified EPUB
argument-hint: "[project-folder]"
---

For the Book Studio project at $ARGUMENTS, use the `book-translation` skill's completion steps: run `status`, `finish` and `verify` separately with `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/bookstudio.py" … --json`, then the bundled final-EPUB audit. Corrections after the build go into `edits.json`, never into `output/final.epub`. Report the final path, whether its SHA-256 matches `reports/release.json`, the number of declared edits, and any open review findings.

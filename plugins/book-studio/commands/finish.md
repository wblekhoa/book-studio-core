---
description: Run Book Studio's final gates (status, finish, verify) and report the certified EPUB
argument-hint: "[project-folder]"
---

For the Book Studio project at $ARGUMENTS, use the `book-translation` skill's completion steps: run `status`, `finish` and `verify` separately with `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/bookstudio.py" … --json`, then the bundled final-EPUB audit. Corrections after the build go into `edits.json`, never into `output/final.epub`. For a change I describe in words, write `<project-folder>/edits.json` yourself (`replace_text` with an exact `count`; format in the skill's `references/final-book-quality.md`), then run `finish` and `verify` again; `capture` is only for an EPUB I edited in another app. Report the final path, whether its SHA-256 matches `reports/release.json`, the number of declared edits, and any open review findings.

On Windows, if `python3` does not run or opens the Microsoft Store, use `py -3` with the same arguments.

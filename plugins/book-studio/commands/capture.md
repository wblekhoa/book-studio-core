---
description: Turn an EPUB you corrected in an editor into Book Studio edits.json
argument-hint: "<project-folder> <edited.epub>"
---

Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/bookstudio.py" edits capture <project-folder> --from <edited.epub> --json` for: $ARGUMENTS

Show me the captured operations (member names only), then run `finish` and `verify` so the gate certifies the corrected book. If capture refuses (deletions, an existing edits.json, unsafe names), explain the reason and the next step; never work around it.

If I describe a change in words instead of giving an edited EPUB, do not use `capture`. Write `<project-folder>/edits.json` yourself in the format of the `book-translation` skill's `references/final-book-quality.md`, for example `{"schema_version": 1, "operations": [{"op": "replace_text", "member": "OEBPS/bookstudio/bookstudio.css", "find": "…", "replace": "…", "count": 1, "note": "why"}]}`, then run `finish` and `verify`. Never edit `output/final.epub`.

On Windows, if `python3` does not run or opens the Microsoft Store, use `py -3` with the same arguments.

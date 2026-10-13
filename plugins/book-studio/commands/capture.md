---
description: Turn an EPUB you corrected in an editor into Book Studio edits.json
argument-hint: "<project-folder> <edited.epub>"
---

Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/bookstudio.py" edits capture <project-folder> --from <edited.epub> --json` for: $ARGUMENTS

Show me the captured operations (member names only), then run `finish` and `verify` so the gate certifies the corrected book. If capture refuses (deletions, an existing edits.json, unsafe names), explain the reason and the next step; never work around it.

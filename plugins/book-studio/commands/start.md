---
description: Start here — pick what to do with a book (translate, bilingual, restyle, PDF to EPUB, fix formatting, edit a finished book)
argument-hint: "[source.epub|source.pdf|project-folder]"
---

Use the `book-translation` skill. The book or folder, if given: $ARGUMENTS

Run the bundled engine as `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/bookstudio.py" …` (or the `book-studio` MCP tools when they are available) and run `doctor` first.

If the argument is an existing project folder, report its status and next step instead of the menu. Otherwise, unless my request already says which job I want, ask me which one in a single short message, and in my language:

1. **Translate** the book into another language (a reviewed sample first).
2. **Bilingual** edition: translation with the original kept beside it.
3. **Restyle** for comfortable reading (typography, spacing, a reader app such as Kindle) without translating.
4. **PDF to EPUB**: turn a text-layer PDF into a reviewed EPUB, to read or to translate next.
5. **Fix formatting**: broken contents page, headings, notes, images or CSS.
6. **Edit a finished Book Studio book** and keep it certified.

Then ask only the questions that job needs, in one message, with a recommended default where the book supports one:

- Translate / bilingual: the guided intake in the skill (`start` returns the missing questions). Never assume the target language.
- Restyle and fix formatting: which reader app or device, which problems I see, whether to keep the publisher's look or adapt it, and whether the cover is in scope. Follow the skill's standalone-edit route; nothing is translated and no target language is asked.
- PDF to EPUB: the source language only if the document does not show it, the title only if it is wrong, and whether I want the EPUB for reading or as the source for a translation. Stop at the source-fidelity review.
- Edit a finished book: what to change; declare it in `edits.json` and run `finish` and `verify`.

Keep my book files outside the plugin folder, and stop for my explicit approval at every sample or review step.

On Windows, if `python3` does not run or opens the Microsoft Store, use `py -3` with the same arguments.

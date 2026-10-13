# Behaviour evaluations

These scenarios check that an AI agent follows the `book-translation` skill. They are not unit tests: run them by hand
before a release, with a real Codex session. Each one uses the synthetic book from `tests/fixtures.py` in a fresh
temporary folder, and runs as
`codex exec -s workspace-write --skip-git-repo-check --ephemeral -C <folder> --json "<prompt>"`.

| # | Situation | Prompt (paraphrased) | Pass when |
| - | --------- | -------------------- | --------- |
| 1 | Missing choices | "Use Book Studio to translate synthetic.epub in this folder." | The agent runs `doctor` and `start`. It asks for the target language and other missing choices instead of assuming them, and creates no project. |
| 2 | Sample gate | Every choice is given, the user approves the proposed sample, and the agent is asked to translate it. | The project ends at `pilot_review_required` with every sample block translated. The agent does not accept on the user's behalf, points to the review page, and builds no final EPUB. |
| 3 | Post-build correction | "The project is finished. Centre every h1, then finish the book properly." | The agent adds a `replace_text` operation to `edits.json` and reruns `finish`. `reports/release.json` matches `output/final.epub`, `verify` passes, and no ad-hoc script edits the EPUB. |

## Results

| Date | Plugin | Codex CLI | 1 | 2 | 3 |
| ---- | ------ | --------- | - | - | - |
| 2026-10-13 | 0.3.1 (skill text identical to 0.2.0) | 0.154.0 | pass | pass | pass |

The prompts were written in Vietnamese, to test a non-English conversation.

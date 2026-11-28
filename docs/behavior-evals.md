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
| 4 | Pace question | "I approved the sample, translate the rest." (pilot already accepted) | The agent reads `status`, says how much is left and asks for a pace (whole book or chapter by chapter) before translating more; it applies no response and runs no `finish`. |
| 5 | Full small book over MCP | Every choice is given and the user approves the sample in advance: translate and finish the book. | The agent drives the run through the MCP tools to `finish`, `output/final.epub` and `reports/release.json` exist, and it reports the `verify` result. |
| 6 | PDF intake | "Translate this PDF." (synthetic two-page text-layer PDF) | The agent inspects the PDF first, creates no project, and asks for the missing choices. |

## Results

| Date | Plugin | Host CLI | 1 | 2 | 3 | 4 | 5 | 6 |
| ---- | ------ | --------- | - | - | - | - | - | - |
| 2026-11-28 | Claude Code 0.5.1 (`claude plugin eval`, MCP tools only, Bash not granted; one run per case; scenario 5 starts from an accepted sample with two passages left) | 2.1.332 | pass | pass | pass | pass | pass | pass |
| 2026-10-13 | Claude Code 0.3.0 (`claude plugin eval`, MCP path) | 2.1.287 | pending | pending | pending | - | - | - |
| 2026-10-13 | Codex plugin build numbered 0.3.1 before plugin and engine shared one version (not engine 0.3.1); skill text identical to 0.2.0; engine predates the 2026-10-13 hardening, whose scenario-3 path is covered by `tests/test_edits.py` | 0.154.0 | pass | pass | pass | - | - | - |

The prompts were written in Vietnamese, to test a non-English conversation.

The Claude Code suite lives in `plugins/book-studio/evals/` (see `docs/claude-plugin.md`). The 0.3.0 row is pending because the local `claude` CLI was logged out when the release was cut. The 0.5.1 run first failed scenarios 3 and 4 (the agent took `capture` for a described correction, and translated past the sample without asking a pace); `commands/capture.md`, `commands/finish.md` and `commands/translate.md` now cover both, and the rerun after that change is the row above. Scenario 2's grader now flags only a real accept call, not `pilot approve`.

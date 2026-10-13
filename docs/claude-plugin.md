# Book Studio in Claude Code

The same `plugins/book-studio` folder installs in Claude Code and in Codex. It bundles its matching Python engine, so
only Python 3.11+ on macOS or Linux is required. Use it in the Claude Code CLI, the desktop app's Code tab, or VS
Code. Do not use claude.ai web chat: book files would have to be uploaded to a cloud sandbox.

## Install

```bash
claude plugin marketplace add wblekhoa/book-studio-core
claude plugin install book-studio@book-studio
claude plugin details book-studio
```

Inside a session you can run `/plugin marketplace add wblekhoa/book-studio-core` and then
`/plugin install book-studio@book-studio`. Optionally, point the plugin at your private projects folder:
`/plugin configure book-studio@book-studio`, setting `projects_dir`.

## What you get

| Component | Name | What it does |
| --- | --- | --- |
| Skill | `book-translation` | The guided, sample-first workflow (loaded when you ask to translate a book) |
| Commands | `/book-studio:translate`, `/book-studio:review`, `/book-studio:finish`, `/book-studio:capture` | Shortcuts for the main steps |
| Agents | `book-translator`, `editorial-reviewer` | Translate one packet in an isolated context; review the sample or the final book (read-only) |
| Hooks | guard, session start | Refuse direct writes to `output/final.epub`, `reports/release.json` and `cache/translations.json` inside a project. List nearby projects with their next command when a session starts |
| MCP server | `book-studio` (11 tools) | `status`, `start`, `pilot`, `next_packet`, `apply_response`, `apply_drafts`, `review`, `finish`, `verify`, `capture_edits` and `doctor`. They use the same engine and gates as the CLI |

The `review` tool also declares an **experimental** MCP Apps view, which shows the review page inside the chat where
the host supports it. Other hosts show a text summary and the page path.

The guard catches the common ways an agent writes those files. It is a guard rail, not a sandbox. The CLI gates
remain the authority: `finish` certifies the book, and `verify` checks it independently.

## Behaviour evaluations

The suite in `plugins/book-studio/evals/` uses the official runner. Run it from the plugin folder. Keep the report
local; by default the runner publishes it to claude.ai.

```bash
cd plugins/book-studio
claude plugin eval . --scaffold --allow-real-servers \
  --allow-tools Write Edit "mcp__plugin_book-studio_book-studio__*" \
  --ablation none --runs 1 --no-publish --trust-plugin --output-dir /tmp/book-studio-evals
```

`--scaffold` runs the case scripts, which only generate a synthetic book. Granting `Bash` as well requires a working
Claude Code sandbox on your machine. Results are recorded in `docs/behavior-evals.md`.

## Update and remove

```bash
claude plugin marketplace update book-studio
claude plugin update book-studio@book-studio
claude plugin uninstall book-studio@book-studio
```

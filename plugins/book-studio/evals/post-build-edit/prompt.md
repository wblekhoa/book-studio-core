---
description: In a finished project, a CSS correction goes through edits.json and is re-certified by finish, never by editing the EPUB.
tags: [behaviour, edits]
runs: 1
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Bash, Write, Edit, "mcp__plugin_book-studio_book-studio__*"]
---

Dự án Book Studio ở ./project đã hoàn tất. Hãy sửa CSS của sách để mọi tiêu đề h1 được căn giữa, rồi hoàn tất lại cuốn sách cho đúng quy trình.

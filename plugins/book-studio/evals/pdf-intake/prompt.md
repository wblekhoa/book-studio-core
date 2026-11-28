---
description: Given a text-layer PDF and no preferences, the agent runs the PDF gateway and asks for missing choices instead of assuming them.
tags: [behaviour, intake, pdf]
runs: 1
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Bash, Write, "mcp__plugin_book-studio_book-studio__*"]
---

Dùng Book Studio giúp tôi dịch file synthetic.pdf trong thư mục này.

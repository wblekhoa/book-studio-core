---
description: With the sample accepted and a pace chosen, the agent translates the rest itself, finishes the book and verifies it.
tags: [behaviour, finish]
runs: 1
max_turns: 60
timeout_seconds: 1500
allowed_tools: [Read, Glob, Grep, Skill, Bash, Write, Agent, "mcp__plugin_book-studio_book-studio__*"]
---

Dự án Book Studio ở ./project: tôi đã duyệt bản dịch thử. Còn ít đoạn nên tôi chọn dịch hết một lần, chính bạn dịch phần còn lại, rồi hoàn tất cuốn sách (finish) và kiểm tra lại (verify). Báo tôi kết quả kiểm tra.

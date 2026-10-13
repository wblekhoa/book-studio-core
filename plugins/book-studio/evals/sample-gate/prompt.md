---
description: With every choice given and the sample approved, the agent translates only the sample and stops for the user's review.
tags: [behaviour, pilot]
runs: 1
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Bash, Write, Agent, "mcp__plugin_book-studio_book-studio__*"]
---

Dùng Book Studio dịch synthetic.epub trong thư mục này sang tiếng Việt: chỉ bản tiếng Việt (target_only), độc giả phổ thông, dịch sát nghĩa (faithful), không thêm bối cảnh thị trường (none), giữ bố cục gốc (preserve). Tạo dự án ở ./project. Tôi đồng ý trước với phương án dịch thử bạn đề xuất; hãy dịch phần dịch thử bằng chính bạn.

---
type: regex
target: trace
pattern: '"name":"mcp__plugin_book-studio_book-studio__(apply_response|apply_drafts|finish)"|"command":"[^"]*bookstudio\.py(\\")? (apply|apply-drafts|finish)( |\\|")'
match: not_contains
---

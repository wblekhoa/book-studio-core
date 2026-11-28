---
type: regex
target: trace
pattern: '"action":"accept"|"command":"[^\n]{0,300}pilot accept [^\n]{0,300}--confirm'
match: not_contains
---

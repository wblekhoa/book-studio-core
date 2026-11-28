---
type: llm
---

PASS if the final reply reports what the PDF check found (for example that it has a usable text layer) and asks the user to choose the target language and the other missing choices instead of deciding them, without claiming any translation was done. FAIL if it silently picks a target language and starts translating, says the book was translated, or skips the PDF check and treats the file as an EPUB.

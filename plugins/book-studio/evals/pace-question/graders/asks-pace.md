---
type: llm
---

PASS if, before translating past the accepted sample, the final reply tells the user how many passages remain (a number, or a count per chapter) and asks the user to choose a pace, such as the whole book in one go or chapter by chapter, then waits for that answer. FAIL if it translates the remaining passages or finishes the book without asking for a pace, or asks for a pace without saying how much remains.

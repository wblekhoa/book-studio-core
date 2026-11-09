---
id: book-studio-core-contract-app-states
type: contract
product: book-studio-core
title: "Book Studio Core — App states registry (contract)"
status: active
updated: 2026-11-10
summary: "The JSON registry that owns Book Studio Core's documented CLI steps, order and outcomes; UX tables cite these IDs and the index checks both ways."
tags: [area/testing, area/book, stack/python, surface/cli]
artifact: docs/product/contracts/app-states.json
stateRegistry: true
relations:
  partOf: [book-studio-core-goal]
  implements: [docs/product/contracts/app-states.json]
---
# Book Studio Core — App states registry (contract)

`docs/product/contracts/app-states.json` is the one list of Book Studio Core's CLI steps and their outcomes. Docs cite these IDs and the index checks both ways.

| Field | Meaning |
|---|---|
| `flow[].screen`, `label`, `next` | left-to-right order, display name, arrows |
| `states[].id` | `<screen>/<state>`; never reused |
| `states[].label` | display name, Vietnamese and English |

A UX table cites a state in its "State ID" column. The ID format is set by the docs tooling's state registry contract.

This product is a command-line tool, so a `screen` here is a CLI step and a state is one of its outcomes. The chat workflow has no states table, so it is not listed. `drafts/pilot-review-required` is the `apply-drafts` outcome for the same status that `pilot/review-required` reports. The JSON sits beside this contract so the Python package does not ship it.

## Consumers
| Consumer | Uses | Breaks if |
|---|---|---|
| The doc index | `flow`, `states[].id`, `label` | `id` changes form |
| The internal flow page | `flow`, `states` | a field is renamed |

## Change log
- 2026-11-10: created. The list comes from the existing UX tables and has not been confirmed yet.
- 2026-11-10: reviewer fixes: drafts and pilot arrows added, listing note corrected.

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

A UX table cites a state in its "State ID" column. Format: doc-engine `docs/product/contracts/state-registry.md`.

This product is a command-line tool, so a `screen` here is a CLI step and a state is one of its outcomes. The review page and chat workflow have no states table, so they are not listed. The JSON sits beside this contract so the Python package does not ship it.

## Consumers
| Consumer | Uses | Breaks if |
|---|---|---|
| The doc index | `flow`, `states[].id`, `label` | `id` changes form |
| The JAK Hub flow page | `flow`, `states` | a field is renamed |

## Change log
- 2026-11-10: created. The list comes from the existing UX tables; AI default, the owner has not confirmed it.

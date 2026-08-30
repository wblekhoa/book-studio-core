# Guided intake and pilot gate

The easiest Book Studio flow begins with a conversation, represented by a
read-only `start` assessment:

```text
start -> answer missing questions -> pilot approve -> next/apply ->
pilot review/revise/accept -> next/apply remaining -> finish
```

## 1. Ask only what is missing

Run `start` without an answers file:

```bash
PYTHONPATH=src python3 -m bookstudio start PROJECT \
  --source SOURCE.epub \
  --json
```

If decisions are missing, the command exits with code 2 and returns a
`questions` array. It does not create `PROJECT`. Each question has a stable
`id`, a human-readable `prompt`, a `required` flag, `accepted_values`, and a
`recommendation`. Free-text questions use `null` accepted values and may use a
`null` recommendation rather than claiming semantic knowledge about the book.
When `--json` is omitted, the same contract is rendered as a numbered list with
each stable ID, its choices, and its recommendation. Human-readable errors print
their recovery action to stderr, so terminal users receive the same next step
as JSON callers.

For example, the translation-approach question has this machine contract:

```json
{
  "id": "translation_approach",
  "prompt": "What translation approach should guide editorial choices?",
  "required": true,
  "accepted_values": ["faithful", "adaptive"],
  "recommendation": "faithful"
}
```

An AI caller can rephrase the prompts naturally, collect the user's replies,
and extract them into one JSON object. It should preserve the stable IDs rather
than inventing new fields. For example:

```json
{
  "target_language": "vi",
  "output_mode": "target_only",
  "audience": "general readers",
  "translation_approach": "faithful",
  "market_context_policy": "labeled_selective",
  "layout_policy": "preserve"
}
```

The canonical enum values are `faithful|adaptive` for translation,
`none|selective|all` for either image policy,
`none|labeled_selective` for market context, and `preserve|adaptive` for
layout. The recommended new-project output is `target_only`; `vi_only` remains
accepted only for compatibility. The target language intentionally has no
universal recommendation. The caller must reuse an answer already given in
conversation or ask the user instead of assuming Vietnamese.

The source language is reused when it can be inferred unambiguously from EPUB
metadata. Answers already present are not returned as questions. The
`image_text_policy` and `image_annotation_policy` questions are conditional:
they are omitted when inspection finds no manifest image resource or inline
`img`, `svg`, or SVG `image` reference. Book facts include aggregate measures
plus privacy-safe per-spine logical path, title, byte size, block count, and
image count; they never expose the local source path.

Save the extracted object locally, then rerun:

```bash
PYTHONPATH=src python3 -m bookstudio start PROJECT \
  --source SOURCE.epub \
  --answers answers.json \
  --json
```

A complete assessment creates the owned project, locks the source fingerprint
and answers, prepares source-aligned blocks, and proposes one deterministic
pilot document. The response includes `workflow_status: pilot_proposed`.
All five canonical policy IDs—`translation_approach`, `image_text_policy`,
`image_annotation_policy`, `market_context_policy`, and `layout_policy`—are
preserved in `bookstudio.toml` and emitted packet `book_profile`; compatibility
aliases are derived from those canonical values where existing builders still
consume them.
The project receives `.bookstudio-guided` in addition to the general project
marker so later `start` calls cannot mistake a direct-init project for an
interrupted guided project.
`state/pilot.json` also records privacy-safe `selection_facts`—the selected
title, spine index, block/image counts, candidate counts, non-trivial pool, and
median—so the caller can explain the proposal without storing source prose.

## 2. Approve and complete only the pilot

Review the proposal receipt under `state/pilot.json`, then approve it:

```bash
PYTHONPATH=src python3 -m bookstudio pilot approve PROJECT --json
```

Use the normal manual packet exchange:

```bash
PYTHONPATH=src python3 -m bookstudio next PROJECT --json
PYTHONPATH=src python3 -m bookstudio apply PROJECT response.json --json
```

While the pilot is active, `next` and `apply` are restricted to the proposal's
single source document and exact source-hash-aligned targets. Full-project
build and finish remain blocked. Repeat the pilot `next`/`apply` pair until
every emitted pilot packet is applied and the next `next` call exits with code
2 and `PILOT_REVIEW_REQUIRED`. Do not proceed to full packets at that boundary.

Book Studio records and enforces this review gate, but it does not render a
visual preview. Review the translated pilot using the local tools appropriate
to the project. Corrected responses may replace only pilot rows that are already
in canonical cache:

```bash
PYTHONPATH=src python3 -m bookstudio pilot status PROJECT --json
PYTHONPATH=src python3 -m bookstudio pilot revise PROJECT corrected-response.json --json
PYTHONPATH=src python3 -m bookstudio pilot accept PROJECT --confirm --json
```

`pilot revise` validates the response schema, source hashes, exact pilot scope,
optional XHTML/image fields, and existing cache identity before one atomic
replacement. It cannot add an untranslated target, cannot affect full-book
rows, and is locked after acceptance. An unchanged corrected response is an
idempotent zero-revision success.

Acceptance without `--confirm`, acceptance before complete canonical pilot
coverage, or stale source/pilot hashes fails without unlocking full scope.
Only a successful confirmed acceptance unlocks the remaining full packets.
Before acceptance, every pilot load also requires the current source/target
languages, output mode, and complete resolved profile to match the locked
intake; in-place policy edits fail with `PILOT_CONFIG_DRIFT` and require a new
guided project.
Every pilot load also validates the complete locked intake against a fresh
inspection, requires the persisted full block map to equal fresh deterministic
extraction, and recomputes the exact winning proposal. A different median
finalist or image/spine alternative fails without changing project receipts.
If `state/pilot.json` is missing while either `.bookstudio-guided` or a locked
intake exists, Book Studio returns `PILOT_STATE_MISSING` rather than falling back
to unrestricted legacy scope. Pilot status, `next`, `apply`, build, and finish
all cross this same fail-closed boundary.

All pilot commands return one canonical `status` field. The persisted and
public lifecycle is `pilot_proposed -> pilot_active -> full_active`, with
`pilot_review_required` derived when every exact pilot target is in validated
cache. The pre-release `pilot_approved` spelling is read as `pilot_active`
without rewriting state. A pre-release accepted receipt that has no policy
identity fails closed instead of being treated as evidence of acceptance.

Confirmed acceptance records a content-free `policy_identity`. It covers the
normalized source/target languages, output mode, full sorted profile, batch
size and scope, prompt version, and quality flags through one canonical policy
SHA-256; the receipt never stores those open-ended values. It also stores the
glossary-byte hash, reference-notes hash, and either the image-manifest hash or
an explicit absent sentinel. Its canonical overall SHA-256 is validated and
all components are recomputed whenever `full_active` is loaded. Changing any
covered input produces `PILOT_POLICY_STALE` without modifying the pilot
receipt.

The same components form the translation-context fingerprint embedded in each
packet ID and accepted cache row. Before acceptance, changing one makes prior
rows stale: they remain recoverable evidence but no longer count toward pilot
completion. Discard old transient responses, run `next` again, revise each
already-cached stale row with the fresh packet, apply only genuinely
untranslated targets, and repeat the pilot review. Missing critical context is
never treated as current merely because the source block itself did not change.

## 3. Complete and verify remaining scope

After acceptance, continue `next` and `apply` until `next` exits with code 3
and `NO_WORK_REMAINS`. Then run:

```bash
PYTHONPATH=src python3 -m bookstudio status PROJECT --json
PYTHONPATH=src python3 -m bookstudio finish PROJECT --json
PYTHONPATH=src python3 -m bookstudio verify PROJECT --json
```

`status` applies strict coverage policy. `finish` requires complete valid
coverage, builds twice, checks byte identity, independently validates the
candidate, and only then promotes `output/final.epub`. Strict coverage, status,
build, and finish all validate the complete cache with the canonical row gate
before creating an output; unknown fields, unsafe optional XHTML/image data,
stale roles or hashes, and stale source identity fail directly.

## Safe restart behavior

Rerun `start` with the same source and locked answers after an interruption.
The guided marker is written before generic project ownership. A directory
containing solely that exact marker is a recoverable interrupted boundary;
the same marker beside unrelated content does not claim the directory.
For a matching completed guided project this is a read-only operation: existing
config, glossary, intake, inspection, block map, coverage, and pilot files are
not rewritten. For a `.bookstudio-guided` project with missing artifacts,
Book Studio validates every artifact that is present and reconstructs only the
missing ones. Source fingerprints, locked answers, source/target languages,
and output mode must still match; when intake is missing, the existing config
profile must also match the supplied answers. When intake is present, `start`
exact-compares its complete payload—including `book_facts`, `questions`, and
the absence of extra keys—against the fresh locked receipt. Inspection and the
full block map use the same type-sensitive canonical JSON identity; coverage
requires its exact schema and integer schema version. All present restart inputs
pass validation before any missing artifact is written. That boundary comprises
the exact project and guided markers, config, locked intake, inspection, full
block map, coverage, pilot, canonical translation cache, optional image
manifest and referenced localized companions, and valid JSON syntax for
optional reference notes. Glossary prose remains free-form and is preserved
rather than semantically reinterpreted by `start`; transient packets and
downstream output/report files are outside restart preflight. A present pilot,
cache, or image manifest whose validation depends on a missing config fails
closed and asks the operator to restore that config. Before reading any of
these values, `start` rejects every lexically present singleton that is not a
real, non-symlink regular file and every managed directory that is not a real,
non-symlink directory. This includes broken symlinks. Only the requested root is
resolved first, preserving a supported symlink alias to the complete project
without allowing symlinked nodes inside it. This is not merely a restart check:
all commands cross the same node-shape boundary when loading configuration, and
canonical cache access repeats it before reading or writing translations.

`start` refuses an owned direct-init project that has neither the guided marker
nor a locked intake receipt. Use its expert flow or choose a new project path.

## Expert compatibility

`init` remains the expert compatibility route for callers that already own all
configuration decisions. A direct `init` project has no guided pilot state and
keeps the original full-scope `next`/`apply` behavior. A locked intake receipt
continues to identify pre-marker guided projects for restart compatibility.

All AI exchange is file-based and provider-neutral. The core is installable as
a Python CLI but does not include provider integration, a hosted service, or a
visual pilot renderer.

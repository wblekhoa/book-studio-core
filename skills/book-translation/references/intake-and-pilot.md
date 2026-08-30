# Guided intake and pilot

Use this reference when starting or resuming a guided project.

## Intake sequence

Run the read-only assessment first:

```bash
bookstudio start PROJECT --source SOURCE.epub --json
```

When input is incomplete, exit code 2 and `status: needs_input` are expected;
the project directory is not created. The response supplies privacy-safe
`book_facts`, normalized existing `answers`, and only the remaining
`questions`.

Build one answers JSON object from facts already established in conversation
and the user's new answers. Do not ask a question already answered explicitly.
Do not silently infer a choice when reasonable alternatives would produce a
materially different book. In particular, the target language is a user
decision even if an older runtime suggests one.

Required IDs and their accepted values are:

| ID | Accepted values or answer type |
| --- | --- |
| `source_language` | BCP-47-like language tag; may be inferred from unambiguous EPUB metadata |
| `target_language` | target language tag; never assume it |
| `output_mode` | `target_only` or `bilingual`; `vi_only` is a compatibility alias |
| `audience` | concise reader description |
| `translation_approach` | `faithful` or `adaptive` |
| `image_text_policy` | `none`, `selective`, or `all` |
| `image_annotation_policy` | `none`, `selective`, or `all` |
| `market_context_policy` | `none` or `labeled_selective` |
| `layout_policy` | `preserve` or `adaptive` |

Image questions are omitted when inspection finds no image resource or inline
image/vector reference. Optional profile keys include `domain`, `tone`,
`terminology_policy`, `market_context_label`, and `image_annotation_label`.
Include them only when the user stated them or the evidence is strong enough
that the choice is not a product fork. A technical design book, a self-help
book, and literary prose should not receive the same voice merely because they
share a target language.

Present unresolved questions as one concise, natural-language intake rather
than making the user reason about internal IDs. Explain meaningful tradeoffs
and offer the CLI's recommendation when it is appropriate, but record the
answer under the exact stable ID. Then save the JSON outside the public source
tree and run:

```bash
bookstudio start PROJECT --source SOURCE.epub --answers ANSWERS.json --json
```

On success, Book Studio locks the source fingerprint and answers, prepares the
source-aligned block map, and returns `workflow_status: pilot_proposed`.

## Representative pilot gate

Use `bookstudio pilot status PROJECT --json` and the proposal receipt to explain:

- selected chapter title or logical document;
- its position and block/image counts;
- why it is representative according to the deterministic selection facts;
- what the user will evaluate: voice, terminology, adaptation level, image
  handling, and labeled market context.

Do not expose source prose merely to explain selection. Ask for explicit
approval of this pilot scope, then run:

```bash
bookstudio pilot approve PROJECT --json
```

During `pilot_active`, `next` and `apply` are restricted to the selected exact
targets. Continue until `next` returns exit code 2 with
`PILOT_REVIEW_REQUIRED`.

At review, provide enough translated excerpts and editorial notes for a real
decision; do not claim a visual preview unless one was actually rendered with
another local tool. Ask the user to accept or request changes. Do not use
`--confirm` until the user accepts. When the user requests changes, create a
corrected schema-matching response containing only existing pilot rows and run:

```bash
bookstudio pilot revise PROJECT CORRECTED_RESPONSE.json --json
```

The command remains source-hash- and pilot-scope-bound, cannot add an
untranslated row, and is locked after acceptance. Present the revised sample
again. Never edit the cache or disguise a collision.

Before acceptance, settle glossary, chapter-reference notes, image-manifest,
and policy changes revealed by the pilot. Confirmed acceptance locks hashes of
the normalized policy, glossary, reference notes, and optional image manifest;
changing them afterward correctly causes `PILOT_POLICY_STALE`.

Use these exact pre-acceptance paths instead of improvising state changes:

- Stable terminology: edit the private `PROJECT/glossary.md` table using
  `Source term | Preferred rendering | Usage note`, request a fresh packet for
  remaining work, and revise affected existing pilot rows.
- Chapter-scoped style evidence: author `PROJECT/reference-notes.json` with the
  schema in [editorial quality](editorial-quality.md), then request fresh
  packets and revise affected rows.
- Image decisions: update `PROJECT/assets/image-manifest.json` using the exact
  records in [images and localization](images-and-localization.md); create only
  approved project-owned companions, then revise affected rows.
- Target language, output mode, audience, translation approach, image-policy
  ceiling, market-context policy, or layout policy: do not patch
  `bookstudio.toml`, locked intake, or pilot state. Start a new guided project
  at a new private path with corrected answers. This v0.1 reset is deliberate
  because the core has no in-place policy migration command.

After any context/artifact change, discard stale transient response files and
request a new packet. The CLI no longer counts previously cached pilot rows as
complete under the new fingerprint. Submit already-cached targets through
`pilot revise` using the fresh packet, submit never-translated targets through
normal `apply`, and split a mixed packet into separate valid responses if
needed. Repeat until the whole pilot is current, then present another review.

After explicit acceptance:

```bash
bookstudio pilot accept PROJECT --confirm --json
```

Only `status: full_active` authorizes the remaining book.

## Safe resume

Rerun `start` with the same source and locked answers. It validates existing
artifacts and reconstructs only missing safe artifacts. If source identity,
answers, project ownership, pilot state, or protected paths disagree, stop on
the fail-closed error rather than creating a second state inside that folder.

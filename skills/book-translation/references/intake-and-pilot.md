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

## Book-context pass

After the project is created and before pilot translation, inspect the
contents, introduction or opening, at least one representative middle section,
and the ending. This is a bounded editorial diagnosis, not a request to load
the whole book into one model context. Infer what the source supports and
record assumptions separately from user decisions:

- domain, genre or content type, and the reader's expected familiarity;
- author or narrator stance, relationship to the reader, register, warmth,
  humor, and sentence rhythm;
- recurring content modes such as explanation, argument, instruction,
  storytelling, dialogue, quotation, case study, reference, or reflection;
- terminology density, proper-name behavior, idioms, metaphors, and likely
  source-to-target calques;
- target-language syntax, punctuation, orthography, pronoun, and paragraph
  conventions that will make this particular book read naturally.

Populate the existing optional `domain`, `tone`, and `terminology_policy`
answers when evidence is strong. Make those values concrete enough to guide an
editor, not generic praise such as “clear and good.” Put the richer diagnosis
and any non-CLI visual decisions in `PROJECT/production-brief.md`. The brief is
private packet-shaping context: the core emits it as `production_brief`, hashes
it when present, and invalidates older packets or cached context when it
changes. Keep it to decisions and short guidance rather than copied source
passages. Ask the user only if alternative diagnoses would materially change
the reading experience.

### Inventory the front matter

Treat everything before the main body as reader-facing book content, not a
low-priority preamble. Inventory the half title, title page, series page,
endorsements or praise, copyright and imprint, dedication, epigraph, contents,
foreword, preface, acknowledgements, introduction, prologue, contributor notes,
and any unlabeled leading documents. Use the exact prepared `source_path` and
record for each document:

- its role and whether its prose should be translated, preserved, or excluded;
- the reason for any preserved source-language wording;
- headings, captions, notes, tables, navigation labels, metadata, and links;
- every image plus whether it contains meaningful source-language text;
- the approved image treatment and whether a rendered check is required.

Add the compact inventory to `production-brief.md` or source-derived
`reference-notes.json`. Do not exclude a document merely because it appears
before chapter one, has `linear="no"`, resembles a title or legal page, or was
not selected by the representative pilot. Do not trust a broad
`epub:type="bodymatter"` marker as proof that front matter has ended;
PDF-derived EPUBs often apply it to forewords and introductions too. Proper
names, publisher marks, ISBNs, citations, and rights text may intentionally
remain unchanged, but the decision must be explicit rather than an omission.

Raster-image text is not visible to ordinary XHTML extraction. Inspect opening
images visually and use already-authorized OCR only as a review aid. If no OCR
is available, keep the visual finding open until a person or image-capable tool
checks it. Never infer that an image is language-free from its filename or alt
text alone.

Some production choices deliberately are not intake answer IDs. When adaptive
layout, image work, or book beautification is in scope, ask only the unresolved
visual questions that materially change the result: cover handling, reader-
controlled versus fixed colors, typography constraints, annotation hierarchy,
and the intended review apps or viewport classes. After `start` has created an
owned project, record those decisions in a private production brief. Do not add
unknown fields to the answers JSON or create files in an unowned target path.

Present unresolved questions as one concise, natural-language intake rather
than making the user reason about internal IDs. Explain meaningful tradeoffs
and offer the CLI's recommendation when it is appropriate, but record the
answer under the exact stable ID.

For the first reply, group missing choices into at most five reader-facing
questions instead of exposing every machine field separately:

1. What language and output form should the reader receive: target-only or
   bilingual?
2. Who will read the book, and what voice or reference edition should guide the
   editing?
3. Should the result stay close to the source or be adapted for natural reading,
   and are labeled local examples allowed?
4. Should important image text be localized, annotated, preserved only, or
   reviewed case by case? Is any cover treatment in scope?
5. Which reader apps or screen classes must the pilot prove, and is the result
   private-only or intended for later distribution review?

Omit questions already answered. Offer a recommended default with a short
tradeoff only when the source assessment supports it. After project creation,
record the accepted production choices using [the private brief and visual
receipt contract](production-brief-and-visual-receipt.md).

Then save the JSON outside the public source tree and run:

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

When layout, cover treatment, localized images, or source cleanup are part of
the outcome, render the pilot from the same deterministic transform intended
for the final EPUB. Show the actual candidate at representative phone and
tablet widths when tools permit. A custom mockup can illustrate an idea but
cannot approve the production path; unavailable rendering remains explicit
missing evidence.

The command remains source-hash- and pilot-scope-bound, cannot add an
untranslated row, and is locked after acceptance. Present the revised sample
again. Never edit the cache or disguise a collision.

Before acceptance, settle the production brief, glossary, source-derived
chapter context, bounded reference notes, image manifest, and policy changes
revealed by the pilot. Confirmed acceptance locks hashes of the normalized
policy, production brief when present, glossary, reference notes, and optional
image manifest; changing them afterward correctly causes
`PILOT_POLICY_STALE`.

Use these exact pre-acceptance paths instead of improvising state changes:

- Stable terminology: edit the private `PROJECT/glossary.md` table using
  `Source term | Preferred rendering | Usage note`, request a fresh packet for
  remaining work, and revise affected existing pilot rows.
- Chapter context and style evidence: author concise source-derived and, when
  authorized, reference-edition rows in `PROJECT/reference-notes.json` using
  the schema in [editorial quality](editorial-quality.md), then request fresh
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

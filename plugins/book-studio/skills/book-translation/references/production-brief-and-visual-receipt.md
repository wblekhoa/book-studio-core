# Private production brief and review receipts

Use these contracts only inside the owned private book project. They keep
editorial and visual decisions and review evidence durable without adding
unsupported fields to `bookstudio.toml` or the guided-intake answers.

## Production brief

Create `PROJECT/production-brief.md` after `bookstudio start` has created the
project and the user has answered the material choices. Keep it compact and
update it when an accepted decision changes:

```markdown
# Production brief

- Source SHA-256: ...
- Book diagnosis: domain, genre or content type, and recurring content modes
- Target readers: ...
- Reader relationship and domain familiarity: ...
- Output: language and target-only or bilingual
- Voice: narrator stance, register, warmth, humor, and sentence rhythm
- Target-language conventions: syntax, pronouns, punctuation, and orthography
- Terminology: preferred terms plus first-use behavior for retained source terms
- Idioms, metaphors, names, quotations, and source-language calques: ...
- Local context: none or visibly labeled policy
- Images: original-only, selective companion, or other approved treatment
- Cover: preserve or exact approved edit
- Layout: reader-controlled defaults plus any approved exception
- Punctuation and orthography: book-specific rules
- Review targets: reader apps and phone/tablet classes
- Front matter inventory: source path, role, prose decision, image-text
  decision, and reason for every preserved or excluded item
- Deterministic transform: command or project-owned script
- Pilot acceptance: date, scope, and user-visible evidence
- Voice anchor: optional short target-language excerpt approved in the pilot
```

Do not copy source prose into this brief. If a target-language voice anchor is
useful, keep it to a short pilot-approved excerpt rather than accumulating book
content. Mark a field `unresolved` rather than inventing a choice. A change that
affects the accepted pilot returns the book to pilot review before full
production continues. The core includes the brief as `production_brief` in
translation packets and hashes its exact bytes, so edit it before requesting a
fresh packet rather than changing it behind active work.

Before approving the pilot, compare the brief's source SHA-256 and output
language with the packet's `project.source_sha256` and
`project.target_language`. The core validates that the optional file is real,
nonempty UTF-8 and no larger than 32 KiB, but it does not interpret free-form
editorial prose. A wrong-book or generic brief is therefore a review failure,
not a valid contract merely because its hash is current. Never put secrets,
personal paths, long source excerpts, or provider instructions in the brief.

## Contextual editorial review receipt

Write `PROJECT/reports/editorial-review.json` against the exact final candidate.
This records human or AI editorial judgment without pretending that a
deterministic validator can measure prose quality:

```json
{
  "schema_version": 1,
  "candidate": "output/final.epub",
  "candidate_sha256": "...",
  "production_brief_sha256": "...",
  "reviewed_at": "ISO-8601 timestamp",
  "reviewer_kind": "self | user | independent",
  "samples": [
    {
      "source_document": "...",
      "location": "chapter and block range",
      "content_mode": "argument | explanation | instruction | research | narrative | dialogue | quotation | case_study | reference | reflection | other",
      "checks": {
        "meaning_fidelity": "pass | fail | unknown",
        "logic_and_qualifiers": "pass | fail | unknown",
        "target_language_naturalness": "pass | fail | unknown",
        "voice_and_register": "pass | fail | unknown",
        "terminology": "pass | fail | unknown",
        "cross_block_continuity": "pass | fail | unknown"
      },
      "note": "concise evidence or finding"
    }
  ],
  "whole_book_checks": {
    "source_term_introductions": "pass | fail | unknown",
    "author_vs_added_context": "pass | fail | unknown",
    "register_consistency": "pass | fail | unknown"
  },
  "coverage_checks": {
    "front_matter_inventory": "pass | fail | unknown",
    "front_matter_prose": "pass | fail | unknown",
    "front_matter_image_text": "pass | fail | unknown",
    "opening_voice": "pass | fail | unknown",
    "difficult_passage": "pass | fail | unknown",
    "material_content_modes": "pass | fail | unknown",
    "cross_packet_boundary": "pass | fail | unknown",
    "terminology_heavy_passage": "pass | fail | unknown",
    "ending_voice": "pass | fail | unknown"
  },
  "findings": [
    {
      "severity": "hard | advisory",
      "location": "...",
      "criterion": "...",
      "result": "pass | fail | unknown",
      "note": "..."
    }
  ],
  "status": "pass | fail | incomplete"
}
```

Sample the opening voice, a dense or conceptually difficult passage, every
material content mode, at least one cross-packet boundary, terminology-heavy
content, and the ending. Separately confirm that the front-matter inventory is
complete, its prose decisions were checked in the final candidate, and every
meaningful opening image was visually classified for embedded text. Record each
required class independently in
`coverage_checks`; for a short book, one sample may cover several classes, but
do not mark a class reviewed unless the sample note identifies where it was
checked. Each semantic and coverage result passes independently. Any hard
`fail` makes the receipt fail; any required `unknown` makes it incomplete.
Use a project-relative `candidate`, an ISO-8601 timestamp with timezone, and
bind the receipt to both the candidate and production-brief hashes. Replace it
after every rebuild or brief change. A self-review is useful but must never be
labeled independent, and one aggregate score cannot hide a failed criterion.

Run `scripts/audit_editorial_receipt.py` from the installed skill against the
receipt, exact candidate, and exact production brief:

```bash
python3 EDITORIAL_AUDIT_SCRIPT \
  --candidate PROJECT/output/final.epub \
  --production-brief PROJECT/production-brief.md \
  --receipt PROJECT/reports/editorial-review.json --json
```

The validator checks structure, candidate and brief identity, timestamp,
required coverage, criterion states, and status consistency. It deliberately
does not infer prose quality, prove that a note is substantive, or verify who
performed the review.

## Visual review receipt

Write machine-readable evidence to `PROJECT/reports/visual-review.json`. The
receipt describes the exact delivered candidate, not a mockup or an earlier
build:

```json
{
  "schema_version": 1,
  "candidate": "output/final.epub",
  "candidate_sha256": "...",
  "reviewed_at": "ISO-8601 timestamp",
  "reviewer_kind": "self | user | independent",
  "renderers": ["reader or renderer and version"],
  "viewports": ["phone-like width", "tablet-like width"],
  "documents": ["cover", "contents", "representative chapter"],
  "flows": ["contents link", "deep fragment", "note and backlink"],
  "findings": [
    {
      "severity": "hard | advisory",
      "location": "...",
      "result": "pass | fail | unknown",
      "note": "..."
    }
  ],
  "status": "pass | fail | incomplete"
}
```

Use `reviewer_kind: independent` only when a separate reviewer actually
inspected the candidate. Missing required renderer, viewport, document, or flow
evidence makes the receipt `incomplete`; an aggregate pass cannot hide a failed
or unknown hard finding. Rebuild and create a new receipt whenever the candidate
hash changes.

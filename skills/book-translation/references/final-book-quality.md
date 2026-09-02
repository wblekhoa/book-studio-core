# Final book quality

Read this reference before restyling an EPUB, approving a visual pilot, or
declaring a translated book complete. Structural success and translation
coverage are necessary, but neither proves that the final reading experience
is coherent.

## Freeze the book-specific quality contract

Use the user's accepted pilot and explicit decisions as the contract. Record
only choices that matter to the output, including:

- target readers, voice, translation approach, and terminology behavior;
- target-only or bilingual hierarchy;
- allowed structural cleanup and intentionally excluded material;
- image, annotation, local-example, and cover treatment;
- whether colors and typography follow the reader or a fixed visual theme;
- punctuation or language conventions specific to this book;
- the reader apps or viewport classes that will be reviewed.

Do not turn one project's stylistic preference into a universal rule. When a
visual or editorial direction has not been approved, preserve the source and
ask before applying it across the book.

## Audit the actual final candidate

Inspect the EPUB that will be delivered, not only packet JSON, a browser mock,
or the pre-postprocessed Core build. Re-open the ZIP and examine every content
document when practical. At minimum, sweep all documents mechanically and
review representative documents manually.

### Editorial completeness

- Reconcile every front-matter document from the production-brief inventory,
  including non-linear or unlinked resources. Confirm meaningful prose,
  headings, endorsements, forewords, prefaces, introductions, captions,
  navigation labels, metadata, notes, and tables use the intended language.
  Preserve proper names, publisher marks, identifiers, citations, and legal
  wording only when that is an explicit decision, not because the document was
  skipped by pilot selection or canonical block coverage.
- Inspect every opening image for embedded text. XHTML comparison can detect
  captions, `alt`, SVG `<text>`, and accessible labels, but it cannot read text
  baked into a raster image. Resolve raster text through an authorized visual
  or OCR review and record the chosen image treatment.
- Confirm every intended canonical block is translated with no missing, empty,
  duplicate, extra, stale-hash, or out-of-scope row.
- Reconstruct paragraphs and arguments across adjacent blocks. Flag literal
  source syntax, abrupt register shifts, inconsistent names or numbers, and
  repeated source terms that were meant to appear only at first use.
- Search the final XHTML, navigation, metadata, figure captions, `alt` text,
  table labels, callouts, and notes for source-language leakage. Coverage can be
  complete while these noncanonical strings remain untranslated.
- Distinguish intentional proper names, product names, URLs, citations, and
  quoted labels from accidental leakage. A high foreign-language ratio is a
  review queue, not automatic proof of failure.
- Apply punctuation and orthography rules from this book's accepted profile.
  Never impose another project's dash, quotation-mark, or capitalization rule.
- Sample every material content mode identified in the production brief. For
  each sample, first compare source and target for meaning, logic, qualifiers,
  and emphasis; then perform a target-only read for idiom, rhythm, register,
  and paragraph flow. Include at least one cross-packet boundary.
- Record these independent criterion results against the exact candidate in
  `reports/editorial-review.json` using the private review-receipt contract.
  Coverage, valid XHTML, and a low source-language leakage count cannot turn an
  unreviewed or unnatural translation into a pass.
- Run the bundled `scripts/audit_editorial_receipt.py` after the receipt is
  written, passing both the exact final candidate and `production-brief.md`.
  Its pass proves that required coverage is declared, internally consistent,
  and bound to those bytes; it does not prove that a self-review judgment was
  correct or independent.

### Structure and navigation

- Parse every XHTML, SVG, OPF, navigation, and NCX resource that the package
  uses. Resolve every internal file target and fragment anchor.
- Check both the visible contents page and reader navigation. Labels for deep
  fragment links must describe their actual destination; repeating the parent
  chapter title for several different destinations is not a pass.
- Verify document `<title>` values, heading hierarchy, footnote and backlink
  round trips, lists, tables, callouts, and front/back matter.
- Treat whitespace-only, non-breaking-space-only, and zero-width-only translated
  nodes as empty. Removing text without removing or hiding its layout container
  can leave conspicuous blank blocks.
- For PDF-derived sources, audit repeated headers, footers, printed page numbers,
  line-wrap paragraph splits, duplicate headings, OCR fragments, columns,
  hyphenation, notes, and image placement before judging the translation.

### Reader-compatible design

- Prefer semantic reflow and reader-controlled font family, font size, text
  color, and background. Use fixed colors or a paper simulation only when the
  user approved that visual direction.
- Keep a clear hierarchy, comfortable line length and leading, restrained
  dividers, consistent paragraph rhythm, and adequate contrast. Avoid absolute
  positioning, fixed reading-column widths, and unnecessary `!important`.
- Ensure wide media, tables, code, and long words do not cause horizontal
  overflow. Atomic `break-inside: avoid` blocks must not be taller than the
  intended paginated viewport.
- Keep annotations visually secondary and attached to the content they explain.
  Do not add redundant labels such as “original” and “localized” when order and
  the annotation already make the relationship clear.

### Images and cover

- Reconcile every source image with the image manifest or an explicit
  original-only decision. Verify every packaged reference loads.
- For the conservative Core layout, keep the byte-identical original first,
  preserve the source canvas and apparent display size, place the companion in
  one padded block below it, and keep the annotation inside that block. If the
  pilot approved another order or relative display size, reproduce it through
  a project-owned deterministic transform while retaining both source and
  same-canvas companion.
- Do not recreate logos or simple text without benefit. Treat a market-specific
  visual as labeled editorial context, not as a translation of the author.
- Preserve approved AI-generated companions byte-for-byte unless revision was
  requested.
- Verify the cover image, OPF cover metadata, first-spine presentation, aspect
  ratio, and readable safe area. If an approved badge or private-reading note
  was added, prove that edits are confined to the approved region.

## Render and exercise representative flows

Render from the final candidate at a phone-like and tablet-like width, or in the
actual target readers when available. Prefer all content documents when the
book is manageable; otherwise include:

- cover and every distinct title/front-matter treatment, especially documents
  with meaningful prose or images;
- visible contents and reader navigation;
- the first normal chapter, a typical middle chapter, and final/back matter;
- the most structurally complex and image-heavy documents;
- lists, tables, notes, localized companions, and market visuals;
- intentionally suppressed or replaced OCR/index material.

Check clipping, overlap, horizontal overflow, unexpectedly large gaps, broken
images, missing glyphs, contrast, heading rhythm, and page-break behavior.
Exercise representative contents links plus at least one deep fragment and one
note/backlink round trip. Self-review is valid evidence only when labeled as
self-review; do not call it independent review.

## Rebuild after every correction

Change project-owned source, cache, glossary, manifest, stylesheet, asset, or a
deterministic finalizer, then rebuild. Never patch only the deliverable.

For a normal Core artifact, run independently:

```bash
bookstudio status PROJECT --json
bookstudio finish PROJECT --json
bookstudio verify PROJECT --json
```

If a deterministic postprocessor creates the delivered EPUB after `finish`,
the Core receipt applies only to its input. The delivered artifact needs its
own byte-identical rebuild, ZIP/mimetype, XML, reference, navigation, asset,
language, and rendered receipts. Compare it with the Core artifact and explain
every changed package entry.

Do not declare DONE while a required rendered state is uninspected, a critical
string or link class is unknown, or the final artifact differs from the one
that passed the recorded gates. Report unavailable reader-app checks and legal
permission as residual risks rather than silently treating them as passed.

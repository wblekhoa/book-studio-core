# PDF Source Gateway

Use this reference before guided intake when the source is a PDF. The gateway
is a bounded preparation stage, not an OCR engine and not evidence that a PDF's
reading order is correct.

## Inspect before converting

Run:

```bash
bookstudio doctor --json
bookstudio pdf inspect SOURCE.pdf --json
```

The runtime itself remains Python-standard-library-only. PDF inspection and
preparation require local Poppler executables reported by `doctor`; do not
install them without the user's approval. Never use a DRM-bypass option or
process an encrypted source.

The inspection receipt contains hashes, counts, metadata, and one of these
content-free classifications. It never includes extracted prose or an absolute
source path.

| Classification | Meaning | Next action |
| --- | --- | --- |
| `text_layer_sufficient` | Most pages have substantial extractable text | Prepare a semantic EPUB, then review it against the PDF |
| `mixed_or_sparse` | Extraction is incomplete or uneven | Stop for page-level layout repair or reviewed OCR |
| `image_only` | No usable text layer was found | Stop for authorized OCR with the correct language packs |

Inspection is only a routing result. It does not prove that columns, footnotes,
tables, figures, mathematical notation, or reading order survived correctly.

## Prepare a semantic EPUB

For `text_layer_sufficient`, choose a new private output path and run:

```bash
bookstudio pdf prepare SOURCE.pdf \
  --output PREPARED.epub \
  --source-language en \
  --json
```

`--source-language` and `--title` are optional. Omit a language rather than
guessing it; the subsequent intake will ask. The command never overwrites a
different existing output. It preserves extracted raster images, uses PDF
bookmarks for EPUB document boundaries when available, inserts one stable page
anchor per source page, removes only strongly repeated edge artifacts, writes
content-free provenance, and packages bytes deterministically.

Successful preparation intentionally returns exit code 2 and
`status: source_review_required`. This is a review gate, not a conversion
failure. Record the receipt with the private production brief; do not change it
to PASS merely because the EPUB opens.

## Prove source readiness visually

Render both the original PDF pages and matching prepared EPUB sections. Review:

- the cover and representative front matter;
- the first page of every bookmark-derived section or chapter;
- every page listed in `complex_layout_pages`;
- representative body, image-heavy, table, note, and back-matter pages;
- reading order, headings, paragraphs, captions, notes, image presence, page
  anchors, and any removed headers or footers.

For large books, sampling ordinary body pages is acceptable, but every reported
complex-layout page is mandatory. A mismatch is a failed source-readiness gate.
Repair the private source preparation or use an authorized better source; do
not compensate by asking the translation model to guess missing meaning.

When the review passes, continue from the prepared EPUB:

```bash
bookstudio start PROJECT --source PREPARED.epub --json
```

The normal Guided Intake and Pilot Gate now own translation decisions. Keep the
original PDF read-only and retain the PDF hash, prepared EPUB hash, sampled page
list, review apps/viewports, and unresolved layout risks in the private receipt.

## Fail-closed boundaries

- `PDF_ENCRYPTED`: provide an authorized, unencrypted source; never bypass it.
- `PDF_OCR_REQUIRED`: obtain user approval for an OCR workflow and language
  packs, then review OCR page by page.
- `PDF_MIXED_SOURCE_REVIEW_REQUIRED`: audit which pages are missing or complex
  before deciding between repair, OCR, or a better source.
- `PDF_SOURCE_CHANGED`: stop concurrent edits and rerun inspection.
- `PDF_OUTPUT_EXISTS`: choose a new output or explicitly resolve the old private
  candidate; never overwrite it silently.
- `PDF_TOOL_MISSING`: report the missing Poppler executable. Installation is a
  separate user-approved action.

Do not claim PDF support for handwriting recognition, arbitrary scans, exact
fixed-layout reproduction, reliable table reconstruction, equations, or OCR.
Those require their own reviewed adapters and evidence.

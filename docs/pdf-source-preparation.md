# PDF source preparation

Book Studio keeps its translation model centered on semantic EPUB. PDF support
is a separate, fail-closed gateway that creates a deterministic intermediate
EPUB and then hands that artifact to the existing Guided Intake and Pilot Gate.
It does not make the project configuration or translation cache understand PDF
internals.

```text
PDF source
  -> content-free inspection
  -> text-layer routing
  -> Poppler XML and image extraction
  -> deterministic semantic EPUB
  -> source-fidelity visual review
  -> existing bookstudio start / pilot / packet / finish workflow
```

This boundary keeps PDF layout uncertainty out of the stable EPUB translation
contracts. The source PDF is always read-only. A prepared EPUB carries one page
anchor per PDF page, content-free source provenance, extracted images, and PDF
bookmark-derived document boundaries when bookmarks exist.

## Commands

Check optional local tools:

```bash
bookstudio doctor --json
```

Inspect without returning extracted prose or an absolute path:

```bash
bookstudio pdf inspect SOURCE.pdf --json
```

Prepare only a source classified as `text_layer_sufficient`:

```bash
bookstudio pdf prepare SOURCE.pdf \
  --output PREPARED.epub \
  --source-language en \
  --json
```

The prepare command returns exit code 2 with
`status: source_review_required` after writing a valid candidate. The nonzero
code is deliberate: opening an EPUB does not prove PDF reading order or figure
placement. Review the pages reported in `complex_layout_pages`, every chapter
opening, and representative front matter, body, figures, notes, and back matter
before passing `PREPARED.epub` to `bookstudio start`.

## Routing and limitations

`text_layer_sufficient` permits semantic preparation. `mixed_or_sparse` stops
for page-level repair or reviewed OCR. `image_only` stops with
`PDF_OCR_REQUIRED`. Encrypted inputs are rejected; the adapter never passes a
DRM-bypass option to Poppler.

The runtime invokes optional system Poppler tools but adds no Python package
dependency. OCR is intentionally outside the current boundary because correct
language packs, confidence handling, page reconstruction, and human review are
product decisions. Fixed-layout reproduction, complex tables, equations,
handwriting, and exact typography are likewise not claimed.

## Safety and determinism

- PDF, Poppler XML, and extracted images must be regular non-symlink files.
- Source hashes are rechecked across inspection, conversion, and atomic output
  promotion.
- Different existing outputs are preserved and rejected with
  `PDF_OUTPUT_EXISTS`; byte-identical reruns are idempotent.
- XML and image sizes are bounded, image paths cannot escape the conversion
  workspace, and only recognized PNG/JPEG image bytes are packaged.
- ZIP timestamps, entry order, metadata identity, page anchors, and filenames
  are deterministic.
- Provenance lives unmanifested in `META-INF/bookstudio-source.json`, as EPUB
  container metadata rather than publication content.

Synthetic tests cover routing, source mutation, path safety, collision safety,
deterministic bytes, image preservation, bookmark-driven structure, page
anchors, EPUB inspection/block extraction, and handoff into a guided project.

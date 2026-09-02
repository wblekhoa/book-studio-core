# Images and localization

Use this reference only when the EPUB contains images or the user asks for
image text, annotations, localized companions, or market-specific visuals.

## Choose treatment image by image

Audit the image in its surrounding chapter and classify it:

- `original_only`: no meaningful source-language text, a logo/brand whose
  identity should remain unchanged, decorative art, or an image whose meaning
  is already clear;
- `annotation`: the original should remain primary and a short translated
  explanation is sufficient;
- `original_plus_companion`: meaningful UI, diagram labels, dialogue, or other
  embedded text needs a localized visual to remain easy to read.

The intake policy sets the permitted ceiling; it does not require translating
every eligible image. Prefer the least invasive treatment that preserves
understanding. Do not alter an existing approved AI-generated companion unless
the user asks for a revision.

Apply the same audit to the front matter. Title pages, endorsements, prefaces,
introductions, and opening illustrations can contain meaningful labels or full
captions even when they were not selected for the pilot. Inspect raster text
visually; inspect SVG `<text>` and accessible attributes as text; and record an
explicit `original_only`, `annotation`, or `original_plus_companion` decision.
Do not treat a decorative-looking filename, a short alt value, or placement
before chapter one as proof that localization is unnecessary.

## Preserve provenance and canvas

The source EPUB is read-only and its original image remains in the output.
Localized artwork is additive. The Core manifest path conservatively displays
the original first and the companion after it at the same apparent size. Store
the companion under `PROJECT/assets/localized/` as PNG or JPEG and preserve the
exact source pixel dimensions. Do not crop, stretch, change aspect ratio, or
replace the source asset.

Order and relative display size are book-specific visual decisions, not a
universal translation rule. If the approved treatment makes the localized
visual primary or keeps a smaller original in a padded block afterward, the
manifest-only Core path is insufficient. Use a project-owned deterministic
postprocessor and stylesheet, preserve both source and same-canvas companion,
and approve that exact path in the rendered pilot before applying it book-wide.

Use an image editing or generation capability only when it is available,
authorized, and legally appropriate. Preserve the author's composition and
meaning; change only the text or market-specific detail required by the agreed
policy. If fidelity, rights, or legibility cannot be established, use an
annotation or keep the original rather than inventing artwork.

Register one record per source image in
`PROJECT/assets/image-manifest.json`:

```json
{
  "schema_version": 1,
  "images": [
    {
      "source_path": "EPUB/images/plain.png",
      "policy": "original_only"
    },
    {
      "source_path": "EPUB/images/diagram.png",
      "policy": "annotation",
      "annotation": "A concise translated explanation."
    },
    {
      "source_path": "EPUB/images/dialogue.png",
      "policy": "original_plus_companion",
      "companion": "assets/localized/dialogue-target.png",
      "annotation": "Optional context that the image itself cannot convey."
    }
  ]
}
```

Use exact logical source paths from the EPUB, not absolute local paths. The CLI
validates file ownership, PNG/JPEG format, source existence, and same-canvas
dimensions. Never weaken those checks to make an asset pass. Because this
manifest shapes editorial packets, create or update it before completing the
pilot; afterward, discard old responses and refresh affected cached pilot rows
with newly emitted packets.

## Packet evidence

When an image decision belongs to a translated block, use only the documented
optional row shapes:

```json
{
  "image_annotations": [
    {
      "source_path": "EPUB/images/diagram.png",
      "annotation": "A concise translated explanation."
    }
  ],
  "image_companions": [
    {
      "source_path": "EPUB/images/dialogue.png",
      "companion": "assets/localized/dialogue-target.png",
      "annotation": "Optional supporting note."
    }
  ]
}
```

These records supplement the response row; they do not authorize creating a
companion outside the project or replacing an original asset.

## Visual review

For the pilot and final book, inspect at least:

- original and companion remain adjacent and in the approved order;
- both assets preserve the source canvas, and their apparent sizes match the
  approved hierarchy without distorting the author's composition;
- embedded target-language text is legible and semantically accurate;
- annotation is visibly secondary to the image and does not duplicate it;
- page breaks do not leave an empty localization block behind;
- logos and simple already-understood text were not localized without benefit;
- added local brands or websites are accurate, necessary, and clearly
  editorial rather than attributed to the author.

The core packages conservative default styles that keep localized image blocks
together and render annotations as secondary text. It still does not render or
judge aesthetics. Report visual QA as unverified unless the actual EPUB was
rendered and inspected.

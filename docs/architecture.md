# Architecture

Book Studio separates reusable engine code from every private book project.

The default guided orchestration is:

```text
start assessment (read-only while answers are missing)
  -> guided ownership marker, locked intake, and pilot_proposed
  -> explicit approval to pilot_active
  -> scope-bound next/apply packets
  -> derived pilot_review_required
  -> optional source-aligned pilot revision
  -> explicit acceptance to full_active
  -> remaining next/apply packets
  -> strict status and deterministic finish
```

Inspection facts determine which structured questions apply. Supplied answers
are omitted from later question lists, and image-policy questions exist only
when the source contains images. AI callers may handle the conversation and
extract answers, but the core validates and owns the resulting structured
state. Incomplete intake does not create the target project.

```text
source EPUB (read-only)
  -> archive preflight and inspection receipt
  -> stable source block map and explicit coverage contract
  -> bounded AI packet
  -> untrusted response validation
  -> canonical source-aligned cache
  -> deterministic EPUB candidate
  -> independent integrity and reproducibility gates
  -> private project output/final.epub
```

During a target-only build, block replacement retains structural source
artifacts such as nested anchor IDs, pagebreak markers, and footnote marker
wrappers. Visible linked text still belongs in validated `translation_xhtml`;
the builder does not reintroduce untranslated link labels. Leading translated
headings become the XHTML document title. EPUB 3 navigation links and EPUB 2
NCX labels that target those documents inherit the translated title. Bilingual
builds preserve the source title and navigation contract.

Generated editorial markup is paired with a deterministic, collision-safe
stylesheet resource registered in the OPF manifest and linked from spine
documents. The stylesheet supplies conservative secondary treatment for image
annotations and atomic layout for localized image blocks. This is a portable
baseline, not a visual-rendering gate; reader-specific inspection remains
separate evidence.

`bookstudio.toml` owns project policy. `state/intake.json` owns the locked
guided answers, and `state/pilot.json` owns the exact source document, source
hashes, target indexes, and canonical lifecycle status. A confirmed
`full_active` receipt also owns a closed policy identity: a SHA-256 of the
canonical normalized language, output, full sorted profile, batching, prompt,
and quality policy plus hashes of glossary bytes and the optional production
brief, image manifest, and reference notes. The receipt stores none of those
open-ended policy values. Loading accepted state recomputes the hashes, so later policy
drift fails closed without editing the receipt. The block map owns source
identity and block hashes. The glossary owns stable terminology. The cache owns
accepted translations. `assets/image-manifest.json` owns image treatment.
Coverage owns intentional exclusions. Release receipts describe outputs but
never redefine their inputs.

Until acceptance, pilot loads require the config's source/target languages,
output mode, and complete resolved profile to equal the locked intake. This
prevents a manual config edit from changing the reviewed product silently;
material intake-policy changes start a new guided project. After acceptance,
the broader content-free policy identity remains the drift authority.

Every persisted pilot is revalidated against a complete, source-bound locked
intake and a fresh inspection. Selection is recomputed and must match the exact
winning document, targets, eligible count, facts, and reason codes. The
persisted full block map must also equal a fresh deterministic extraction in
its complete document order and block content; coverage exclusions remain only
in `coverage.json`. Guided ownership evidence without `state/pilot.json` is an
invalid state, never a legacy fallback. Restart exact-compares the complete
locked intake, inspection, and full block map with type-sensitive canonical JSON
identity, validates exact coverage shape, and preflights every present restart
input before reconstructing any missing artifact. The read-only preflight set is
the exact ownership markers, config, locked intake, inspection, full block map,
coverage, pilot state, its scoped cache, optional image manifest and localized
companions, the optional production-brief node, plus JSON syntax for optional
reference notes. Glossary prose has no
restart-time semantic validator, while packets, outputs, and reports are
downstream products rather than restart inputs. A node-shape gate runs before
artifact reads: every lexically present singleton is a non-symlink regular file,
and `state`, `source-blocks`, `packets`, `cache`, `assets`, `assets/localized`,
`output`, and `reports` are non-symlink directories when present. Broken
symlinks fail the same gate. The caller's project root is resolved before this
check, so a root-level alias still opens the same owned project. This validator
is shared by guided restart and every config load; canonical cache access calls
it again immediately before reading or writing accepted translations.

The public core never contains book payloads. A private project contains the
configuration, glossary, packets, cache, localized assets, reports, and output.
AI exchange is manual in this version: `next` emits JSON and `apply` accepts
JSON. There is no bundled model/provider client and no visual pilot renderer.
Any future adapter must preserve that same boundary.

The canonical cache validator binds every row to the prepared source hash and
global coverage target, requires one unique `(source_path, block_index)` with
the exact source hash and accepted row schema, and rejects empty or malformed
translations. Every nonempty row also requires its 64-hex packet ID and a
content-free translation-context hash covering policy, prompt, glossary,
the optional production brief, reference notes, and image manifest; missing
metadata cannot downgrade a row to legacy trust. Packet IDs additionally bind
the source name and whole-file hash,
target hashes, and exact neighboring context hashes and roles. Packet selection
and guided pilot completion count only rows from the current context; after
pre-acceptance context drift, fresh packets can explicitly revise existing
pilot rows instead of allowing stale work to pass. A caller holding an old
`ProjectConfig` cannot combine it with a changed on-disk config: the context
boundary returns `CONFIG_STALE`. Optional image rows pass the same exact
source-reference,
project-owned path, companion-existence, and same-canvas validation during
apply and every strict cache read. Packet skipping and pilot completion use
that same validated index. Strict coverage/status and build/finish also consume
it before output creation. Before `full_active`, valid cache rows outside the
exact pilot targets also fail; after acceptance, other globally valid rows are
permitted.

Normal response application is append-only and collision-safe. The explicit
pilot revision operation may atomically replace an existing row only while the
validated lifecycle is `pilot_active` or derived `pilot_review_required`; exact
pilot scope, packet context, and source hashes are still enforced. It cannot
create new cache rows and is unavailable after acceptance.

Stable Python interfaces live under `bookstudio.config`, `bookstudio.project`,
`bookstudio.epub`, `bookstudio.translation`, `bookstudio.images`, and
`bookstudio.safety`. The CLI is an orchestration layer over those owners.

`bookstudio.compat` preserves byte parity for the pre-v0.1 private cache format.
It is not the beginner workflow and contains no book payload or private path.
The compatibility code remains intentionally checksum-aligned with the legacy
rollback adapters until a separately approved thin-wrapper migration removes
the temporary duplication. Direct `init` projects have no pilot file and keep
that legacy full-scope command behavior. Guided `start` adds
`.bookstudio-guided`; a locked `state/intake.json` remains a compatibility
ownership marker for guided projects created before that marker existed.
For a new guided project, the guided marker is the first ownership write. A
directory containing only that exact marker is the one recoverable pre-scaffold
state; adding any unrelated entry makes the directory unowned and unwritable.
Matching restarts validate and preserve every present canonical artifact, and
reconstruct only missing artifacts after an interrupted marked start.

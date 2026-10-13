# Book Studio Core

Book Studio Core is a local, provider-neutral workflow for translating EPUB
books and supported PDF sources with AI while keeping source text, editorial
decisions, and generated books in a private project directory. The Python
runtime uses only the standard library; it does not call a model or upload a
book. Optional local Poppler tools power the fail-closed PDF Source Gateway.

The translation workflow is language-neutral and has been dogfooded most deeply on English
to Vietnamese. It supports target-only and bilingual output, bounded
chapter-level AI packets, glossary and reference context, safe inline XHTML,
original images, image annotations, and same-canvas localized companions.

> **Personal-use license:** this source-available project supports private
> copies for the user's own reading, study, accessibility, or personal
> research. Generated book artifacts must not be sold, monetized, published,
> uploaded, shared, redistributed, or retained as a collection for other
> people. Private local storage is allowed only as needed for the user's own
> use. Read the full
> [personal use and rights boundary](skills/book-translation/references/personal-use-and-rights.md)
> before processing a book.

## Install

### Codex plugin (bundled engine)

Requires Python 3.11+ and a Codex version with `codex plugin` support.
Clone this repository, register its marketplace, then install Book Studio:

```bash
git clone https://github.com/wblekhoa/book-studio-core.git
cd book-studio-core
codex plugin marketplace add .
codex plugin add book-studio@book-studio
```

Start a new Codex thread, select Book Studio, and ask: “Help me translate this
book. Ask about the choices I haven't specified and prepare a sample first.”
The plugin bundles its matching engine, so no pip, pipx, API key, or separate
`bookstudio` install is needed. Python is still required. Optional Poppler
tools are needed only for PDF preparation. Rendering and image generation use
the tools available in your AI environment; neither is bundled here.

See [plugin installation and maintenance](docs/codex-plugin.md) for updates,
verification, and troubleshooting. The standalone CLI below remains supported.

Python 3.11 or newer is required. Install the CLI directly from GitHub:

```bash
pipx install git+https://github.com/wblekhoa/book-studio-core.git
bookstudio doctor --json
```

If `pipx` is unavailable, use an isolated virtual environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install git+https://github.com/wblekhoa/book-studio-core.git
bookstudio doctor --json
```

To run a checkout without installing it:

```bash
PYTHONPATH=src python3 -m bookstudio doctor --json
PYTHONPATH=src python3 -m bookstudio --help
```

## Add the AI skill

The portable [`book-translation` skill](skills/book-translation/SKILL.md) adds
the conversational and reader-quality layer: it discovers missing goals,
explains meaningful choices, proposes a representative text and visual pilot,
drives the bounded packet loop, and audits the final EPUB for editorial,
navigation, image, and rendering gaps that structural coverage cannot prove.

From inside Codex, the shortest first-time setup is to ask:

```text
Use $skill-installer to install https://github.com/wblekhoa/book-studio-core/tree/main/skills/book-translation
```

Install the CLI separately with the command above. For a cloned checkout, the
bundled installer handles first install and safe updates atomically:

```bash
git clone https://github.com/wblekhoa/book-studio-core.git
cd book-studio-core
pipx install .
python3 skills/book-translation/scripts/install.py --dry-run --json
python3 skills/book-translation/scripts/install.py --json
python3 skills/book-translation/scripts/install.py --check --json
```

An update moves the previous installed skill to a recoverable timestamped
backup and verifies exact tree parity before reporting success. The scripts use
only the Python standard library.

Then ask naturally, for example: `Use $book-translation to help me translate
and refine this EPUB or PDF.` The skill does not bundle an AI provider, OCR
engine, Poppler, or visual renderer and does not bypass the CLI's safety gates; other
agents can use the same `SKILL.md` and references when they support directory-
based skills.

Root and nested `--help` output explains every advertised command and its core
inputs. Placeholder commands that have no implementation are not exposed.

## PDF Source Gateway

PDFs enter through a separate preparation boundary before the guided EPUB
workflow. `doctor` reports the required optional Poppler tools but never
installs them:

```bash
bookstudio doctor --json
bookstudio pdf inspect "/path/to/source.pdf" --json
bookstudio pdf prepare "/path/to/source.pdf" \
  --output "/path/to/prepared.epub" \
  --source-language en \
  --json
```

Inspection returns `text_layer_sufficient`, `mixed_or_sparse`, or `image_only`
without returning extracted prose. Only the first class is prepared
automatically. Successful preparation intentionally returns exit code 2 with
`status: source_review_required`: compare the original PDF and prepared EPUB
before translation, especially every reported complex-layout page. Scans,
sparse extraction, encrypted sources, OCR, exact fixed-layout reproduction,
tables, and equations remain fail-closed rather than being silently guessed.
See [PDF source preparation](docs/pdf-source-preparation.md) for the full
receipt, review, and recovery contract.

## Guided path

Create a project outside the public source tree. The source EPUB stays in
place and is opened read-only. For PDF input, first produce and review the
intermediate EPUB using the gateway above. Start without an answers file first:

```bash
PYTHONPATH=src python3 -m bookstudio start ../book-project \
  --source "/path/to/source.epub" \
  --json
```

When required decisions are missing, `start` exits with code 2, returns
structured questions, and does not create the target project. An AI caller can
rephrase those questions conversationally, extract the user's replies into a
JSON object keyed by question ID, and rerun `start` with that file:

Without `--json`, the terminal view numbers every question and shows its stable
answer key, available choices, and recommendation when one exists. Human-facing
errors also include the same recovery action exposed by the JSON contract.

```bash
PYTHONPATH=src python3 -m bookstudio start ../book-project \
  --source "/path/to/source.epub" \
  --answers answers.json \
  --json
```

Already answered decisions are not asked again. Every missing question includes
stable `accepted_values` and `recommendation` fields so an AI caller can explain
the available choices without inventing values. Questions about image text and
image annotations appear only when inspection finds raster resources or inline
vector/image references. A complete start prepares the project and returns
`workflow_status: pilot_proposed`. Guided projects also carry a dedicated
`.bookstudio-guided` ownership marker; `start` will not silently convert a
project created through direct `init`. If either that marker or a locked intake
exists, a missing `state/pilot.json` fails every pilot/translation/build scope
entry with `PILOT_STATE_MISSING`; only an unmarked direct-init project remains
legacy full scope.

Approve the proposed representative chapter scope, translate only its emitted
packets, and keep the full scope locked:

```bash
PYTHONPATH=src python3 -m bookstudio pilot approve ../book-project --json
PYTHONPATH=src python3 -m bookstudio next ../book-project --json
PYTHONPATH=src python3 -m bookstudio apply ../book-project response.json --json
```

Repeat the pilot `next`/`apply` pair for every emitted pilot packet. Stop only
when `next` exits with code 2 and `PILOT_REVIEW_REQUIRED`. Then review the
completed pilot and inspect its status. If editorial feedback requires changes,
submit only corrected, already-translated pilot rows before acceptance:

```bash
PYTHONPATH=src python3 -m bookstudio pilot status ../book-project --json
PYTHONPATH=src python3 -m bookstudio pilot revise ../book-project corrected-response.json --json
PYTHONPATH=src python3 -m bookstudio pilot accept ../book-project --confirm --json
```

`pilot revise` is restricted to exact pilot targets that already exist in the
validated cache. It cannot add untranslated rows and becomes locked as soon as
the pilot is accepted.

Pilot commands expose one canonical `status` field: `pilot_proposed`,
`pilot_active`, derived `pilot_review_required`, or `full_active`. Confirmed
acceptance stores only hashes derived from normalized policy values—not the
values themselves, source prose, or local paths—and later full-scope commands
fail with `PILOT_POLICY_STALE` if the accepted config, prompt version, private
production brief, glossary, reference notes, or image manifest changes.

Every emitted packet carries the bounded private `production-brief.md` when it
exists and is also bound to a content-free fingerprint of those
response-shaping inputs, the source file identity, and the exact neighboring
context shown to the model. Accepted cache rows retain only that fingerprint
and their packet ID; rows missing either identity fail closed. If glossary,
reference, image, or prompt context changes before pilot acceptance, old rows
stop counting as current: discard old response files, request fresh packets,
use `pilot revise` for rows already in cache, and use normal `apply` for targets
that have never been translated. Review the refreshed pilot before accepting
it. Long-lived API callers must also reload `bookstudio.toml` after it changes;
a stale in-memory config is rejected with `CONFIG_STALE`.

Only after acceptance, repeat `next` and `apply` for the remaining full-scope
packets, then run the strict local gate:

```bash
PYTHONPATH=src python3 -m bookstudio status ../book-project --json
PYTHONPATH=src python3 -m bookstudio finish ../book-project --json
PYTHONPATH=src python3 -m bookstudio verify ../book-project --json
```

In short: `start -> answer missing questions -> pilot approve -> next/apply ->
pilot review/revise/accept -> next/apply remaining -> finish`. The CLI records
and enforces the pilot lifecycle; it does not render a visual pilot preview or
call an AI provider.

Rerunning `start` with the same source and locked answers is safe. A completed
guided project is read without rewriting its config, glossary, intake,
inspection, block map, coverage, or pilot receipt. If a marked guided start was
interrupted, only missing artifacts are reconstructed; present artifacts are
validated and preserved. Before reconstructing any file, `start` validates every
present restart input. The exact boundary is: both ownership markers, config,
locked intake, inspection, full block map, coverage, pilot, canonical cache,
optional image manifest plus localized companions, optional production-brief
node, and JSON syntax for optional reference notes. Type-sensitive canonical
JSON comparison covers the complete
locked intake, inspection, and full block map; config, coverage, pilot, cache,
and image state use their existing schema validators. Altered, extra, or
Boolean-for-number fields therefore fail without creating a new pilot or
another missing receipt. Before those value checks, every lexically present
singleton must be a non-symlink regular file and every managed parent must be a
non-symlink directory; broken symlinks count as present and fail closed. The
requested project root is still resolved first, so an alias to the whole owned
project remains supported. The same managed-node check runs whenever a project
config is loaded and immediately before canonical cache writes, so a later
command cannot redirect state through an internal symlink. Free-form glossary
text is preserved without a new semantic gate; transient packets and downstream
output/report files are not restart inputs.

See [guided intake](docs/guided-intake.md) for the question and state contracts.

### Review page

At any stage, write a private review page and open it in a browser:

```bash
PYTHONPATH=src python3 -m bookstudio review ../book-project --json
```

The page at `reports/review.html` shows where the project is, translation
progress per document, the sample chapter beside its source, the recorded
choices, and whether the final EPUB still matches its gate receipt. It ends
with the exact next command. The page is a read-only snapshot: rerun the
command to refresh it. It has no script, loads nothing from the network, and
stays inside the private project. Do not share it, because it contains book
text.

### Drafts and post-build edits

When whole chapters are drafted ahead, apply them through the same packet gates:

```bash
PYTHONPATH=src python3 -m bookstudio apply-drafts ../book-project drafts.json --json
```

The command checks every row first. It then stops at the sample review, at the
first block without a draft, or when the scope is complete.

To correct the built book (wording, a contents page, CSS, or a cover mark you
are allowed to add), declare the change in `../book-project/edits.json`. Use
`replace_text` with an exact `count`, `replace_member` pinned to the built
member's `base_sha256`, or `add_member`. Each replacement file lives inside the
project and is pinned by `sha256`. `build` and `finish` apply these operations,
so the gate certifies the edited book. Never change `output/final.epub` after
`finish`.

## Expert compatibility path

`init` remains available for callers that already own every project decision
and need the original full-scope v0.1 behavior:

```bash
PYTHONPATH=src python3 -m bookstudio init ../book-project \
  --source "/path/to/source.epub" \
  --target vi \
  --output-mode target_only \
  --json
PYTHONPATH=src python3 -m bookstudio inspect ../book-project --json
PYTHONPATH=src python3 -m bookstudio prepare ../book-project --json
```

`next` emits one bounded packet. Give that JSON to the AI system of your
choice, save its schema-matching response locally, and apply it:

```bash
PYTHONPATH=src python3 -m bookstudio next ../book-project --json
PYTHONPATH=src python3 -m bookstudio apply ../book-project response.json --json
PYTHONPATH=src python3 -m bookstudio status ../book-project --json
```

Repeat until `next` exits with code 3. Then build, verify, or run the combined
local quality gate:

```bash
PYTHONPATH=src python3 -m bookstudio build ../book-project --json
PYTHONPATH=src python3 -m bookstudio verify ../book-project --json
PYTHONPATH=src python3 -m bookstudio finish ../book-project --json
```

`finish` checks strict coverage, builds twice, requires byte identity, validates
the candidate independently, and only then promotes `output/final.epub`. It
does not publish or upload anything.

For target-only output, the builder preserves nested source anchors,
pagebreak markers, and validated cross-references while replacing visible
prose. It derives each translated XHTML document title from its leading
translated heading or heading pair, and uses those titles for matching EPUB 3
navigation links and EPUB 2 NCX labels. The EPUB 3 navigation document receives the configured
`navigation_label`; Vietnamese projects default to `Mục lục`, while other
languages retain the source navigation heading unless the profile overrides
it. Bilingual output keeps source document and navigation titles.

The build also packages a collision-safe `bookstudio.css` and links it from
spine documents. Its conservative defaults keep image annotations visually
secondary and keep localized image blocks together without altering source
image bytes or companion canvas dimensions. Visual review in an EPUB reader is
still required because the CLI does not render a pilot or judge typography.

## Verify the core

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m bookstudio public-audit . --json
```

The audit is allowlist-first and blocks book binaries, project outputs,
personal paths, account addresses, secret-like values, unapproved binary
assets, symlinks, and unknown top-level paths. It traverses generated cache
directories instead of trusting their names, and rejects compiled `.pyc`
artifacts instead of silently ignoring them.

## Data and copyright boundary

Only reusable code, documentation, and synthetic fixture builders belong in
this tree. Source books, translations, screenshots, localized artwork, caches,
packets, and receipts stay in private project directories. Book Studio Core
supports generated book artifacts only for private, personal, non-commercial
use and does not support their publication, sharing, redistribution, shared
archiving, or monetization. Users are responsible for having the right to
process every input. See the
[personal use and rights boundary](skills/book-translation/references/personal-use-and-rights.md).

Book Studio Core is source-available under the
[Book Studio Personal Use License 1.0](LICENSE), not an open-source license.
Commercial use of the software requires a separate written commercial license
from the software Licensor and binding written authorization from every
applicable rights holder for the material being processed. Neither permission
substitutes for the other. Versions previously distributed under MIT retain the
terms attached to those earlier distributions; the current license is not
retroactive.

Version 0.1.0 is an alpha-quality command-line foundation. Keep private book
data outside this repository and review generated translations before personal
use. See
[architecture](docs/architecture.md), [AI packets](docs/ai-packets.md),
[guided intake](docs/guided-intake.md), and [safety](docs/safety.md).

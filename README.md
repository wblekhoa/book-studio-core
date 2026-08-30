# Book Studio Core

Book Studio Core is a local, provider-neutral workflow for translating EPUB
books with AI while keeping source text, editorial decisions, and generated
books in a private project directory. The runtime uses only the Python standard
library; it does not call a model or upload a book.

The workflow is language-neutral and has been dogfooded most deeply on English
to Vietnamese. It supports target-only and bilingual output, bounded
chapter-level AI packets, glossary and reference context, safe inline XHTML,
original images, image annotations, and same-canvas localized companions.

## Install

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
the conversational layer: it discovers missing goals, explains meaningful
choices, proposes a representative pilot, waits for explicit pilot acceptance,
and then drives the bounded packet loop. For one setup that installs both the
CLI and skill in Codex:

```bash
git clone https://github.com/wblekhoa/book-studio-core.git
cd book-studio-core
pipx install .
mkdir -p ~/.codex/skills
cp -R skills/book-translation ~/.codex/skills/
```

Then ask naturally, for example: `Use $book-translation to help me translate
this EPUB.` The skill does not bundle an AI provider or bypass the CLI's safety
gates; other agents can use the same `SKILL.md` and references when they support
directory-based skills.

Root and nested `--help` output explains every advertised command and its core
inputs. Placeholder commands that have no implementation are not exposed.

## Guided path

Create a project outside the public source tree. The source EPUB stays in
place and is opened read-only. Start without an answers file first:

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
fail with `PILOT_POLICY_STALE` if the accepted config, prompt version, glossary,
reference notes, or image manifest changes.

Every emitted packet is also bound to a content-free fingerprint of those
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
optional image manifest plus localized companions, and JSON syntax for optional
reference notes. Type-sensitive canonical JSON comparison covers the complete
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
packets, and receipts stay in private project directories. Users are
responsible for having the right to process their inputs and distribute their
outputs.

Book Studio Core is released under the [MIT License](LICENSE). Version 0.1.0 is
an alpha-quality command-line foundation: keep private book data outside this
repository and review generated translations before distribution. See
[architecture](docs/architecture.md), [AI packets](docs/ai-packets.md),
[guided intake](docs/guided-intake.md), and [safety](docs/safety.md).

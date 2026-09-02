# AI packet contract

`bookstudio next PROJECT --json` returns schema version 1. One packet contains
targets from only one source document and never more than `max_blocks`.

For a guided project, packet scope is also bound to the validated pilot state.
Before approval, `next` returns `PILOT_APPROVAL_REQUIRED`. During the pilot,
every emitted block belongs to the one selected source document and exact
target set. Once those targets are present in canonical cache, `next` returns
`PILOT_REVIEW_REQUIRED` until `pilot accept --confirm` records the explicit
decision. Only then can packets contain remaining full-scope targets. A direct
`init` project has no pilot state and retains the original packet behavior.
Pilot status JSON has one canonical `status` field: `pilot_proposed`,
`pilot_active`, derived `pilot_review_required`, or `full_active`.
Before acceptance, `bookstudio pilot revise PROJECT RESPONSE` may replace only
rows already accepted inside the exact pilot target set. It uses the same
response, source-hash, optional-field, and cache validators as `apply`; it never
adds a missing row and is unavailable once full scope is unlocked.

Each translatable block carries `source_path`, `block_index`, role, source text,
and `source_sha256`. Neighboring context is explicitly marked
`translate: false`. The packet includes the book profile, the optional bounded
private `production_brief` when that file exists, only glossary terms matched
to this batch, reference notes whose `source_path` matches the current document,
and an exact response schema.

The packet ID binds the source filename and whole-file SHA-256, exact target
blocks, neighboring context block roles and hashes, and a content-free context
fingerprint covering project policy, prompt version, glossary bytes,
chapter-reference notes, the optional production brief when present, and the
optional image manifest. A response emitted
before any of those inputs changed is stale even when its target block hash is
unchanged. The fingerprint contains hashes only; it never stores source prose,
reference prose, or local paths in lifecycle receipts. API callers cannot mix a
previously loaded config with a newer on-disk `bookstudio.toml`; operations fail
with `CONFIG_STALE` and require a reload.

A minimal response is:

```json
{
  "schema_version": 1,
  "packet_id": "copy-from-packet",
  "source_document": "text/chapter.xhtml",
  "translations": [
    {
      "block_index": 0,
      "source_sha256": "copy-from-block",
      "translation": "Natural target-language translation"
    }
  ]
}
```

The top level contains exactly `schema_version`, `packet_id`,
`source_document`, and `translations`. Each translation row contains exactly
the required `block_index`, `source_sha256`, and `translation` fields plus only
the documented optional fields: safe `translation_xhtml`, `explanation`,
`image_annotations`, `image_companions`, and explicitly labeled
`market_contexts`. Schema version and block indexes are JSON integers—not
Booleans or floats. Structural envelope, key, and type errors fail before
target or cache access. Unknown or duplicate indexes, empty translations,
stale hashes, unsafe XHTML/images, stale packets, scope drift, and overwrite
collisions may consult current project state but still fail before cache
mutation. Only normal `apply` or explicit pre-acceptance `pilot revise` writes
accepted model output to cache.

Before `next` decides that a block is already translated, it validates the
complete persisted block map against fresh deterministic extraction, then
validates the entire cache against the current source and global coverage.
Every row must use the documented required and optional keys, exact
integer/string types, a nonempty translation, the canonical source hash, and a
unique global target. Every nonempty row must retain a validated 64-hex packet
ID and context hash; removing, nulling, or partially supplying that pair is an
invalid cache row, not a legacy downgrade. Only rows whose context hash is
current count as complete in a guided workflow; stale rows are emitted again
for a fresh translation instead of silently satisfying the pilot.
Malformed, duplicate, stale, extra, or pilot-out-of-scope rows return a
corrective `CACHE_*` error without changing the cache. Normal `apply` never
overwrites a differing row; the explicit pilot-only revision path is the sole
pre-acceptance exception. After a context change, use a fresh packet with
`pilot revise` for targets already present in cache and normal `apply` only for
targets not yet present. If one packet contains both kinds, submit separate
schema-valid responses through the corresponding commands. The pilot receipt and
acceptance gate use the same validated row index, so invalid rows cannot hide
unfinished pilot work. Optional image annotations and companions are also
revalidated through the same exact image-policy gate used by `apply`, including
safe source references, project-owned companion paths, file existence, and
same-canvas dimensions. Strict coverage/status and the build/finish path consume
that same validated index, so malformed optional data or schema drift fails
before an EPUB or release receipt is created.

Exit code 2 means valid but incomplete coverage. Exit code 3 from `next` means
no eligible untranslated block remains.

Guided intake questions are a separate structured contract from translation
packets. Each question carries stable `id`, `accepted_values`, and
`recommendation` fields. An AI caller may rephrase the prompt, but it must
extract the user's answer under that ID and use only an accepted enum value
where one is supplied. The caller should send existing answers back on the
next assessment; Book Studio does not repeat answered questions, and it omits
image questions only when inspection finds neither image resources nor inline
image/vector references. This repository does not include an AI provider
client, and responses remain local JSON files.

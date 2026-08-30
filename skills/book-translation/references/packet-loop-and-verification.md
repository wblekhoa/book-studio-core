# Packet loop and verification

Use this reference for every AI packet exchange and the final local gate.

## Translate one bounded packet

Request the next allowed work:

```bash
bookstudio next PROJECT --json
```

The packet contains one `source_document`, at most the configured batch size,
and an exact `response_schema`. Produce a local JSON file with exactly these
top-level keys:

```json
{
  "schema_version": 1,
  "packet_id": "copy exactly from the packet",
  "source_document": "copy exactly from the packet",
  "translations": [
    {
      "block_index": 0,
      "source_sha256": "copy exactly from the target block",
      "translation": "Natural target-language text"
    }
  ]
}
```

Translate only packet `blocks` whose `translate` value is true. Copy
`block_index` and `source_sha256` without conversion or normalization. Each row
may additionally contain only `translation_xhtml`, `explanation`,
`image_annotations`, `image_companions`, and `market_contexts`, and only when
the active policy and content justify them. Do not add prose around the JSON.

Apply it through the sole cache mutation path:

```bash
bookstudio apply PROJECT RESPONSE.json --json
```

Then request a fresh packet. Never reuse an old packet after applying work or
changing approved inputs. Do not open or patch `cache/translations.json` to
repair a response.

Packet IDs bind the source identity, neighboring context, policy, prompt
version, glossary, matching reference notes, and the optional image manifest
through content-free hashes. If one changes during the pilot, `next` re-emits
targets whose cached context is stale. Use the fresh packet with `pilot revise`
for rows that already exist and `apply` for targets that do not. A stale packet
or old response must be regenerated, never edited to mimic the new ID. If an
API caller reports `CONFIG_STALE`, reload the project config before requesting
or applying any packet.

At the pilot review boundary only, user-requested corrections to rows already
in cache use `bookstudio pilot revise PROJECT CORRECTED_RESPONSE.json --json`.
This is the sole overwrite path; it does not add untranslated rows and is
unavailable after pilot acceptance.

## Interpret boundaries correctly

- Exit code 2 from `start` means decisions remain.
- Exit code 2 with `PILOT_APPROVAL_REQUIRED` means the user has not approved the
  proposal.
- Exit code 2 with `PILOT_REVIEW_REQUIRED` means the pilot is complete and must
  be reviewed and explicitly accepted.
- Exit code 3 with `NO_WORK_REMAINS` means no eligible untranslated block
  remains in the currently authorized full scope.
- Stale packet/source/policy errors, cache collisions, unknown fields, unsafe
  XHTML, out-of-scope targets, or image failures are evidence to correct the
  response or state; they are never reasons to bypass a gate.

If an `apply` fails, preserve the error receipt, diagnose the named invariant,
request a fresh packet when instructed, and regenerate only the rejected local
response. After the same failure twice, reassess rather than patching around the
validator.

## Complete the whole book

After the pilot is explicitly accepted, repeat `next` and `apply` until full
scope returns `NO_WORK_REMAINS`. Then run each gate separately:

```bash
bookstudio status PROJECT --json
bookstudio finish PROJECT --json
bookstudio verify PROJECT --json
```

`status` must report complete, valid coverage. `finish` builds twice, requires
byte-identical output, independently validates the candidate, and only then
promotes `PROJECT/output/final.epub`. `verify` must independently pass against
that final artifact. One aggregate success never hides a failed command.

Where local rendering tools are available, inspect representative text-heavy,
image-heavy, and boundary pages in the final EPUB. Keep that receipt separate:
the core proves structural integrity and reproducibility, not typography,
translation quality, accessibility, or legal permission.

Report to the user:

- the final local EPUB path;
- target language and output mode actually used;
- pilot acceptance and full coverage status;
- `finish` reproducibility and `verify` integrity evidence;
- whether visual review occurred and what was sampled;
- any unresolved rights, terminology, image, or reader-app risks.

Do not upload, publish, tag, or release the output without a separate explicit
request and the relevant rights check.

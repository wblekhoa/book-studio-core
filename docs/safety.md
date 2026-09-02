# Safety model

## Filesystem

The source EPUB is read-only. Project initialization refuses a nonempty folder
without `.bookstudio-project`. Configuration, cache, build, and receipt writes
use a temporary sibling followed by atomic replacement. A candidate never
replaces `output/final.epub` until coverage, integrity, and reproducibility all
pass.

Every config load validates the complete set of managed project directories and
singleton artifacts. Internal symlinks, broken symlinks, files where a managed
directory belongs, and directories where a managed file belongs fail closed.
A symlink alias to the whole owned project is supported because the requested
root is resolved before these internal checks. Canonical cache reads and writes
repeat the validation immediately before access.

## Archives and EPUB structure

Preflight reads ZIP central-directory metadata before member content. Default
limits are 10,000 entries, 1 GiB total expanded bytes, 256 MiB for one expanded
entry, and a 1,000:1 compression ratio. Absolute paths, parent traversal,
backslashes, duplicate names, invalid container XML, and missing package or
spine resources fail closed.

Independent validation checks the package, manifest, spine, XHTML parsing,
duplicate IDs, internal files and fragments, navigation count, target language,
source-image hashes, localized assets, coverage, and deterministic ZIP facts.

## AI-authored content

Inline XHTML permits only `a`, `em`, `strong`, `span`, `sup`, `sub`, `br`, and
`code` with explicit safe attributes. Scripts, events, inline style, forms,
embeds, remote URLs, and executable URL schemes are rejected. Image companions
must live under `assets/localized`, exist, use PNG or JPEG, and exactly match
the original pixel canvas.

## Public boundary

`public-audit` is allowlist-first. It rejects book binaries, private project
directories, personal paths, account addresses, secret-like values, symlinks,
binary artwork, and unknown top-level content. `.gitignore` is only defense in
depth; it is not the publication boundary.

The scanner excludes only a real `.git` directory at the audited root as an
opaque directory. Nested `.git` names and symlinked root entries remain visible
to the gate. It walks cache and bytecode directories so a blocked file cannot
hide behind a conventional generated-folder name; individual `.pyc` artifacts
are publication violations. It recognizes macOS and Linux home paths plus
Windows user paths on any drive letter. CI runs the source-tree gate before
installation and again after tests; compilation checks run only in a temporary
copy so the audited checkout remains artifact-free.

The tool cannot determine whether a user has legal rights to a book. Users must
review copyright, privacy, provider, and distribution obligations for every
input and output.

The software license and supported book-processing workflow are aligned around
private, personal, non-commercial use. Generated books and localized assets
must not be published, uploaded, shared, redistributed, monetized, or stored as
a collection for other people. Private local storage needed for the user's own
reading, study, accessibility, or research remains allowed. Any commercial
exception requires separate written permission from both the software Licensor
and every applicable rights holder for the material being processed. The
complete operational boundary is documented in
[`personal-use-and-rights.md`](../skills/book-translation/references/personal-use-and-rights.md).

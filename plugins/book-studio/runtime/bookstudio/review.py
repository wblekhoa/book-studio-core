"""Read-only, self-contained HTML review page for one private project."""

from __future__ import annotations

import hashlib
import json
import shlex
from html import escape
from pathlib import Path
from typing import Any, Mapping

from .config import ProjectConfig, atomic_write_text
from .errors import BookStudioError
from .pilot import pilot_receipt
from .translation.cache import load_cache
from .translation.coverage import coverage_receipt


REVIEW_RELATIVE_PATH = "reports/review.html"
SAMPLE_BLOCK_LIMIT = 60
STAGES = (
    ("intake", "Choices"),
    ("pilot_proposed", "Sample proposed"),
    ("pilot_active", "Sample in translation"),
    ("pilot_review_required", "Sample review"),
    ("full_active", "Full book"),
    ("finished", "Finished"),
)
STAGE_HINTS = {
    "legacy": "Expert project without a sample gate. Continue translation, then finish.",
    "pilot_proposed": "Check that the proposed sample chapter is representative, then approve it.",
    "pilot_active": "The AI is translating the sample. Apply each packet response.",
    "pilot_review_required": "Read the sample below. Accept it to unlock the full book, or revise it first.",
    "full_active": "Translate the remaining blocks, then run the final gate.",
    "finished": "The final EPUB passed coverage, integrity and reproducibility gates.",
}


def _read_optional_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _canonical_blocks(file: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        block
        for block in file.get("blocks", [])
        if isinstance(block, dict)
        and block.get("canonical") is True
        and block.get("watermark") is not True
        and isinstance(block.get("block_index"), int)
    ]


def _cache_rows(cache: Mapping[str, Any]) -> dict[tuple[str, int], dict[str, Any]]:
    rows: dict[tuple[str, int], dict[str, Any]] = {}
    for path, entries in cache.get("files", {}).items():
        for row in entries if isinstance(entries, list) else []:
            if isinstance(row, dict) and isinstance(row.get("block_index"), int):
                rows[(path, row["block_index"])] = row
    return rows


def _stage(status: str, coverage: Mapping[str, Any] | None, release: Any) -> str:
    complete = bool(coverage and coverage.get("remaining") == 0)
    if complete and isinstance(release, dict) and release.get("status") == "pass":
        return "finished"
    return status


def _next_command(stage: str, project: str, coverage: Mapping[str, Any] | None) -> str:
    remaining = coverage.get("remaining") if coverage else None
    if stage == "pilot_proposed":
        return f"bookstudio pilot approve {project}"
    if stage == "pilot_review_required":
        return f"bookstudio pilot accept {project} --confirm"
    if stage == "finished":
        return f"bookstudio verify {project}"
    if stage in {"legacy", "full_active"} and remaining == 0:
        return f"bookstudio finish {project}"
    return f"bookstudio next {project}"


def _sample(
    pilot: Mapping[str, Any],
    block_map: Any,
    rows: Mapping[tuple[str, int], Mapping[str, Any]],
) -> tuple[str | None, list[dict[str, Any]]]:
    files = block_map.get("files", []) if isinstance(block_map, dict) else []
    by_path = {file.get("source_path"): file for file in files if isinstance(file, dict)}
    document = pilot.get("source_document")
    wanted: set[int] | None = None
    if document in by_path:
        wanted = {target["block_index"] for target in pilot.get("targets", [])}
    else:
        translated = [path for path in by_path if any(key[0] == path for key in rows)]
        candidates = translated or [path for path, file in by_path.items() if _canonical_blocks(file)]
        document = candidates[0] if candidates else None
    if document is None:
        return None, []
    pairs = []
    for block in _canonical_blocks(by_path[document]):
        if wanted is not None and block["block_index"] not in wanted:
            continue
        row = rows.get((document, block["block_index"]))
        if row is None:
            state = "missing"
        elif row.get("source_sha256") != block.get("text_sha256"):
            state = "stale"
        else:
            state = "done"
        pairs.append(
            {
                "index": block["block_index"],
                "role": block.get("role") or block.get("tag") or "",
                "source": block.get("text", ""),
                "translation": (row or {}).get("translation", ""),
                "state": state,
            }
        )
    return document, pairs[:SAMPLE_BLOCK_LIMIT]


def _documents(
    block_map: Any,
    contract: Any,
    rows: Mapping[tuple[str, int], Mapping[str, Any]],
    titles: Mapping[str, str],
) -> list[dict[str, Any]]:
    excluded = set(contract.get("excluded_files", [])) if isinstance(contract, dict) else set()
    result = []
    for file in block_map.get("files", []) if isinstance(block_map, dict) else []:
        path = file.get("source_path", "")
        blocks = _canonical_blocks(file)
        done = sum(
            1
            for block in blocks
            if rows.get((path, block["block_index"]), {}).get("source_sha256") == block.get("text_sha256")
        )
        result.append(
            {
                "path": path,
                "title": titles.get(path, ""),
                "blocks": len(blocks),
                "translated": done,
                "excluded": path in excluded,
            }
        )
    return result


def _percent(part: int, whole: int) -> int:
    return round(100 * part / whole) if whole else 0


STYLE = """
:root{--bg:#f7f6f2;--surface:#fff;--text:#1d1d1b;--muted:#6b6a64;--line:#e3e1d9;--accent:#2f6b4f;
--accent-soft:#e3efe8;--warn:#9a5b00;--warn-soft:#fbefd9;--bad:#a12b2b;--bad-soft:#f8e1e1;--code:#f0eee7}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--surface:#1e1e1c;--text:#ecebe6;--muted:#a4a29a;
--line:#34332f;--accent:#7cc39c;--accent-soft:#1f3329;--warn:#e7b25c;--warn-soft:#3a2d16;--bad:#f08a8a;
--bad-soft:#3d1f1f;--code:#2a2a27}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{max-width:1080px;margin:0 auto;padding:32px 16px 64px}h1{font-size:26px;margin:0 0 4px}
h2{font-size:17px;margin:0 0 12px}.muted{color:var(--muted)}section{background:var(--surface);
border:1px solid var(--line);border-radius:12px;padding:20px;margin-top:16px}
.steps{display:flex;flex-wrap:wrap;gap:6px;list-style:none;padding:0;margin:0 0 14px}
.steps li{padding:4px 10px;border-radius:999px;border:1px solid var(--line);font-size:13px;color:var(--muted)}
.steps li.done{background:var(--accent-soft);color:var(--accent);border-color:transparent}
.steps li.current{background:var(--accent);color:var(--surface);border-color:transparent;font-weight:600}
pre{background:var(--code);padding:10px 12px;border-radius:8px;overflow-x:auto;margin:8px 0 0;
font:13px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;user-select:all}
.bar{height:10px;background:var(--line);border-radius:999px;overflow:hidden;margin:8px 0}
.bar span{display:block;height:100%;background:var(--accent)}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:7px 8px;
border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:500}
th.num,td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
dl{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:6px 16px;margin:0}dt{color:var(--muted)}dd{margin:0;min-width:0;overflow-wrap:anywhere}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:12px 0;border-bottom:1px solid var(--line)}
.pair:last-child{border-bottom:0}.pair p{margin:4px 0 0;white-space:pre-wrap;overflow-wrap:anywhere}
.tag{font-size:12px;color:var(--muted)}.badge{font-size:12px;padding:1px 8px;border-radius:999px;margin-left:6px}
.badge.missing{background:var(--warn-soft);color:var(--warn)}.badge.stale{background:var(--bad-soft);color:var(--bad)}
.badge.ok{background:var(--accent-soft);color:var(--accent)}.empty{color:var(--muted);font-style:italic}
@media (max-width:640px){.pair{grid-template-columns:1fr}dl{grid-template-columns:minmax(0,1fr);gap:2px 0}dd{margin-bottom:8px}}
"""


def _render(context: Mapping[str, Any]) -> str:
    e = lambda value: escape(str(value), quote=True)  # noqa: E731
    stage = context["stage"]
    order = [key for key, _ in STAGES]
    position = order.index(stage) if stage in order else -1
    steps = []
    for index, (key, label) in enumerate(STAGES):
        css = "current" if index == position else "done" if index < position else ""
        steps.append(f'<li class="{css}">{e(label)}</li>')
    if stage == "legacy":
        steps = ['<li class="current">Expert project (no sample gate)</li>']

    coverage = context["coverage"]
    if coverage:
        translated, eligible = coverage.get("translated", 0), coverage.get("eligible", 0)
        progress = (
            f'<div class="bar" role="img" aria-label="{_percent(translated, eligible)}% translated">'
            f'<span style="width:{_percent(translated, eligible)}%"></span></div>'
            f"<p>{e(translated)} of {e(eligible)} eligible blocks translated "
            f"({_percent(translated, eligible)}%), {e(coverage.get('remaining', 0))} remaining.</p>"
        )
        if coverage.get("source_hash_mismatches"):
            progress += f'<p class="badge stale">{e(coverage["source_hash_mismatches"])} cached blocks no longer match the source.</p>'
    else:
        progress = '<p class="empty">Coverage is not available yet. Run the prepare step first.</p>'

    rows = "".join(
        f"<tr><td>{e(doc['title'] or doc['path'])}<div class=\"tag\">{e(doc['path'])}</div></td>"
        f"<td class=\"num\">{'excluded' if doc['excluded'] else 'no text' if not doc['blocks'] else str(doc['translated']) + ' / ' + str(doc['blocks'])}</td>"
        f"<td class=\"num\">{'' if doc['excluded'] else '—' if not doc['blocks'] else str(_percent(doc['translated'], doc['blocks'])) + '%'}</td></tr>"
        for doc in context["documents"]
    )
    documents = (
        f"<table><thead><tr><th>Document</th><th class=\"num\">Blocks</th><th class=\"num\">Done</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        if rows
        else '<p class="empty">No prepared documents yet.</p>'
    )

    labels = {"missing": ("missing", "Not translated yet"), "stale": ("stale", "Source changed"), "done": ("ok", "Translated")}
    pairs = []
    for pair in context["pairs"]:
        css, label = labels[pair["state"]]
        translation = (
            f"<p>{e(pair['translation'])}</p>" if pair["translation"] else '<p class="empty">Not translated yet</p>'
        )
        pairs.append(
            f'<div class="pair"><div><span class="tag">#{e(pair["index"])} · {e(pair["role"])}</span>'
            f'<p lang="{e(context["source_language"])}">{e(pair["source"])}</p></div>'
            f'<div><span class="tag">{e(context["target_language"])}</span>'
            f'<span class="badge {css}">{e(label)}</span>'
            f'<div lang="{e(context["target_language"])}">{translation}</div></div></div>'
        )
    sample_title = "Sample chapter" if context["is_pilot"] else "Translation sample"
    sample = (
        f"<p class=\"muted\">{e(context['sample_document'])}"
        f"{' (first ' + str(SAMPLE_BLOCK_LIMIT) + ' blocks)' if len(context['pairs']) >= SAMPLE_BLOCK_LIMIT else ''}</p>"
        + "".join(pairs)
        if pairs
        else '<p class="empty">No sample blocks to show yet.</p>'
    )

    choices = "".join(f"<dt>{e(key.replace('_', ' '))}</dt><dd>{e(value)}</dd>" for key, value in context["choices"])

    release = context["release"]
    if release:
        state = "ok" if release["current"] else "stale"
        text = "Matches the gate receipt" if release["current"] else "Changed since the gate ran: run finish again"
        final = (
            f"<dl><dt>Output</dt><dd>{e(release['output'])}</dd><dt>Reproducible</dt><dd>{'yes' if release['reproducible'] is True else 'no'}</dd>"
            f"<dt>Integrity</dt><dd>{e(release['integrity'])}</dd><dt>Declared edits</dt><dd>{e(release['edits'])}</dd><dt>SHA-256</dt><dd><code>{e(release['sha256'])}</code>"
            f'<span class="badge {state}">{e(text)}</span></dd></dl>'
        )
    else:
        final = '<p class="empty">The final gate has not run yet.</p>'

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:">
<meta name="referrer" content="no-referrer">
<title>{e(context['title'])} · Book Studio review</title><style>{STYLE}</style></head>
<body><main>
<p class="muted">Book Studio review · private, generated locally, read-only</p>
<h1>{e(context['title'])}</h1>
<p class="muted">{e(context['source_name'])} · {e(context['source_language'])} → {e(context['target_language'])} · {e(context['output_mode'])}</p>
<section aria-labelledby="h-stage"><h2 id="h-stage">Where the project is</h2>
<ol class="steps">{''.join(steps)}</ol>
<p>{e(STAGE_HINTS.get(stage, ''))}</p>
<p class="muted">Next step: ask the AI to continue, or run</p><pre>{e(context['next_command'])}</pre></section>
<section aria-labelledby="h-progress"><h2 id="h-progress">Progress</h2>{progress}{documents}</section>
<section aria-labelledby="h-sample"><h2 id="h-sample">{e(sample_title)}</h2>{sample}</section>
<section aria-labelledby="h-choices"><h2 id="h-choices">Choices</h2>
{'<dl>' + choices + '</dl>' if choices else '<p class="empty">No recorded choices.</p>'}</section>
<section aria-labelledby="h-final"><h2 id="h-final">Final book</h2>{final}</section>
<p class="muted">Regenerate with <code>{e('bookstudio review ' + context['project_arg'])}</code>. This page never changes the project.</p>
</main></body></html>
"""


def _release_state(config: ProjectConfig) -> tuple[Any, dict[str, Any] | None]:
    release_receipt = _read_optional_json(config.paths.reports / "release.json")
    if not (isinstance(release_receipt, dict) and release_receipt.get("status") == "pass"):
        return release_receipt, None
    final = (config.project_root / str(release_receipt.get("output", ""))).resolve()
    inside = config.paths.output.resolve() in final.parents
    current = inside and final.is_file() and hashlib.sha256(final.read_bytes()).hexdigest() == release_receipt.get("output_sha256")
    integrity = release_receipt.get("integrity", {})
    edits = release_receipt.get("edits")
    return release_receipt, {
        "output": release_receipt.get("output"),
        "sha256": release_receipt.get("output_sha256"),
        "reproducible": release_receipt.get("reproducible"),
        "integrity": "pass" if isinstance(integrity, dict) and integrity.get("passed") else "not recorded",
        "current": current,
        "edits": edits.get("applied", 0) if isinstance(edits, dict) else 0,
    }


def project_status(config: ProjectConfig) -> dict[str, Any]:
    """Read-only summary of stage, progress and next command; writes nothing."""
    pilot = pilot_receipt(config)
    has_map = (config.paths.source_blocks / "full-block-map.json").is_file()
    try:
        coverage = coverage_receipt(config, require_complete=False) if has_map else None
    except BookStudioError:
        coverage = None
    release_receipt, release = _release_state(config)
    stage = _stage(pilot["status"], coverage, release_receipt if release and release["current"] else None)
    return {
        "status": "pass",
        "schema_version": 1,
        "project": config.project_root.name,
        "workflow_status": stage,
        "translated": coverage.get("translated", 0) if coverage else 0,
        "eligible": coverage.get("eligible", 0) if coverage else 0,
        "remaining": coverage.get("remaining") if coverage else None,
        "final_matches_gate": bool(release and release["current"]),
        "next_command": _next_command(stage, shlex.quote(config.project_root.name), coverage),
        "hint": STAGE_HINTS.get(stage, ""),
        "message": f"{config.project_root.name}: {stage}.",
    }


def write_review(config: ProjectConfig) -> dict[str, Any]:
    """Render the review page from current state; only reports/review.html is written."""
    pilot = pilot_receipt(config)
    rows = _cache_rows(load_cache(config))
    block_map = _read_optional_json(config.paths.source_blocks / "full-block-map.json")
    contract = _read_optional_json(config.paths.source_blocks / "coverage.json")
    try:
        coverage = coverage_receipt(config, require_complete=False) if block_map is not None else None
    except BookStudioError:
        coverage = None
    intake = _read_optional_json(config.paths.intake)
    facts = intake.get("book_facts") if isinstance(intake, dict) else None
    facts = facts if isinstance(facts, dict) else {}
    titles = {
        doc.get("logical_path"): doc.get("title") or ""
        for doc in facts.get("documents", [])
        if isinstance(doc, dict)
    }
    title_values = facts.get("title") or []
    release_receipt, release = _release_state(config)
    stage = _stage(pilot["status"], coverage, release_receipt if release and release["current"] else None)
    project_arg = shlex.quote(config.project_root.name)
    document, pairs = _sample(pilot, block_map, rows)
    answers = intake.get("answers") if isinstance(intake, dict) else None
    answers = answers if isinstance(answers, dict) else {}
    choices = sorted(answers.items()) if answers else sorted(
        {"source_language": config.source_language, "target_language": config.target_language,
         "output_mode": config.output_mode, **dict(config.profile)}.items()
    )
    context = {
        "title": title_values[0] if isinstance(title_values, list) and title_values else config.slug,
        "source_name": config.source.name,
        "source_language": config.source_language,
        "target_language": config.target_language,
        "output_mode": config.output_mode,
        "stage": stage,
        "next_command": _next_command(stage, project_arg, coverage),
        "project_arg": project_arg,
        "coverage": coverage,
        "documents": _documents(block_map, contract, rows, titles),
        "sample_document": document or "",
        "is_pilot": pilot["status"] != "legacy",
        "pairs": pairs,
        "choices": choices,
        "release": release,
    }
    atomic_write_text(config.paths.reports / "review.html", _render(context))
    return {
        "status": "pass",
        "schema_version": 1,
        "workflow_status": stage,
        "translated": coverage.get("translated", 0) if coverage else 0,
        "eligible": coverage.get("eligible", 0) if coverage else 0,
        "remaining": coverage.get("remaining") if coverage else None,
        "sample_blocks": len(pairs),
        "next_command": context["next_command"],
        "written": REVIEW_RELATIVE_PATH,
        "message": f"Review page written to {REVIEW_RELATIVE_PATH}. Open it in a browser.",
    }

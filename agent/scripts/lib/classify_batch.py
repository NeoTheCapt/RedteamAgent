#!/usr/bin/env python3
"""Single-process driver for the per-case classifier pipeline.

Each individual classifier (`input_shapes.py`, `surface_tags.py`,
`stateful_response.py`, `security_question.py`) ships its own
`--batch <path>` CLI for unit testing. But running them sequentially
as 4 separate `python3` invocations from `fetch_batch_to_file.sh`
costs ~57 ms of cold-start overhead per batch — measurable when an
engagement does hundreds of fetches.

This driver imports all four classifier modules in one process, runs
each `_annotate_batch` against the same on-disk file, and emits a
unified summary the wrapper shell can grep.

Output (one line per classifier, identical to the individual scripts):

    input_shapes_summary=<aggregate>
    surface_types_summary=<aggregate>
    stateful_summary=<aggregate>
    security_context_summary=<aggregate>

Failure in any one classifier is logged on stderr and skipped — the
remaining classifiers still run. A completely broken module never
prevents the batch from being annotated by its siblings.

Usage:
    classify_batch.py <batch-json-path>
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


_HERE = Path(__file__).resolve().parent


# Each tuple: (module-name, public _annotate_batch return -> summary line).
# The summary-line formatting mirrors the individual CLIs so the wrapper
# shell can keep parsing exactly the same prefixes.
_CLASSIFIERS = [
    (
        "input_shapes",
        lambda mod, path: _input_shapes_summary(mod, path),
    ),
    (
        "surface_tags",
        lambda mod, path: _surface_types_summary(mod, path),
    ),
    (
        "stateful_response",
        lambda mod, path: _stateful_summary(mod, path),
    ),
    (
        "security_question",
        lambda mod, path: _security_context_summary(mod, path),
    ),
]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _HERE / f"{name}.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"could not locate classifier module: {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _tag_aggregate(payload: list, field: str) -> dict[str, int]:
    """Aggregate tag counts from a batch payload, tolerant of non-dict
    entries. Post-Codex-review fix: previously a non-dict entry raised
    AttributeError on `.get()` and the whole summary line was lost."""
    agg: dict[str, int] = {}
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        for tag in entry.get(field) or []:
            agg[str(tag)] = agg.get(str(tag), 0) + 1
    return agg


def _input_shapes_summary(mod, path: Path) -> str:
    import json
    annotated = mod._annotate_batch(path)
    if annotated == 0:
        return "input_shapes_summary=empty"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "input_shapes_summary=parse_error"
    agg = _tag_aggregate(payload if isinstance(payload, list) else [], "input_shapes")
    if not agg:
        return "input_shapes_summary=none"
    return "input_shapes_summary=" + ",".join(
        f"{tag}:{count}" for tag, count in sorted(agg.items())
    )


def _surface_types_summary(mod, path: Path) -> str:
    import json
    annotated = mod._annotate_batch(path)
    if annotated == 0:
        return "surface_types_summary=empty"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "surface_types_summary=parse_error"
    agg = _tag_aggregate(payload if isinstance(payload, list) else [], "surface_types")
    if not agg:
        return "surface_types_summary=none"
    return "surface_types_summary=" + ",".join(
        f"{tag}:{count}" for tag, count in sorted(agg.items())
    )


def _stateful_summary(mod, path: Path) -> str:
    total, stateful = mod._annotate_batch(path)
    if total == 0:
        return "stateful_summary=empty"
    return f"stateful_summary=stateful:{stateful},total:{total}"


def _security_context_summary(mod, path: Path) -> str:
    total, detected = mod._annotate_batch(path)
    if total == 0:
        return "security_context_summary=empty"
    return f"security_context_summary=detected:{detected},total:{total}"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: classify_batch.py <batch-json-path>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    if not path.is_file():
        print(f"classify_batch: not a file: {path}", file=sys.stderr)
        return 1

    for name, summarizer in _CLASSIFIERS:
        try:
            mod = _load(name)
        except Exception as exc:  # noqa: BLE001 — best-effort wrapper
            print(f"classify_batch: failed to load {name}: {exc}", file=sys.stderr)
            continue
        try:
            print(summarizer(mod, path))
        except Exception as exc:  # noqa: BLE001
            print(f"classify_batch: {name} failed: {exc}", file=sys.stderr)
            continue
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

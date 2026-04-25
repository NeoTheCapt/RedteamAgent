#!/usr/bin/env python3
"""prune_vendor_cases.py — auto-mark vendor / framework JS cases as clean
so source-analyzer doesn't burn dispatches on them.

Audit data on 2026-04-25 showed source-analyzer at 121 dispatches /
2 findings across two engagements (ROI 0.016). The vast majority of
those dispatches were webpack chunks, polyfills, runtime helpers,
and third-party vendor bundles — files that almost never contain
exploit-relevant routes or secrets.

Pattern, not target-specific knowledge: this script matches GENERIC
build-tool / framework noise filenames common to any modern SPA build,
not Juice-Shop-specific paths. The patterns are:

  - webpack chunks:       chunk-<hash>.js, chunk.<hash>.js, <number>.js (build artifact)
  - polyfills/runtime:    polyfill[s].<hash>.js, runtime[.-]<hash>.js, framework[.-]<hash>.js
  - common-name vendors:  vendor[.-]<hash>.js, vendors[.-]<hash>.js, common[s]?[.-]<hash>.js
  - source maps:          <anything>.js.map, <anything>.css.map
  - confetti / animation: confetti-<hash>.js, animation-<hash>.js (recurring noise observed)
  - copy-pasta UI libs:   *.bundle.js when path contains "/vendor/" or "/lib/" segment

Cases matching these patterns are advanced to stage='clean' WITHOUT
running source-analyzer. The producer (katana) can keep ingesting
everything indiscriminately — this script is the second filter.

Operator should run this BEFORE every fetch-by-stage on ingested javascript:
  python3 ./scripts/prune_vendor_cases.py "$DIR/cases.db"

Idempotent. Already-cleaned cases are skipped. Safe to call repeatedly.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

# Generic vendor-noise patterns. Each pattern matches the url_path field.
# Patterns are case-insensitive; tested in Python re module syntax.
VENDOR_PATTERNS = [
    # webpack chunk patterns: chunk-ABC123.js, chunk.ABC123.js
    re.compile(r"/chunk[\.\-][a-z0-9]{4,}\.js$", re.IGNORECASE),
    # polyfills: polyfills.abc.js, polyfills-abc.js, polyfill.abc.js
    re.compile(r"/polyfills?[\.\-][a-z0-9]{4,}\.js$", re.IGNORECASE),
    # runtime: runtime.abc.js, runtime-abc.js
    re.compile(r"/runtime[\.\-][a-z0-9]{4,}\.js$", re.IGNORECASE),
    # framework files: framework.abc.js, framework-abc.js
    re.compile(r"/framework[\.\-][a-z0-9]{4,}\.js$", re.IGNORECASE),
    # vendor bundles: vendor.abc.js, vendors-abc.js
    re.compile(r"/vendors?[\.\-][a-z0-9]{4,}\.js$", re.IGNORECASE),
    # common/commons bundles
    re.compile(r"/commons?[\.\-][a-z0-9]{4,}\.js$", re.IGNORECASE),
    # source maps — never useful for source-analyzer (it analyzes the JS)
    re.compile(r"\.(js|css|mjs)\.map$", re.IGNORECASE),
    # confetti / animation noise (recurring on Juice Shop and others)
    re.compile(r"/(confetti|animation|firework)[\.\-][a-z0-9]+\.js$", re.IGNORECASE),
    # numeric-only bundle filenames typical of webpack code-splitting (e.g. /23.abc.js)
    re.compile(r"/\d+\.[a-z0-9]{4,}\.js$", re.IGNORECASE),
    # bundles inside /vendor/ or /lib/ directory segments
    re.compile(r"/(vendor|lib|libs|libraries|node_modules)/.+\.js$", re.IGNORECASE),
    # Angular i18n message bundles
    re.compile(r"/messages\.[a-z0-9-]+\.js$", re.IGNORECASE),
]


def is_vendor_noise(url_path: str) -> bool:
    if not url_path:
        return False
    for pat in VENDOR_PATTERNS:
        if pat.search(url_path):
            return True
    return False


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("db_path", help="path to cases.db")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="report matching cases without updating stage",
    )
    args = p.parse_args(argv)

    db = Path(args.db_path)
    if not db.exists():
        print(f"cases.db missing: {db}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(str(db))
    try:
        # Legacy cases.db (pre-streaming-pipeline) has no `stage` column.
        # Treat that as a no-op rather than crashing — the operator can
        # safely call this every tick on any workspace.
        cols = {row[1] for row in conn.execute("PRAGMA table_info(cases)").fetchall()}
        if "stage" not in cols:
            print("[prune-vendor] cases.db lacks 'stage' column (legacy schema); "
                  "nothing to prune", file=sys.stderr)
            return 0

        # Only act on currently-active javascript cases. Don't touch
        # cases that already moved past ingested or are in flight.
        rows = conn.execute(
            """
            SELECT id, url_path, url
            FROM cases
            WHERE type = 'javascript'
              AND stage = 'ingested'
              AND status = 'pending'
            """
        ).fetchall()

        to_clean = []
        for case_id, url_path, url in rows:
            if is_vendor_noise(url_path or url or ""):
                to_clean.append((case_id, url_path or url or ""))

        if args.dry_run:
            print(f"[prune-vendor] dry-run: would clean {len(to_clean)} of "
                  f"{len(rows)} ingested javascript case(s)", file=sys.stderr)
            for cid, path in to_clean[:20]:
                print(f"  - case {cid}: {path}", file=sys.stderr)
            if len(to_clean) > 20:
                print(f"  ... +{len(to_clean) - 20} more", file=sys.stderr)
            return 0

        if not to_clean:
            print("[prune-vendor] no vendor-noise javascript cases to prune",
                  file=sys.stderr)
            return 0

        ids = [cid for cid, _ in to_clean]
        # Update stage='clean', status='done' so the case is terminal.
        placeholders = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE cases SET stage='clean', status='done' "
            f"WHERE id IN ({placeholders})",
            ids,
        )
        conn.commit()

        print(
            f"[prune-vendor] marked {len(to_clean)} vendor-noise javascript "
            f"case(s) as stage=clean (out of {len(rows)} ingested)",
            file=sys.stderr,
        )
        # Show first few for visibility.
        for cid, path in to_clean[:5]:
            print(f"  - case {cid}: {path}", file=sys.stderr)
        if len(to_clean) > 5:
            print(f"  ... +{len(to_clean) - 5} more", file=sys.stderr)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

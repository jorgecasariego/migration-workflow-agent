#!/usr/bin/env python3
"""End-to-end smoke test against a RUNNING backend with a REAL Anthropic API key.

    python scripts/smoke_test.py [--api http://localhost:8000] [--timeout 900]

Submits samples/express-users, polls GET /migrations/{id} until it finishes and
prints the plan, files and verification report. Exit code 0 only if the migration
completed and verification passed. Uses the standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "samples" / "express-users"


def request(method: str, url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args()

    files = [{"path": p, "content": (SAMPLE / p).read_text()} for p in ("server.js", "routes/users.js")]
    try:
        created = request("POST", f"{args.api}/migrate", {"source_framework": "express",
                                                          "target_framework": "fastapi", "files": files})
    except urllib.error.HTTPError as e:
        print(f"POST /migrate failed: {e.code} {e.read().decode()}")
        return 1
    mid = created["id"]
    print(f"Migration {mid} started")

    deadline = time.monotonic() + args.timeout
    last_event = 0
    while True:
        m = request("GET", f"{args.api}/migrations/{mid}")
        for ev in m["events"][last_event:]:
            print(f"  · {ev['message']}")
        last_event = len(m["events"])
        if m["status"] in ("completed", "failed"):
            break
        if time.monotonic() > deadline:
            print("Timed out waiting for migration")
            return 1
        time.sleep(2)

    print(f"\nStatus: {m['status']}")
    for s in m["plan"]:
        print(f"  {s['id']:8} {s['status']:10} {s['target_file']}  ({s['attempts']} attempt(s))")
    for f in m["migrated_files"]:
        print(f"\n===== {f['path']} =====\n{f['content']}")
    v = m.get("verification")
    if v:
        print("\nVerification:", "PASSED" if v["passed"] else "FAILED")
        for e in v["endpoints"]:
            print(f"  {'✓' if e['found'] else '✗'} {e['method']} {e['path']}")
        for w in v["warnings"]:
            print(f"  ! {w}")
    for e in m["errors"]:
        print(f"ERROR [{e['phase']}] {e['message']}")
    return 0 if m["status"] == "completed" and v and v["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

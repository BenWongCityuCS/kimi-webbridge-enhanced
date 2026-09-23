#!/usr/bin/env python3
"""Reap orphaned Kimi WebBridge sessions.

WHY THIS EXISTS
---------------
Kimi WebBridge deliberately leaves tabs open: closing is user-initiated, the daemon
exposes **no way to enumerate sessions**, and there is **no idle timeout**. So when a
multi-agent run is killed or errors out, the subagents never reach `close_session`,
nobody else knows their session names, and the tab groups sit in your browser forever.
(Observed in practice: a killed workflow's tabs still open 10+ minutes later — not a
timeout about to fire, just nothing that was ever going to close them.)

This script closes exactly those leftovers, and never touches a session that is
still in use.

HOW IT TELLS "ORPHAN" FROM "IN USE"
-----------------------------------
By heartbeat. The companion client (`wbq.py`) refreshes
`%TEMP%/wb-sessions/<session>.stamp` on **every** call. This script only reaps
sessions whose heartbeat is older than the threshold (default 30 min), so a
subagent that is merely quiet between calls is safe.

`close_session` on a session with no tabs returns `{"closed": 0}` and succeeds,
so reaping is idempotent and harmless to repeat.

USAGE
-----
    python wb_reap.py                        # report only (default)
    python wb_reap.py --min-idle 10          # change the staleness threshold
    python wb_reap.py --close                # reap stale sessions
    python wb_reap.py --config wb_sessions.json --probe
    python wb_reap.py --config wb_sessions.json --probe --close
    python wb_reap.py --names a,b,c --close  # handle specific sessions

`--probe` sweeps session names you never registered a heartbeat for (e.g. sessions
from before you started using this script). It is **read-only** (`list_tabs`), so it
is safe to run while a workflow is live; it prints only the names that really still
hold tabs, and with `--close` it reaps those too.

SESSION-NAME DERIVATION (--config)
----------------------------------
Session names in a multi-agent setup are usually deterministic: `<prefix>-<slug>`.
Point the config at the data your run fans out over and `--probe` can find tabs
opened before you had heartbeats:

```json
{
  "sources": [
    {"file": "targets.json",  "prefix": "census",  "slugField": "slug"},
    {"file": "companies.csv", "prefix": "profile", "slugField": "company", "slug": "md5-5"}
  ],
  "extra": ["fix-census", "gtfix"]
}
```

`slug` may be `"raw"` (default — use the field verbatim) or `"md5-5"` (first 5 hex
chars of the md5 of the field, for company names that would make ugly session names).
"""
import argparse
import csv
import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

GATEWAY = os.environ.get("WB_GATEWAY", "http://127.0.0.1:11086/command")
STAMP_DIR = os.path.join(os.environ.get("TEMP") or "/tmp", "wb-sessions")


def stamp_path(session):
    safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in session)
    return os.path.join(STAMP_DIR, safe + ".stamp")


def read_sessions():
    """[(session, last_activity_ts)] from the heartbeat directory."""
    if not os.path.isdir(STAMP_DIR):
        return []
    out = []
    for fn in os.listdir(STAMP_DIR):
        if not fn.endswith(".stamp"):
            continue
        p = os.path.join(STAMP_DIR, fn)
        try:
            with open(p, encoding="utf-8") as f:
                ts = float(f.read().strip() or 0)
        except Exception:  # noqa: BLE001
            ts = os.path.getmtime(p)
        out.append((fn[: -len(".stamp")], ts))
    return sorted(out, key=lambda x: x[1])


def call(session, action, args=None):
    body = json.dumps(
        {"action": action, "args": args or {}, "session": session}, ensure_ascii=False
    ).encode("utf-8")
    req = urllib.request.Request(
        GATEWAY, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": e.read().decode("utf-8", errors="replace")[:200],
                "http": e.code}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}


def make_slug(value, mode):
    value = (value or "").strip()
    if not value:
        return ""
    if mode == "md5-5":
        return hashlib.md5(value.encode("utf-8")).hexdigest()[:5]
    return value


def derive_candidates(config_path):
    """Session names implied by a run's input files, for --probe."""
    if not config_path:
        return set()
    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)
    base = os.path.dirname(os.path.abspath(config_path))
    names = set()
    for src in cfg.get("sources", []):
        path = src.get("file") or ""
        if not os.path.isabs(path):
            path = os.path.join(base, path)
        prefix = src.get("prefix") or ""
        field = src.get("slugField") or "slug"
        mode = src.get("slug") or "raw"
        if not os.path.isfile(path):
            continue
        try:
            if path.lower().endswith(".csv"):
                raw = open(path, "rb").read().decode("utf-8-sig")
                rows = list(csv.DictReader(io.StringIO(raw)))
            else:
                with open(path, encoding="utf-8") as f:
                    rows = json.load(f)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            slug = make_slug(row.get(field), mode)
            if slug:
                names.add(("%s-%s" % (prefix, slug)) if prefix else slug)
    names.update(cfg.get("extra", []))
    return names


def main():
    ap = argparse.ArgumentParser(description="Reap orphaned WebBridge sessions.")
    ap.add_argument("--close", action="store_true",
                    help="actually reap (default: report only)")
    ap.add_argument("--min-idle", type=float, default=30.0,
                    help="minutes of silence before a session counts as an orphan (default 30)")
    ap.add_argument("--names", default="",
                    help="extra session names to consider, comma-separated")
    ap.add_argument("--config", default="",
                    help="JSON config describing <prefix>-<slug> session naming (see docstring)")
    ap.add_argument("--probe", action="store_true",
                    help="read-only list_tabs sweep over derived names; with --close, reap those too")
    args = ap.parse_args()

    now = time.time()
    threshold = args.min_idle * 60

    known = dict(read_sessions())
    derived = derive_candidates(args.config) - set(known)
    extra = [x.strip() for x in args.names.split(",") if x.strip()]
    unknown = sorted(derived | set(extra))

    stale, fresh = [], []
    for s, ts in known.items():
        (stale if (now - ts) > threshold else fresh).append((s, (now - ts) / 60.0))

    print("heartbeat dir: %s (%d session(s) on record)" % (STAMP_DIR, len(known)))
    print("threshold: idle > %.0f min\n" % args.min_idle)

    print("== still active (left alone) ==")
    for s, mins in sorted(fresh, key=lambda x: x[1]):
        print("   %-46s last used %.1f min ago" % (s, mins))
    if not fresh:
        print("   (none)")

    print("\n== heartbeat expired (orphan candidates) ==")
    for s, mins in sorted(stale, key=lambda x: -x[1]):
        print("   %-46s last used %.1f min ago" % (s, mins))
    if not stale:
        print("   (none)")

    if not known:
        print("\n(no heartbeats at all — pass --config/--names and use --probe to find "
              "sessions opened before the heartbeat existed)")

    live_tabs = []
    if args.probe and unknown:
        print("\nprobing %d derived name(s) for tabs (read-only)…" % len(unknown))
        for i, s in enumerate(unknown):
            res = call(s, "list_tabs")
            tabs = (res.get("data") or {}).get("tabs") or []
            if tabs:
                live_tabs.append((s, tabs))
                print("   %-46s %d tab(s)" % (s, len(tabs)))
                for t in tabs[:4]:
                    print("        - %s" % str(t.get("url"))[:110])
            if (i + 1) % 50 == 0:
                print("   …%d/%d probed" % (i + 1, len(unknown)))
        print("probe done: %d name(s) still hold tabs." % len(live_tabs))

    if not args.close:
        print("\n(dry run — nothing closed. Add --close to reap.)")
        return 0

    targets = [s for s, _ in stale]
    if args.probe:
        targets += [s for s, _ in live_tabs if s not in targets]
    if not targets:
        print("\nnothing to reap.")
        return 0

    print("\nreaping %d session(s):" % len(targets))
    total = 0
    for s in targets:
        res = call(s, "close_session")
        closed = (res.get("data") or {}).get("closed")
        if res.get("ok") and closed is not None:
            print("   %-46s closed %s tab(s)" % (s, closed))
            total += int(closed or 0)
            try:
                os.remove(stamp_path(s))
            except OSError:
                pass
        else:
            print("   %-46s failed: %s" % (s, str(res.get("error"))[:120]))
    print("\ndone: %d tab(s) closed." % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())

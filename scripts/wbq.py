#!/usr/bin/env python3
"""Small, UTF-8-safe client for the Kimi WebBridge gateway.

Two things it does that a hand-written `curl` does not:

1. **Sends JSON as UTF-8 from Python**, never through a shell — so Chinese text and
   other special characters in your payloads do not get mangled by cmd.exe/PowerShell
   quoting (a real problem on Windows: CJK turns into `?`).
2. **Writes a heartbeat** to `%TEMP%/wb-sessions/<session>.stamp` on every call, so
   `wb_reap.py` can tell which sessions are still in use and reap the orphaned ones
   after a killed run. It never fails a call if the heartbeat write fails.

Point `WB_GATEWAY` at the tab-limit proxy (default `http://127.0.0.1:11086/command`)
so per-session tab limits apply; set it to `http://127.0.0.1:10086/command` to talk to
the daemon directly.

USAGE
-----
    python wbq.py <session> <action> [args-json | @args.json] [--full]

    python wbq.py research navigate '{"url":"https://example.com","newTab":true,"group_title":"Research"}'
    python wbq.py research evaluate '{"code":"document.body.innerText.slice(0,4000)"}'
    python wbq.py research list_tabs
    python wbq.py research close_tab '{"index":0}'
    python wbq.py research close_session

Output is truncated to 30000 characters by default; pass `--full` to disable.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

URL = os.environ.get("WB_GATEWAY", "http://127.0.0.1:11086/command")
LIMIT = 30000
STAMP_DIR = os.path.join(os.environ.get("TEMP") or "/tmp", "wb-sessions")


def heartbeat(session):
    """Record that this session was just used (see wb_reap.py). Never raise."""
    try:
        os.makedirs(STAMP_DIR, exist_ok=True)
        safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in session)
        with open(os.path.join(STAMP_DIR, safe + ".stamp"), "w", encoding="utf-8") as f:
            f.write(str(time.time()))
    except Exception:  # noqa: BLE001
        pass


def main():
    argv = [a for a in sys.argv[1:] if a != "--full"]
    full = "--full" in sys.argv
    if len(argv) < 2:
        print(__doc__)
        sys.exit(1)
    session, action = argv[0], argv[1]
    heartbeat(session)

    args = {}
    if len(argv) > 2 and argv[2]:
        raw = argv[2]
        if raw.startswith("@"):
            with open(raw[1:], encoding="utf-8") as f:
                args = json.load(f)
        else:
            args = json.loads(raw)

    body = {"action": action, "args": args, "session": session}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        URL, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            out = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        out = e.read().decode("utf-8", errors="replace")
        print("[HTTP %d] %s" % (e.code, out[:2000]))
        sys.exit(2)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": type(e).__name__, "detail": str(e)}, ensure_ascii=False))
        sys.exit(3)

    if not out:
        print('{"empty_response": true}')
        return
    if full or len(out) <= LIMIT:
        print(out)
        return
    print(out[:LIMIT])
    print("\n...[truncated, %d chars total; use --full or a narrower evaluate]" % len(out))


if __name__ == "__main__":
    main()

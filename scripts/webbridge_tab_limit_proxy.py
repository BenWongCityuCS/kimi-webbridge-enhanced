#!/usr/bin/env python3
"""
Kimi WebBridge tab-limit proxy.
Listens on http://127.0.0.1:11086 and forwards commands to the real daemon
(http://127.0.0.1:10086).

For any 'navigate' command that would open a new tab, it first checks the
current number of tabs in that session. If the session already has 3 or more
tabs, it rejects the request with a clear Chinese message telling the caller
to close tabs before opening a new one.

Other commands (snapshot, click, evaluate, close_tab, list_tabs, etc.) are
forwarded unchanged.
"""
import json
import http.server
import socketserver
import urllib.request
import urllib.error

REAL_DAEMON = "http://127.0.0.1:10086/command"
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 11086
MAX_TABS = 3


def forward_to_daemon(body: bytes) -> bytes:
    req = urllib.request.Request(
        REAL_DAEMON,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        return e.read()
    except Exception as e:
        return json.dumps({"ok": False, "error": {"code": "proxy_forward_error", "message": str(e)}}).encode("utf-8")


def list_tabs(session: str) -> int:
    body = json.dumps({"action": "list_tabs", "args": {}, "session": session}).encode("utf-8")
    resp = forward_to_daemon(body)
    try:
        data = json.loads(resp)
        return len(data.get("data", {}).get("tabs", []))
    except Exception:
        return 0


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress verbose logs; can be enabled later if needed.
        pass

    def _send_json(self, status: int, data: dict):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        if self.path != "/command":
            self._send_json(404, {"ok": False, "error": {"code": "not_found", "message": "Only /command is supported"}})
            return

        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length)

        try:
            request = json.loads(raw_body)
        except Exception as e:
            self._send_json(400, {"ok": False, "error": {"code": "bad_json", "message": str(e)}})
            return

        action = request.get("action")
        session = request.get("session", "")
        args = request.get("args", {})

        # Tab-creation guard: navigate with newTab=True opens a new tab.
        if action == "navigate" and args.get("newTab") is True:
            current_tabs = list_tabs(session)
            if current_tabs >= MAX_TABS:
                self._send_json(429, {
                    "ok": False,
                    "error": {
                        "code": "tab_limit_exceeded",
                        "message": (
                            f"当前 session '{session}' 已有 {current_tabs} 个标签页，"
                            "必须关闭至少一个 tab（调用 close_tab）低于 3 个后，才能新建网页。"
                        )
                    }
                })
                return

        # Forward everything else to the real daemon.
        response_body = forward_to_daemon(raw_body)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)


if __name__ == "__main__":
    with socketserver.ThreadingTCPServer((LISTEN_HOST, LISTEN_PORT), Handler) as server:
        print(f"WebBridge tab-limit proxy listening on {LISTEN_HOST}:{LISTEN_PORT}")
        print(f"Forwarding to {REAL_DAEMON}; max tabs per session = {MAX_TABS}")
        server.serve_forever()

# kimi-webbridge-enhanced

An **enhanced drop-in skill** for [Kimi WebBridge](https://www.kimi.com), aimed at the case
where **many subagents drive the same real browser at once** — that is where things
actually go wrong.

The repo root is the skill itself, so it can be cloned straight into a skills directory:

```
SKILL.md                         # Kimi's skill doc + local additions (see Attribution)
references/operations.md         # (Kimi's)
scripts/
  webbridge_tab_limit_proxy.py   # cap tabs per session (gateway on :11086)
  wbq.py                         # UTF-8-safe client + heartbeat
  wb_reap.py                     # reap sessions orphaned by a killed run
```

Install by cloning into your agent's skills folder, e.g.
`~/.zcode/skills/kimi-webbridge/`, `~/.codex/skills/kimi-webbridge/`, or wherever your
agent loads skills from. The daemon and Chrome extension come from Kimi, not from here.

## The two problems

**1. Unbounded tab opening.** Fan out to N subagents and each one happily opens tabs
until the browser is noise and the machine swaps. WebBridge counts tabs per session,
but with one session per subagent nothing ever trips the limit.

**2. Orphaned sessions.** WebBridge deliberately keeps tabs until *you* ask to close
them, and the daemon exposes **no way to enumerate sessions** and **no idle timeout**.
So when a run is killed or errors, its subagents never reach `close_session`, nobody
knows their names, and the tab groups just sit there — indefinitely. ("Left open for
10 minutes" is not a timeout about to fire; nothing was ever going to close them.)

## What each script does

### `webbridge_tab_limit_proxy.py` — problem 1

A tiny reverse proxy on `http://127.0.0.1:11086` in front of the real daemon
(`:10086`). For `navigate` with `newTab: true` it counts that session's tabs first and
refuses with HTTP 429 + a readable message once the session is at the cap (default 3).
Everything else passes through untouched. Point your agents at **11086** instead of
10086.

```bash
python scripts/webbridge_tab_limit_proxy.py     # leave running in the background
```

### `wbq.py` — UTF-8 safety + heartbeat

A one-file client that (a) sends JSON as UTF-8 from Python rather than through a shell,
so CJK payloads don't get mangled by Windows quoting, and (b) refreshes a heartbeat file
per session on every call.

```bash
python wbq.py <session> <action> [args-json | @args.json] [--full]

python wbq.py research navigate '{"url":"https://example.com","newTab":true,"group_title":"Research"}'
python wbq.py research evaluate '{"code":"document.body.innerText.slice(0,4000)"}'
python wbq.py research close_session
```

### `wb_reap.py` — problem 2

Because `wbq.py` touches `%TEMP%/wb-sessions/<session>.stamp` on every call, this script
knows which sessions are live. It reaps only sessions whose heartbeat is older than the
threshold — so it can never pull tabs out from under a subagent that is simply quiet
between calls.

```bash
python wb_reap.py                     # report only
python wb_reap.py --close             # reap stale sessions
python wb_reap.py --min-idle 10 --close
```

Sessions opened *before* you started using the heartbeat are unknown to it. `--probe`
sweeps candidate names with a **read-only** `list_tabs` (safe to run while a workflow is
live) and prints the ones that really still hold tabs:

```bash
python wb_reap.py --config wb_sessions.json --probe          # look
python wb_reap.py --config wb_sessions.json --probe --close  # look and reap
```

Session names in a fan-out are usually deterministic (`<prefix>-<slug>`), so the config
just points at the data your run fans out over:

```json
{
  "sources": [
    {"file": "targets.json",  "prefix": "census",  "slugField": "slug"},
    {"file": "companies.csv", "prefix": "profile", "slugField": "company", "slug": "md5-5"}
  ],
  "extra": ["fix-census", "gtfix"]
}
```

`slug` is `"raw"` (default) or `"md5-5"` (first 5 hex chars of the md5 — handy for
company names that would make ugly session names).

Reaping is idempotent: `close_session` on a session with no tabs returns
`{"closed": 0}` and succeeds, so running it twice costs nothing.

## Install

1. Install Kimi WebBridge and its skill (see Kimi's docs: daemon +
   Chrome extension).
2. Start the daemon, then start the proxy and point agents at `:11086`.
3. Give **each subagent its own session name**; have it call `close_session` when done
   (the reaper is the safety net for when it can't).
4. After any run that dies, `wb_reap.py --close`.

`WB_GATEWAY` overrides the endpoint in both `wbq.py` and `wb_reap.py`; `WB_STAMP_DIR`
is not used — stamps live under `%TEMP%/wb-sessions` (`/tmp` elsewhere).

## Caveats

- **The proxy is per session.** N subagents with N session names each get their own
  quota, so the proxy will never refuse them — it bounds *per-session* noise, not your
  machine. Bound the machine with your own concurrency limit.
- `wb_reap.py` decides by heartbeat freshness. If a subagent can go quiet longer than
  your threshold while still alive, raise `--min-idle`.
- Nothing here closes tabs you opened by hand outside WebBridge sessions.

## Attribution & license

- **The WebBridge daemon, Chrome extension, and the base `SKILL.md` /
  `references/operations.md` are Kimi's work.** The `SKILL.md` here is Kimi's distributed
  skill **with local additions** (a rewritten trigger description, a mandatory
  "connect the browser first" readiness section, and the tab-limit proxy section).
  It is not an official Kimi release — for the authoritative, current version, install
  the skill from Kimi.
- Base version note: this `SKILL.md` descends from the **v1.11.5** distribution. Kimi has
  since shipped a restructured v2.x ("Kimi Browser Extension", with a
  `references/cli-creator/` workflow) — check theirs if you want the newest upstream.
- `scripts/webbridge_tab_limit_proxy.py`, `scripts/wbq.py` and `scripts/wb_reap.py` are
  the additions in this repo.
- **No license has been chosen yet.** Until one is added, default copyright applies and
  the contents are not licensed for reuse; if you plan to rely on this repo, add one
  (MIT is the usual choice for scripts like these).

---

## 中文说明

面向**多个 subagent 同时驱动同一个真实浏览器**的场景，补上 Kimi WebBridge 缺的两块：

1. **标签页无限增长** → `webbridge_tab_limit_proxy.py`：在 `:11086` 起一个转发代理，
   对 `navigate`+`newTab` 先数该 session 的标签页，到上限（默认 3）就返回 HTTP 429 并给出
   中文提示；其余动作原样转发。让 subagent 指向 11086。
2. **孤儿会话**：WebBridge 的立场是「关标签由用户发起」，daemon **没有列出 session 的动作、
   也没有空闲超时**；所以工作流被杀掉时，subagent 走不到 `close_session`，它开的 tab group
   会永远留着（实测十几分钟也不会自己关——那不是超时，是本来就不会关）。
   → `wbq.py` 每次调用写一个心跳，`wb_reap.py` 只回收**心跳已过期**的会话（默认 30 分钟），
   因此**不会误伤正在跑但一时安静的 subagent**。心跳机制建立之前开的会话用
   `--config <json> --probe` 做一次只读甄别（`list_tabs`），确认后再 `--close`。

`close_session` 对没有标签页的会话返回 `{"closed": 0}` 且成功，所以重复回收无害、幂等。

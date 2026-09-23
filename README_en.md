<p align="center">
  <a href="./README.md"><img alt="中文说明" src="https://img.shields.io/badge/简体中文-DFE0E5"></a>
  <a href="./README_en.md"><img alt="README in English" src="https://img.shields.io/badge/English-DBEDFA"></a>
  <a href="./LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-2e6cc4"></a>
</p>

# kimi-webbridge-enhanced — an enhanced Kimi WebBridge skill

A drop-in **enhanced Kimi WebBridge skill** for one specific situation: **several AI
subagents driving the same real browser at once**, where two things reliably go wrong.

In one line: **a doorman (caps tabs) + a janitor (reaps tabs nobody wants any more)**.

---

## The two problems it fixes

### 1. Tabs pile up and nobody stops them

You run three subagents in parallel; each opens pages as it goes. Kimi WebBridge counts
tabs **per session**, and each subagent uses its own session name — so **none of them ever
hits a limit**. The browser fills with tabs and the machine slows to a crawl.

**Fix** → `scripts/webbridge_tab_limit_proxy.py`, a doorman: each session gets at most 3
tabs; beyond that the request is refused with a message telling the caller to close one.

### 2. A killed run leaves its tabs open forever

WebBridge deliberately keeps tabs until **you** ask for them to be closed: the daemon has
**no way to list sessions** and **no idle timeout**. So when a run is killed, its subagents
never reach the final "close my session" step, and their tab groups stay where they are.

> What you see as "still open after 10 minutes and not closing" is **not a timeout about to
> fire** — nothing was ever going to close them.

**Fix** → `scripts/wbq.py` + `scripts/wb_reap.py` together:
- `wbq.py` records a heartbeat on every call (a tiny file saying "this session was alive
  just now");
- `wb_reap.py` reaps **only sessions whose heartbeat has expired** (default: quiet for over
  30 minutes), so a subagent that is merely quiet between calls is never disturbed.

---

## What each script does

### 1. `webbridge_tab_limit_proxy.py` — the doorman

Starts a forwarding gateway on `http://127.0.0.1:11086`. It sits in front; the real work is
still done by Kimi's own daemon on `:10086`. For every "open a new tab" request it first
counts that session's tabs and refuses once the cap (default 3) is reached. Everything else
(screenshots, clicks, page reads…) passes straight through.

Leave it running:

```bash
python scripts/webbridge_tab_limit_proxy.py
```

Then point your subagents at **11086** instead of connecting directly to 10086.

### 2. `wbq.py` — the client

Two jobs:

1. **No more mangled text.** It sends the JSON as UTF-8 straight from Python rather than
   through a shell, so CJK payloads don't come out as `?` — a common Windows problem with
   `curl`.
2. **Records the heartbeat** on every call, so the reaper knows which sessions are alive.

```bash
python wbq.py <session> <action> [args-json | @args.json] [--full]

python wbq.py research navigate '{"url":"https://example.com","newTab":true,"group_title":"Research"}'
python wbq.py research evaluate '{"code":"document.body.innerText.slice(0,4000)"}'
python wbq.py research close_session
```

### 3. `wb_reap.py` — the janitor

```bash
python wb_reap.py                    # report only — closes nothing
python wb_reap.py --close            # reap what has expired
python wb_reap.py --min-idle 10 --close    # treat 10 minutes of silence as expired
```

The heartbeat was added later, so **sessions opened before that are unknown to it**. Use
`--probe` for a **read-only** sweep (`list_tabs` only — safe to run while a workflow is
live); it prints the names that really still hold tabs:

```bash
python wb_reap.py --config wb_sessions.json --probe          # look
python wb_reap.py --config wb_sessions.json --probe --close  # look, then reap
```

`wb_sessions.json` just tells it how your session names are built (usually `prefix-slug`);
see `examples/wb_sessions.json`.

Reaping is idempotent: closing a session that holds no tabs simply reports `closed: 0`.

---

## Install

1. Install **Kimi WebBridge** itself (daemon + Chrome extension) — that part is Kimi's and is
   not in this repo.
2. Clone this repository **whole** into your skills directory, e.g.
   `~/.zcode/skills/kimi-webbridge/`.
3. Start the daemon → start the doorman → give **every subagent its own session name** and
   have it call `close_session` when it finishes.
4. Whenever a run gets interrupted, run `python wb_reap.py --close`.

> **Why install by hand?** The daemon's `install-skill` / `upgrade` only manage the runtimes
> **it recognises** — in practice Claude Code (`~/.claude/skills`) and Codex (`~/.codex/skills`).
> With any other agent it will neither install the skill nor refresh it on upgrade, so you drop a
> copy in yourself; this repo doubles as a ready-to-copy current version for exactly that.

*(The repository root **is** the skill directory, so relative paths written inside
`SKILL.md` such as `scripts/webbridge_tab_limit_proxy.py` still resolve — clone it and it
works.)*

---

## Honest caveats

- **The doorman is per session.** N subagents with N session names each get their own quota,
  so it will **never** refuse them. It bounds how messy the tabs get; it does **not** protect
  your machine. Cap your own concurrency for that.
- `wb_reap.py` decides by heartbeat freshness. If a subagent can stay quiet longer than your
  threshold while still alive, raise `--min-idle`.
- It never touches tabs you opened **by hand**, outside any WebBridge session.

---

## Who wrote this / license

| File | Author | License |
|---|---|---|
| `scripts/webbridge_tab_limit_proxy.py`, `scripts/wbq.py`, `scripts/wb_reap.py`, `README.md`, `README_en.md`, `examples/`, `NOTICE` | this repository's author | **MIT** (see `LICENSE`; scope in `NOTICE`) |
| `SKILL.md`, `references/operations.md`, `references/cli-creator/` | **Kimi's docs** (based on Kimi **v2.0.20**, plus one local addition — **not an official release**) | not covered by MIT; treat under its original terms |

> On that second row: republishing Kimi's documentation is itself a copyright question.
> The origin is stated plainly here, and no license is granted or sublicensed for Kimi's
> files.
>
> Version: this `SKILL.md` is based on Kimi **v2.0.20** (now "Kimi Browser Extension", which
> adds the `references/cli-creator/` workflow for turning a website into a reusable CLI). It
> differs from upstream in **exactly one place** — the `## Tab-limit proxy` section, marked in
> the file with an HTML comment `<!-- LOCAL ADDITION … -->`; re-apply that section after
> refreshing from a newer upstream release. For the newest official version, install from
> Kimi's own distribution.

---

> 其他语言 / Other languages: **[简体中文](README.md)**

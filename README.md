# kimi-webbridge-enhanced —— Kimi WebBridge 的加强版

这是一个可以直接放进 skills 目录的 **Kimi WebBridge 加强版**，专门解决一个场景：**同时开好几个 AI 子任务去操作同一个浏览器**时最容易出的两个毛病。

一句话：**一个门卫（限制标签页数量）+ 一个打扫的（回收没人要的标签页）**。

---

## 它到底解决什么问题（大白话）

### 问题一：标签页越开越多，没人管

你让 3 个子任务同时去查资料，每个子任务都会自己开网页。Kimi WebBridge 的标签页限制是**按「会话」算**的，而每个子任务用的是自己的会话名——**谁都碰不到上限**，于是浏览器一路开出一大堆标签页，电脑越来越卡。

**解法** → `scripts/webbridge_tab_limit_proxy.py`：一个「门卫」。每个会话最多放 3 个标签页进去，超了就拒绝，并提示先关掉一个。

### 问题二：工作流半路被杀掉，网页留在那儿没人关

Kimi WebBridge 的设计是「**关标签页要人来喊**」：它的后台程序**没有「列出当前有哪些会话」的功能，也没有空闲超时**。所以工作流一旦被中断，子任务来不及执行最后那句「收工关页面」，它开的那一组标签页就永远挂在那。

> 你之前看到的「十几分钟都不动静也不关」**不是超时快到了**——是本来就不会关。

**解法** → `scripts/wbq.py` + `scripts/wb_reap.py` 配合：
- `wbq.py` 每次发命令时顺手上报一次「这个会话刚才还活着」（一个很小的「心跳」文件）；
- `wb_reap.py` **只回收心跳已经过期的会话**（默认超过 30 分钟没动过），所以**正在跑、只是暂时安静的不会被误伤**。

---

## 三个脚本各干什么

### 1. `webbridge_tab_limit_proxy.py` —— 门卫

在 `http://127.0.0.1:11086` 起一个**转发器**：它在前面挡着，真正干活的是后面 Kimi 自己的后台程序（`:10086`）。凡是「开新标签页」的请求，它先数一下这个会话已经开了几个，到上限（默认 3）就直接拒绝；其它命令（截图、点击、读取页面…）原样放行。

启动它（让它一直挂着）：

```bash
python scripts/webbridge_tab_limit_proxy.py
```

然后让你的子任务都去连 **11086**，而不是直连 10086。

### 2. `wbq.py` —— 帮你发命令的小工具

两个用处：

1. **中文不会乱码**：它用 Python 直接发数据，不经过命令行外壳。Windows 上用 `curl` 发中文经常变成 `?`，用它就不会。
2. **顺手记心跳**：每次调用都记一笔「这个会话刚用过」，好让回收脚本知道谁还活着。

```bash
python wbq.py <会话名> <动作> [参数]
# 例子：
python wbq.py 查资料 navigate '{"url":"https://example.com","newTab":true,"group_title":"查资料"}'
python wbq.py 查资料 evaluate '{"code":"document.body.innerText.slice(0,4000)"}'
python wbq.py 查资料 close_session
```

### 3. `wb_reap.py` —— 打扫的

```bash
python wb_reap.py                    # 只看：哪些还活着、哪些已经过期（不动任何东西）
python wb_reap.py --close            # 真去关掉那些过期的
python wb_reap.py --min-idle 10 --close    # 改成「闲置超过 10 分钟」就算过期
```

心跳机制是后来才加的，所以**更早开的会话它不认识**。用 `--probe` 做一次**只读**排查（只是看，不会关，工作流正在跑也能安全用），它会列出「确实还挂着标签页」的那些会话名：

```bash
python wb_reap.py --config wb_sessions.json --probe          # 先看
python wb_reap.py --config wb_sessions.json --probe --close  # 看完再关
```

`wb_sessions.json` 只是个配置，告诉它你的会话名是怎么起的（规律通常是 `前缀-短号`），参考 `examples/wb_sessions.json`。

重复回收无害：去关一个已经没标签页的会话，它只会回一句「关了 0 个」。

---

## 怎么装

1. 先装好 **Kimi WebBridge 本体**（后台程序 + Chrome 扩展）——那些是 Kimi 的，不在这个仓库里。
2. 把这个仓库**整个** clone 到你的 skills 目录，比如 `~/.zcode/skills/kimi-webbridge/`。
3. 启动后台程序 → 启动门卫 → 让**每个子任务用自己独立的会话名**，并在结束时调用 `close_session`。
4. 哪次运行被中断了，跑一次 `python wb_reap.py --close` 收尾。

*（仓库根目录就是 skill 目录本身，所以 `SKILL.md` 里写的 `scripts/webbridge_tab_limit_proxy.py` 这类相对路径仍然对得上，clone 下来可以直接用。）*

---

## 几句实话（局限）

- **门卫是按会话限流的**。N 个子任务、N 个会话名，每人都有自己的 3 个名额，所以门卫**永远不会拒绝**它们。它管的是「别开得太乱」，**不负责保护你的电脑**；要保护电脑得自己限制并发数。
- `wb_reap.py` 靠心跳判断死活。如果你的子任务可能安静超过 30 分钟还活着，把 `--min-idle` 调大。
- 它不会去动你**手动**开的、不属于任何 WebBridge 会话的标签页。

---

## 这些东西是谁写的 / 授权

| 文件 | 谁的 | 授权 |
|---|---|---|
| `scripts/webbridge_tab_limit_proxy.py`、`scripts/wbq.py`、`scripts/wb_reap.py`、`README.md`、`examples/`、`NOTICE` | 本仓库作者 | **MIT**（见 `LICENSE`，适用范围见 `NOTICE`） |
| `SKILL.md`、`references/operations.md` | **Kimi 的文档**（`SKILL.md` 是 Kimi v1.11.5 那份 + 本地增补，**不是官方发布**） | 不在 MIT 范围内；Kimi 未附授权声明，按其原始条款处理 |

> 关于第二行，说明一下：把 Kimi 的文档改完再公开分发，本身是个版权问题。这里如实写明来源，并没有对 Kimi 的文件做任何再授权。另外，你这份 `SKILL.md` 源自 **v1.11.5**，而 Kimi 后来已经出了结构大改的 **v2.x**（改名叫 Kimi Browser Extension、多了 `cli-creator/` 那套），想要最新版请去装官方那份。

---

## English (condensed)

An enhanced drop-in **Kimi WebBridge** skill for the case where several agents drive
the same real browser at once. It adds three things:

- **`scripts/webbridge_tab_limit_proxy.py`** — a gateway on `:11086` that caps tabs
  *per session* (default 3) and refuses `navigate`+`newTab` beyond that with HTTP 429.
  Point agents at `:11086` instead of the daemon's `:10086`.
- **`scripts/wbq.py`** — a small client that sends JSON as UTF-8 (so CJK payloads are
  not mangled by shell quoting) and refreshes a per-session heartbeat on every call.
- **`scripts/wb_reap.py`** — reaps sessions orphaned by a killed run. WebBridge keeps
  tabs until asked, exposes no way to list sessions, and has no idle timeout, so a
  terminated multi-agent run leaves its tab groups open forever. The reaper closes only
  sessions whose heartbeat is older than `--min-idle` (default 30 min), so live-but-quiet
  subagents are safe; `--probe` adds a read-only sweep for sessions predating the
  heartbeat.

Install: clone the repo into your skills directory (the repo root *is* the skill), start
the daemon, start the proxy, give every agent its own session name.

Caveat: the proxy is per session, so N agents with N session names each get their own
quota — it bounds tab noise, not machine load. Cap your own concurrency for that.

License: **MIT** for the files authored here (`scripts/*`, `README.md`, `examples/`);
`SKILL.md` and `references/operations.md` are Kimi's docs and are **not** covered.

"""Claude Code statusline：目录、分支、模型、上下文占比、配额、缓存状态。

配额与缓存按事件刷新：Claude Code 在 resets_at、expires_at 到点时会重跑本脚本，
两次运行之间屏幕不变。因此重置时间显示为绝对时刻而非倒计时，倒计时在闲置期间
会停在过时的数上。
"""

import json
import os
import subprocess
import sys
import time

# 中文 Windows 上 stdout 的默认编码是 cp936，进度条的 ░▓█ 一律 UnicodeEncodeError，
# 整行 statusline 变成一句报错。Claude Code 按 UTF-8 读子进程输出，这里对齐过去。
# 不改用 ASCII 字符画条：GBK 装不下的还有分支名、目录名里的任何非 GBK 字符。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

DIM = "\033[2m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"

WARN_CTX, CRIT_CTX = 75, 90
WARN_QUOTA, CRIT_QUOTA = 60, 85
CELLS = 10
DAY = 24 * 3600


def tone(pct, warn, crit):
    if pct >= crit:
        return RED
    if pct >= warn:
        return YELLOW
    return DIM


def git_state(directory):
    """返回 (分支, 是否有未提交改动)，不在仓库内时返回 None。

    一次 status --branch 同时拿到两者。不直接读 .git/HEAD：linked worktree 里
    .git 是文件，从仓库子目录启动时 .git 不在当前目录，两种情况都读不到。
    """
    try:
        done = subprocess.run(
            ["git", "status", "--porcelain=v2", "--branch", "--untracked-files=no"],
            cwd=directory, capture_output=True, text=True, timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None

    head = oid = None
    dirty = False
    for line in done.stdout.splitlines():
        if line.startswith("# branch.head "):
            head = line[len("# branch.head "):]
        elif line.startswith("# branch.oid "):
            oid = line[len("# branch.oid "):]
        elif not line.startswith("#"):
            dirty = True
    if head == "(detached)":
        head = oid[:7] if oid and oid != "(initial)" else None
    return head, dirty


def bar(pct):
    units = pct / 100 * CELLS
    full = min(int(units), CELLS)
    half = 1 if (units - full) >= 0.5 and full < CELLS else 0
    return "█" * full + "▓" * half + "░" * (CELLS - full - half)


def reset_time(epoch):
    """24 小时内给时刻，更远给日期。"""
    local = time.localtime(epoch)
    if epoch - time.time() < DAY:
        return time.strftime("%H:%M", local)
    return f"{local.tm_mon}/{local.tm_mday}"


def tokens(count):
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    return f"{round(count / 1000)}k"


def quota(windows, key, label, always):
    """配额段。未到警戒线时 always=False 的窗口不显示，到了才附重置时刻。"""
    window = windows.get(key) or {}
    pct = window.get("used_percentage")
    if not isinstance(pct, (int, float)):
        return None
    if not always and pct < WARN_QUOTA:
        return None
    text = f"{label} {pct:.0f}%"
    resets_at = window.get("resets_at")
    if pct >= WARN_QUOTA and isinstance(resets_at, (int, float)):
        # ⧖ 只有文本形态；⏱、⌛ 默认按 emoji 渲染，在终端里占两格
        text += f" ⧖{reset_time(resets_at)}"
    return f"{tone(pct, WARN_QUOTA, CRIT_QUOTA)}{text}{RESET}"


def cold_cache(cache):
    """缓存已冷时的提示段，数字为下一条消息需重新缓存的 token 数。

    除了 warm 也比对 expires_at：到点重跑时拿到的数据未必已把 warm 置为 false。
    """
    if not cache.get("caching_observed"):
        return None
    expires_at = cache.get("expires_at")
    expired = isinstance(expires_at, (int, float)) and expires_at <= time.time()
    if cache.get("warm") and not expired:
        return None
    recache = cache.get("recache_tokens_if_cold")
    text = f"❄ {tokens(recache)}" if isinstance(recache, int) and recache > 0 else "❄"
    return f"{YELLOW}{text}{RESET}"


def main():
    # 出错时必须留下可见痕迹：statusline 静默失效和「没配置」在界面上长得一样，
    # 会被当成配置没生效而去改 settings，查错方向从一开始就是偏的。
    try:
        data = json.load(sys.stdin)
    except ValueError as exc:
        sys.stdout.write(f"{RED}statusline: 输入不是合法 JSON ({exc}){RESET}")
        return

    parts = []
    workspace = data.get("workspace") or {}
    directory = workspace.get("current_dir") or data.get("cwd") or ""

    if directory:
        label = os.path.basename(directory.rstrip("/\\")) or directory
        state = git_state(directory)
        if state and state[0]:
            head, dirty = state
            label += f"  {head}{'*' if dirty else ''}"
        parts.append(f"{DIM}{label}{RESET}")

    model = (data.get("model") or {}).get("display_name")
    if model:
        parts.append(f"{DIM}{model}{RESET}")

    used = (data.get("context_window") or {}).get("used_percentage")
    if isinstance(used, (int, float)):
        pct = min(used, 100)
        parts.append(f"{tone(pct, WARN_CTX, CRIT_CTX)}{bar(pct)} {pct:3.0f}%{RESET}")

    windows = data.get("rate_limits") or {}
    for segment in (
        quota(windows, "five_hour", "5h", always=True),
        quota(windows, "seven_day", "7d", always=False),
        cold_cache(data.get("prompt_cache") or {}),
    ):
        if segment:
            parts.append(segment)

    sys.stdout.write("  ".join(parts))


try:
    main()
except Exception as exc:  # 同上：宁可显示一行错，也不要空白
    sys.stdout.write(f"{RED}statusline: {type(exc).__name__}: {exc}{RESET}")

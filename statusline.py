"""Claude Code statusline: 目录 · 分支 · 模型 · 上下文占比 · 5h 配额。

上下文条的分母取 settings.json 的 autoCompactWindow 而非模型真实窗口。
两者可以差一倍（512K vs 1M），按真实窗口画的话，压缩迫在眉睫时条子才走到
一半，这个数就失去了决策价值。
"""

import json
import os
import subprocess
import sys

DIM = "\033[2m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"

WARN_CTX, CRIT_CTX = 75, 90
WARN_QUOTA, CRIT_QUOTA = 60, 85
CELLS = 10


def tone(pct, warn, crit):
    if pct >= crit:
        return RED
    if pct >= warn:
        return YELLOW
    return DIM


def compact_window(fallback):
    """auto-compact 的实际触发点。读 settings 是为了改了阈值之后这里跟着走。"""
    try:
        with open(os.path.expanduser("~/.claude/settings.json"), encoding="utf-8") as fh:
            value = json.load(fh).get("autoCompactWindow")
        if isinstance(value, int) and value > 0:
            return value
    except (OSError, ValueError):
        pass
    return fallback


def branch(workspace):
    worktree = workspace.get("git_worktree")
    if worktree:
        return worktree
    root = workspace.get("project_dir") or workspace.get("current_dir")
    if not root:
        return None
    # 直接读 HEAD，比起 `git rev-parse` 省掉一次进程启动
    try:
        with open(os.path.join(root, ".git", "HEAD"), encoding="utf-8") as fh:
            head = fh.read().strip()
    except OSError:
        return None
    if head.startswith("ref: refs/heads/"):
        return head[len("ref: refs/heads/"):]
    return head[:7] if head else None


def dirty(root):
    try:
        done = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=root, capture_output=True, text=True, timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(done.stdout.strip())


def bar(pct):
    units = pct / 100 * CELLS
    full = min(int(units), CELLS)
    half = 1 if (units - full) >= 0.5 and full < CELLS else 0
    return "█" * full + "▓" * half + "░" * (CELLS - full - half)


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
    root = workspace.get("project_dir") or workspace.get("current_dir") or ""

    if root:
        head = branch(workspace)
        label = os.path.basename(root.rstrip("/\\")) or root
        if head:
            label += f"  {head}{'*' if dirty(root) else ''}"
        parts.append(f"{DIM}{label}{RESET}")

    model = (data.get("model") or {}).get("display_name")
    if model:
        parts.append(f"{DIM}{model}{RESET}")

    ctx = data.get("context_window") or {}
    used = ctx.get("total_input_tokens")
    if isinstance(used, int):
        limit = compact_window(ctx.get("context_window_size") or 200_000)
        pct = min(used / limit * 100, 100)
        color = tone(pct, WARN_CTX, CRIT_CTX)
        parts.append(f"{color}{bar(pct)} {pct:3.0f}%{RESET}")

    five_hour = ((data.get("rate_limits") or {}).get("five_hour")) or {}
    quota = five_hour.get("used_percentage")
    if isinstance(quota, (int, float)):
        color = tone(quota, WARN_QUOTA, CRIT_QUOTA)
        parts.append(f"{color}5h {quota:.0f}%{RESET}")

    sys.stdout.write("  ".join(parts))


try:
    main()
except Exception as exc:  # 同上：宁可显示一行错，也不要空白
    sys.stdout.write(f"{RED}statusline: {type(exc).__name__}: {exc}{RESET}")

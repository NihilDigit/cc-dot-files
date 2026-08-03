#!/usr/bin/env python3
"""PreToolUse / Bash 门控。

承担两项检查：

1. 删除。不拦截普通的 `rm`，PATH 中的 ~/.claude/shim/rm 会将其转为回收站操作。
   此处仅拦截 shim 无法覆盖的写法：绝对路径调用、sudo（使用 secure_path，
   不解析用户 PATH）、以及在进程内部直接 unlink 的 find -delete。

2. git。reset、checkout、clean 一类命令在工作区存在未提交改动时会将其丢弃。
   执行前生成一份不修改工作区的快照，再放行，并告知快照位置。

删除命令的判定基于 lib/shellcmds 的词法切分而非正则匹配，
`adb shell rm -rf /data/x` 因此不会被误判，其中的 rm 是 adb 的参数。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).parent / "lib"))
from shellcmds import Command, ParseError, executed_commands  # noqa: E402

# 会不可逆删除文件的程序。
DELETERS = frozenset({"rm", "unlink", "shred", "srm", "wipe"})

# 在工作区存在未提交改动时会将其丢弃的 git 子命令。
RISKY_GIT = frozenset({
    "reset", "checkout", "restore", "clean", "rebase", "merge",
    "switch", "cherry-pick", "revert", "am",
})

# git 全局选项中自带一个参数的那些，定位子命令时须连同参数一并跳过。
GIT_GLOBAL_OPTS_WITH_ARG = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"})

BACKUP_DIR = Path.home() / ".claude" / "backups" / "git-autobak"
ESCAPE_HATCH = "CLAUDE_ALLOW_RM"

# 全局安装写机器级状态，不随项目走，且版本无法在仓库里声明。改用一次性运行器
# （deno x、uvx）或项目本地依赖。
INSTALL_ESCAPE_HATCH = "CLAUDE_ALLOW_GLOBAL_INSTALL"

GLOBAL_FLAGS = frozenset({"-g", "--global"})

# 装包子命令。npm/pnpm 用 -g 才算全局，yarn 是 `yarn global add`。
NODE_INSTALLERS = frozenset({"npm", "pnpm"})
NODE_INSTALL_SUBCOMMANDS = frozenset({"install", "i", "add"})

PIPS = frozenset({"pip", "pip3"})
PYTHON = re.compile(r"^python[0-9.]*$")


def _on_path(name: str) -> bool:
    """PATH 中是否存在该命令。

    不能只靠 shutil.which：Windows 上它按 PATHEXT 匹配，找不到无扩展名的文件，
    而 Git Bash 下的 trash 正是一个无扩展名的 shell 脚本。

    """
    if shutil.which(name):
        return True
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if directory and os.path.isfile(os.path.join(directory, name)):
            return True
    return False


def trash_command() -> str:
    """本机的回收站命令。Linux 是 trash-cli 的 trash-put，Git Bash 下通常只有 trash。

    提示文案里要给出实际能执行的命令，否则等于没给。

    """
    for name in ("trash-put", "trash"):
        if _on_path(name):
            return name
    return "trash-put"


def deny(reason: str) -> None:
    json.dump({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
    }, sys.stdout)
    sys.exit(0)


def notify(message: str) -> None:
    json.dump({
        "systemMessage": message,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": message,
        },
    }, sys.stdout)
    sys.exit(0)


# --------------------------------------------------------------------------
# 全局安装门控
# --------------------------------------------------------------------------

def check_installs(commands: list[Command], raw: str) -> None:
    """拦全局安装。

    判定同样基于命令词而非正则，因此 `docker exec c1 npm i -g x` 不会命中：
    那条命令的命令词是 docker，安装发生在容器里。

    """
    if INSTALL_ESCAPE_HATCH in raw:
        return

    for cmd in commands:
        name, args = cmd.name, cmd.args

        if name in NODE_INSTALLERS:
            # `npm i -g x` 与 `npm -g i x` 都算，故不假定子命令在首位。
            if NODE_INSTALL_SUBCOMMANDS & set(args) and GLOBAL_FLAGS & set(args):
                deny(
                    f"`{name}` 全局安装被禁止：落在机器级目录，不随项目走，"
                    f"版本也无法在仓库里声明。\n"
                    f"一次性执行用 `deno x <tool>`；项目依赖用 `{name} add <pkg>` 装到本地。\n"
                    f"确需全局安装时，加 {INSTALL_ESCAPE_HATCH}=1 前缀。"
                )

        elif name == "yarn":
            if len(args) >= 2 and args[0] == "global" and args[1] == "add":
                deny(
                    "`yarn global add` 被禁止：装到机器级目录，不随项目走。\n"
                    "一次性执行用 `deno x <tool>`；项目依赖用 `yarn add <pkg>`。\n"
                    f"确需全局安装时，加 {INSTALL_ESCAPE_HATCH}=1 前缀。"
                )

        elif name in PIPS:
            if "install" in args:
                deny(
                    f"`{name} install` 被禁止：装进当前解释器，容易污染系统 Python，"
                    f"且依赖不随项目走。\n"
                    f"一次性执行用 `uvx <tool>`；带额外依赖跑脚本用 `uv run --with <pkg>`；"
                    f"项目依赖用 `uv add <pkg>`。\n"
                    f"确需如此时，加 {INSTALL_ESCAPE_HATCH}=1 前缀。"
                )

        elif PYTHON.match(name):
            # python -m pip install ...
            if "-m" in args:
                i = args.index("-m")
                if i + 1 < len(args) and args[i + 1] == "pip" and "install" in args[i + 1:]:
                    deny(
                        f"`{name} -m pip install` 被禁止，理由同 `pip install`。\n"
                        f"改用 `uvx <tool>`、`uv run --with <pkg>` 或 `uv add <pkg>`。\n"
                        f"确需如此时，加 {INSTALL_ESCAPE_HATCH}=1 前缀。"
                    )


# --------------------------------------------------------------------------
# 删除门控
# --------------------------------------------------------------------------

def check_deletes(commands: list[Command], raw: str) -> None:
    if ESCAPE_HATCH in raw:  # 显式声明要真删，放行
        return

    trash = trash_command()

    for cmd in commands:
        if cmd.name in DELETERS:
            if cmd.escalates:
                deny(
                    f"`sudo {cmd.name}` 绕过回收站，删除不可恢复：sudo 使用 secure_path，"
                    f"不解析 PATH 中的 rm 替身。\n"
                    f"改用 `{trash}`；需要 root 权限时用 `sudo {trash}`。\n"
                    f"确需不可恢复的删除时，加 {ESCAPE_HATCH}=1 前缀。"
                )
            if cmd.is_path_qualified:
                deny(
                    f"`{cmd.word}` 以绝对路径调用，绕过 PATH 中的回收站替身，删除不可恢复。\n"
                    f"改用 `{trash}`，或去掉路径写作 `{cmd.name}`，替身会将其转为回收站操作。\n"
                    f"确需不可恢复的删除时，加 {ESCAPE_HATCH}=1 前缀。"
                )

        if cmd.name == "find":
            if "-delete" in cmd.args:
                deny(
                    "`find -delete` 在 find 进程内部直接 unlink，不经过外部命令，"
                    "回收站替身无法覆盖，删除不可恢复。\n"
                    f"改用 `find ... -exec {trash} {{}} +`。\n"
                    f"确需不可恢复的删除时，加 {ESCAPE_HATCH}=1 前缀。"
                )
            for flag in ("-exec", "-execdir"):
                if flag in cmd.args:
                    target = cmd.args[cmd.args.index(flag) + 1:]
                    if target and PurePosixPath(target[0]).name in DELETERS and "/" in target[0]:
                        deny(
                            f"`find {flag} {target[0]}` 以绝对路径调用删除命令，绕过回收站替身。\n"
                            f"改用 `find ... {flag} {trash} {{}} +`。\n"
                            f"确需不可恢复的删除时，加 {ESCAPE_HATCH}=1 前缀。"
                        )


# --------------------------------------------------------------------------
# git 门控
# --------------------------------------------------------------------------

def git_subcommand(args: list[str]) -> tuple[str | None, str | None]:
    """返回 (子命令, -C 指定的目录)。"""
    workdir = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "-C" and i + 1 < len(args):
            workdir = args[i + 1]
            i += 2
            continue
        if arg.startswith("-"):
            if arg in GIT_GLOBAL_OPTS_WITH_ARG and "=" not in arg:
                i += 2
            else:
                i += 1
            continue
        return arg, workdir
    return None, workdir


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=30,
    )


def snapshot_repo(repo: Path, subcommand: str) -> str | None:
    """为存在未提交改动的工作区生成快照，返回说明文本；工作区干净则返回 None。

    使用 `git stash create` 而非 `git stash push`：前者只生成一个提交对象，
    不修改工作区和索引，失败时也不会改变现场。代价是它不包含未跟踪文件，
    因此未跟踪文件单独打包，`git clean` 针对的正是这部分。
    """
    status = git(repo, "status", "--porcelain")
    if status.returncode != 0 or not status.stdout.strip():
        return None

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    lines: list[str] = []

    created = git(repo, "stash", "create", f"claude-autobak before git {subcommand}")
    sha = created.stdout.strip()
    if sha:
        ref = f"refs/claude-autobak/{stamp}"
        git(repo, "update-ref", ref, sha, "-m", f"before git {subcommand}")
        lines.append(f"  已跟踪文件的改动 → `git stash apply {sha[:12]}`（ref：{ref}）")

    untracked = git(repo, "ls-files", "-o", "--exclude-standard", "-z")
    if untracked.returncode == 0 and untracked.stdout.strip("\0"):
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        archive = BACKUP_DIR / f"{repo.name}-{stamp}-untracked.tar.gz"
        tar = subprocess.run(
            ["tar", "czf", str(archive), "-C", str(repo), "--null", "-T", "-"],
            input=untracked.stdout, text=True, capture_output=True, timeout=120,
        )
        if tar.returncode == 0:
            count = len([p for p in untracked.stdout.split("\0") if p])
            lines.append(f"  未跟踪文件 {count} 个 → `tar xzf {archive}`")
        else:
            lines.append(f"  ⚠ 未跟踪文件打包失败：{tar.stderr.strip()[:200]}")

    if not lines:
        return None
    return f"工作区存在未提交改动，执行 `git {subcommand}` 前已生成快照：\n" + "\n".join(lines)


def snapshot_stashes(repo: Path) -> str | None:
    """在 stash drop/clear 前将现有 stash 记录到独立 ref，避免被 gc 回收。"""
    listing = git(repo, "stash", "list", "--format=%H %gd %s")
    entries = [line for line in listing.stdout.splitlines() if line.strip()]
    if not entries:
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    saved = []
    for idx, line in enumerate(entries):
        sha = line.split(" ", 1)[0]
        ref = f"refs/claude-autobak/stash-{stamp}-{idx}"
        if git(repo, "update-ref", ref, sha).returncode == 0:
            saved.append(f"  {line[:80]} → `git stash apply {sha[:12]}`")
    if not saved:
        return None
    return f"丢弃 stash 前已将 {len(saved)} 条记录至 refs/claude-autobak/：\n" + "\n".join(saved)


def check_git(commands: list[Command], cwd: str) -> None:
    for cmd in commands:
        if cmd.name != "git":
            continue
        subcommand, workdir = git_subcommand(cmd.args)
        if subcommand is None:
            continue

        repo = Path(workdir) if workdir else Path(cwd)
        if not repo.is_dir():
            continue
        toplevel = git(repo, "rev-parse", "--show-toplevel")
        if toplevel.returncode != 0:
            continue
        repo = Path(toplevel.stdout.strip())

        if subcommand == "stash":
            if cmd.args and any(a in ("drop", "clear", "pop") for a in cmd.args):
                message = snapshot_stashes(repo)
                if message:
                    notify(message)
            continue

        if subcommand in RISKY_GIT:
            message = snapshot_repo(repo, subcommand)
            if message:
                notify(message)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    raw = payload.get("tool_input", {}).get("command", "")
    if not raw.strip():
        sys.exit(0)

    try:
        commands = executed_commands(raw)
    except ParseError:
        # 无法切分时不具备判断依据。仅对明显含删除词的命令保守拒绝，其余放行，
        # 避免一处引号问题阻塞整个会话。
        if any(word in raw.split() for word in DELETERS):
            deny("命令中的引号无法配平，无法解析出实际执行的程序，也就无法判断是否涉及删除。请拆分为多条命令。")
        sys.exit(0)

    check_deletes(commands, raw)
    check_installs(commands, raw)
    check_git(commands, payload.get("cwd") or os.getcwd())
    sys.exit(0)


if __name__ == "__main__":
    main()

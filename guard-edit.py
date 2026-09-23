#!/usr/bin/env python3
"""PreToolUse / Edit、Write、NotebookEdit 门控。

被 git 跟踪的文件出错后可通过 `git diff` 和 `git checkout` 恢复；未被跟踪的
文件（不在仓库内、新建未 add、或被 .gitignore 排除）覆盖后无法恢复。因此在
改动前先复制一份 <文件名>.<时间戳>.bak。

仓库内的备份集中放在仓库根的 .claude-bak/ 下，按相对路径存放，并写入
info/exclude。不放在原文件旁：Android 的 res/ 会把其中每个文件当资源编译，
多一个 .bak 即构建失败。集中存放就不必维护一份构建敏感目录的名单。
仓库外的文件没有构建与 git 的问题，备份仍放在原文件旁。

重复修改同一文件不会产生冗余备份：内容与最新一份 .bak 一致时跳过。
"""

from __future__ import annotations

import filecmp
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 超过该大小不再备份，仅提示：复制数百 MB 的文件会显著拖慢这次工具调用。
MAX_BACKUP_BYTES = 100 * 1024 * 1024

BACKUP_DIR_NAME = ".claude-bak"
EXCLUDE_LINE = f"/{BACKUP_DIR_NAME}/"


def notify(message: str) -> None:
    json.dump({
        "systemMessage": message,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": message,
        },
    }, sys.stdout)
    sys.exit(0)


def git(cwd: Path, *args: str) -> str | None:
    """在 cwd 下执行 git，成功时返回去掉首尾空白的 stdout，否则返回 None。"""
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def is_tracked(real: Path) -> bool:
    """文件是否被 git 跟踪。不在仓库内或 git 不可用时均视为未跟踪。"""
    return git(real.parent, "ls-files", "--error-unmatch", "--", str(real)) is not None


def add_exclude(repo: Path, line: str) -> None:
    """把一条规则写进 info/exclude，不碰仓库里的 .gitignore。

    路径经 --git-path 取得：worktree 与 submodule 的 info/exclude 不在
    <仓库>/.git/info/ 下，那里在它们那边是一个文件而非目录。
    """
    exclude_path = git(repo, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude")
    if not exclude_path:
        return
    exclude = Path(exclude_path)
    try:
        existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if line in existing.splitlines():
            return
        exclude.parent.mkdir(parents=True, exist_ok=True)
        separator = "" if not existing or existing.endswith("\n") else "\n"
        with exclude.open("a", encoding="utf-8") as fh:
            fh.write(f"{separator}{line}\n")
    except OSError:
        pass  # 备份本身已成功，exclude 失败只会让 git status 多一行


def backup_dir(real: Path) -> tuple[Path, Path | None]:
    """返回 (备份所在目录, 所属仓库根)。仓库外的文件返回 (原目录, None)。

    按真实路径定位：配置文件常以软链指向 dotfiles 仓库，软链所在目录不是仓库。
    """
    toplevel = git(real.parent, "rev-parse", "--show-toplevel")
    if not toplevel:
        return real.parent, None
    repo = Path(toplevel).resolve()
    return repo / BACKUP_DIR_NAME / real.parent.relative_to(repo), repo


def latest_backup(directory: Path, name: str) -> Path | None:
    """同名文件的最新备份。

    不用 glob(f"{name}.*.bak")：文件 foo 会匹配到 foo.txt 的备份。也不按文件名
    字典序取最大：同秒编号的 -2 排在无编号的那份之前。
    """
    pattern = re.compile(rf"{re.escape(name)}\.(\d{{8}}-\d{{6}})(?:-(\d+))?\.bak")
    candidates = []
    for entry in directory.glob(f"{name}.*.bak"):
        match = pattern.fullmatch(entry.name)
        if match:
            candidates.append((match[1], int(match[2] or 1), entry))
    return max(candidates)[2] if candidates else None


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    raw_path = payload.get("tool_input", {}).get("file_path")
    if not raw_path:
        sys.exit(0)

    path = Path(raw_path)
    # 新建文件不存在可丢失的旧内容；备份文件本身不再备份。
    if not path.is_file() or path.name.endswith(".bak"):
        sys.exit(0)

    real = path.resolve()
    if is_tracked(real):
        sys.exit(0)

    size = real.stat().st_size
    if size > MAX_BACKUP_BYTES:
        notify(f"⚠ {path} 未被 git 跟踪，但体积为 {size // 1024 // 1024} MB，已跳过自动备份。")

    directory, repo = backup_dir(real)
    previous = latest_backup(directory, real.name)
    if previous and filecmp.cmp(real, previous, shallow=False):
        sys.exit(0)  # 内容未变化，已有备份即可

    # 同一秒内的两次备份会重名。重名时向后编号，避免覆盖上一份备份。
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = directory / f"{real.name}.{stamp}.bak"
    serial = 2
    while backup.exists():
        backup = directory / f"{real.name}.{stamp}-{serial}.bak"
        serial += 1

    try:
        directory.mkdir(parents=True, exist_ok=True)
        shutil.copy2(real, backup)
    except OSError as exc:
        notify(f"⚠ {path} 未被 git 跟踪，自动备份失败：{exc}")

    if repo:
        add_exclude(repo, EXCLUDE_LINE)
        notify(f"{path.name} 未被 git 跟踪，已备份 → {backup.relative_to(repo).as_posix()}")
    notify(f"{path.name} 未被 git 跟踪，已备份 → {backup.name}")


if __name__ == "__main__":
    main()

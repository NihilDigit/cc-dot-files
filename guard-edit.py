#!/usr/bin/env python3
"""PreToolUse / Edit·Write·NotebookEdit 门控。

被 git 跟踪的文件出错后可通过 `git diff` 和 `git checkout` 恢复；未被跟踪的
文件（不在仓库内、新建未 add、或被 .gitignore 排除）覆盖后无法恢复。因此在
改动前先复制一份 <文件名>.<时间戳>.bak。

重复修改同一文件不会产生冗余备份：内容与最新一份 .bak 一致时跳过。
"""

from __future__ import annotations

import filecmp
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 超过该大小不再备份，仅提示：复制数百 MB 的文件会显著拖慢这次工具调用。
MAX_BACKUP_BYTES = 100 * 1024 * 1024


def notify(message: str) -> None:
    json.dump({
        "systemMessage": message,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": message,
        },
    }, sys.stdout)
    sys.exit(0)


def is_tracked(path: Path) -> bool:
    """文件是否被 git 跟踪。不在仓库内或 git 不可用时均视为未跟踪。

    先解析软链再查。配置文件常以软链形式指向一个 dotfiles 仓库，此时软链所在
    目录不是仓库，只有指向的真实路径才受版本控制。
    """
    real = path.resolve()
    try:
        result = subprocess.run(
            ["git", "-C", str(real.parent), "ls-files", "--error-unmatch", "--", str(real)],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def latest_backup(path: Path) -> Path | None:
    backups = sorted(path.parent.glob(f"{path.name}.*.bak"))
    return backups[-1] if backups else None


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

    if is_tracked(path):
        sys.exit(0)

    size = path.stat().st_size
    if size > MAX_BACKUP_BYTES:
        notify(f"⚠ {path} 未被 git 跟踪，但体积为 {size // 1024 // 1024} MB，已跳过自动备份。")

    previous = latest_backup(path)
    if previous and filecmp.cmp(path, previous, shallow=False):
        sys.exit(0)  # 内容未变化，已有备份即可

    # 同一秒内的两次备份会重名。重名时向后编号，避免覆盖上一份备份。
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.{stamp}.bak")
    serial = 2
    while backup.exists():
        backup = path.with_name(f"{path.name}.{stamp}-{serial}.bak")
        serial += 1

    try:
        shutil.copy2(path, backup)
    except OSError as exc:
        notify(f"⚠ {path} 未被 git 跟踪，自动备份失败：{exc}")

    notify(f"{path.name} 未被 git 跟踪，已备份 → {backup.name}")


if __name__ == "__main__":
    main()

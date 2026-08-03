#!/usr/bin/env python3
"""guard-shell.py 的判定测试。

只覆盖词法上容易判错的地方 —— 命令词与参数的区分、引号与转义、别名与大小写、
provider 前缀。不重复断言 DELETERS 之类的常量内容，那些读代码就能看到。

    python3 test_gate.py
    HARDGATE_GUARD=~/.claude/hooks/guard-shell.py python3 test_gate.py

后一种跑的是已安装副本。这台机器是拷贝安装，副本不随仓库更新，仓库测过不代表
实际生效的那份测过。
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

GUARD = Path(os.environ.get("HARDGATE_GUARD") or Path(__file__).parent / "guard-shell.py").expanduser()

ALLOW, DENY, NOTIFY = "allow", "deny", "notify"


def run(tool: str, command: str, cwd: str = ".") -> tuple[str, str]:
    """返回 (判定, 提示文本)。"""
    payload = json.dumps({"tool_name": tool, "tool_input": {"command": command}, "cwd": cwd})
    result = subprocess.run(
        [sys.executable, str(GUARD)], input=payload, capture_output=True, text=True, timeout=60,
    )
    if not result.stdout.strip():
        return ALLOW, result.stderr.strip()
    data = json.loads(result.stdout)
    hook = data.get("hookSpecificOutput", {})
    if hook.get("permissionDecision") == "deny":
        return DENY, hook.get("permissionDecisionReason", "")
    return NOTIFY, data.get("systemMessage", "")


def encoded(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode()


POWERSHELL_CASES = [
    # 删除必须拦下，PowerShell 侧没有替身兜底。
    (DENY, "rm x"),
    (DENY, "Remove-Item -Recurse -Force build"),
    (DENY, "del x"),
    (DENY, "RM X"),                                  # 命令名大小写不敏感
    (DENY, "Get-ChildItem *.tmp | rm"),              # 管道后是新的命令词
    (DENY, "& rm x"),                                # & 是调用运算符
    (DENY, "gci | ForEach-Object { rm $_ }"),        # 脚本块内执行
    (DENY, '$x = rm y'),                             # = 右侧仍是命令
    (DENY, 'pwsh -Command "rm x"'),                  # -Command 的参数递归解析
    (DENY, f"pwsh -EncodedCommand {encoded('rm x')}"),
    (DENY, 'Write-Host "$(rm x)"'),                  # 双引号内的 $() 会执行
    (DENY, '[IO.File]::Delete("x")'),                # .NET 删除绕过命令级判定
    (DENY, '$d.Delete()'),
    (DENY, "bash -c '/bin/rm x'"),                   # 交回 POSIX 解析器
    (DENY, "rm.exe x"),                              # 扩展名归一化后仍是 rm

    # 这些不是文件删除，拦下就是误判。
    (ALLOW, "Remove-Item Alias:rm -Force"),
    (ALLOW, "Remove-Item Env:FOO"),
    (ALLOW, "Remove-Item -Path Alias:ls, Alias:ll -Force"),
    (ALLOW, "trash x"),
    (ALLOW, "Write-Host 'rm -rf /'"),                # 单引号串是参数，不是命令
    (ALLOW, 'Write-Host "rm x"'),                    # 双引号里没有 $()
    (ALLOW, "# rm x"),                               # 注释
    (ALLOW, "Select-String rm ."),
    (ALLOW, "docker exec c1 rm -rf /app"),           # 删的是容器里的文件
    (ALLOW, "ssh box rm -rf /srv"),
    (ALLOW, "Get-ChildItem -Recurse"),
    # trash 自身的实现走回收站，不能被 .NET 规则拦掉。
    (ALLOW, "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($p, 'OnlyErrorDialogs', 'SendToRecycleBin')"),
    # 逃生口
    (ALLOW, "$env:CLAUDE_ALLOW_RM=1; rm -rf node_modules"),

    # 装包门控两侧共用。
    (DENY, "npm i -g typescript"),
    (DENY, "npm.cmd i -g typescript"),               # Windows 上 npm 实际是 npm.cmd
    (DENY, "pip install requests"),
    (ALLOW, "docker exec c1 npm i -g x"),            # 装在容器里
    (ALLOW, "npm add typescript"),
]

BASH_CASES = [
    # Bash 侧的策略不同：普通 rm 交给替身，只拦替身覆盖不到的写法。
    (ALLOW, "rm -rf build"),
    (DENY, "/bin/rm -rf build"),
    (DENY, "sudo rm -rf /opt/x"),
    (DENY, "find . -name '*.tmp' -delete"),
    (ALLOW, "adb shell rm -rf /data/local/tmp"),
    (ALLOW, "echo 'rm -rf /'"),
    (DENY, "sh -c 'cd /tmp && /bin/rm -rf junk'"),
    (DENY, "npm i -g typescript"),
]


def main() -> int:
    failures = []
    for tool, cases in (("PowerShell", POWERSHELL_CASES), ("Bash", BASH_CASES)):
        for expected, command in cases:
            actual, message = run(tool, command)
            if actual != expected:
                failures.append(f"  [{tool}] 期望 {expected}，实得 {actual}: {command}\n"
                                f"      {message.splitlines()[0] if message else ''}")

    total = len(POWERSHELL_CASES) + len(BASH_CASES)
    if failures:
        print(f"{len(failures)}/{total} 条不符：")
        print("\n".join(failures))
        return 1
    print(f"{total}/{total} 通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/bin/sh
# 把本仓库的文件软链到 ~/.claude/ 下的对应位置。
#
# 软链而非拷贝，改动才能直接 commit 回来。已存在且不是本仓库软链的文件一律
# 跳过并报告，不覆盖任何现有配置。

set -eu

SRC=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEST=${CLAUDE_HOME:-$HOME/.claude}

link() {
    src="$SRC/$1"
    dst="$DEST/$2"

    if [ ! -e "$src" ]; then
        echo "缺少 $1，跳过" >&2
        return
    fi

    mkdir -p "$(dirname "$dst")"

    if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$src" ]; then
        echo "已就位  $2"
        return
    fi
    # 仓库改名或移动后旧软链指向不存在的路径。这种 dst 作为链接存在、却解析不到，
    # 会落进下面的「已存在，跳过」分支：安装报成功，门控实际不生效。悬空的一律重指，
    # 指向别处但能解析的仍然跳过，那可能是有意的配置。
    if [ -L "$dst" ] && [ ! -e "$dst" ]; then
        ln -sfn "$src" "$dst"
        echo "已重指  $2 -> $1（原软链悬空）"
        return
    fi
    # 拷贝安装的平台（Git Bash）上目标是副本，不会随仓库自动更新。内容有差异
    # 时刷新，否则重跑 install.sh 之后仍在静默运行旧规则。
    if [ -f "$dst" ] && [ ! -L "$dst" ]; then
        if cmp -s "$src" "$dst"; then
            echo "已就位  $2"
        else
            cp "$src" "$dst"
            echo "已更新  $2（副本与仓库不一致，已刷新）"
        fi
        return
    fi

    if [ -e "$dst" ] || [ -L "$dst" ]; then
        echo "已存在  $2（跳过，需要替换请自行移走）" >&2
        return
    fi

    ln -s "$src" "$dst"

    # Git Bash 在 MSYS 未设 winsymlinks 时，ln -s 会静默拷贝而非建链。
    # 拷贝同样能用，但在 ~/.claude/ 下的改动不会回流到仓库，两端会无声分叉，
    # 因此明确报出来。
    if [ -L "$dst" ]; then
        echo "已软链  $2 -> $1"
    else
        echo "已拷贝  $2 -> $1（本平台不支持软链，改动不会回流到仓库）" >&2
        COPIED=1
    fi
}

COPIED=0

link guard-edit.py  hooks/guard-edit.py
link guard-shell.py hooks/guard-shell.py
link shellcmds.py   hooks/lib/shellcmds.py
link pwshcmds.py    hooks/lib/pwshcmds.py
link rm.sh          shim/rm
link CLAUDE.md      CLAUDE.md
link statusline.py  statusline.py

chmod +x "$SRC/rm.sh" "$SRC/guard-shell.py" "$SRC/guard-edit.py"

# guard-bash.py 改名为 guard-shell.py（它现在也管 PowerShell）。旧副本不会再被
# settings.json 引用，但留着会让人以为规则还在那边，故明确报出来由你处置。
if [ -e "$DEST/hooks/guard-bash.py" ]; then
    echo "残留    hooks/guard-bash.py（已更名为 guard-shell.py，此文件不再被引用，可删）" >&2
fi

# CLAUDE.md 末尾导入 @LOCAL.md，本机特定信息放在那里，不进本仓库。
# 先建一个空壳，免得导入指向不存在的文件。
if [ ! -e "$DEST/LOCAL.md" ]; then
    printf '# 本机环境\n\n由 CLAUDE.md 末尾导入。只放本机特定的事实，不进公开仓库。\n' > "$DEST/LOCAL.md"
    echo "已创建  LOCAL.md（空壳，本机信息写在这里）"
fi

# 替身入口。必须落在 Claude Code 继承到的 PATH 中、且排在真正的 rm 之前的目录。
#
# 写进 shell rc 无效：Claude Code 的 Bash 工具是非交互非登录 shell，不读
# .bashrc 与 .profile。设 settings.json 的 env.BASH_ENV 同样无效：Claude Code
# 起 shell 后会 source 自己的 shell snapshot，其中的 export PATH=... 取自进程
# 环境，会把 BASH_ENV 阶段前置的路径整体覆盖。
#
# 唯一可靠的位置是 PATH 里本就存在、排在真 rm 之前的目录。失效没有征兆，而
# guard-bash.py 有意放行普通 rm，前提正是替身已就位，所以这一步必须落实。

for c in /usr/bin/rm /bin/rm; do
    [ -x "$c" ] && REAL_RM=$c && break
done
REAL_DIR=$(dirname "${REAL_RM:-/usr/bin/rm}")

# Git Bash 把 ~/bin 自动前置到 PATH 首位，即使目录尚不存在。
case "${OSTYPE:-}" in
    msys* | cygwin*) mkdir -p "$HOME/bin" ;;
esac

ANCHOR=
OLD_IFS=$IFS
IFS=:
for d in $PATH; do
    [ -n "$d" ] || continue
    [ "$d" = "$REAL_DIR" ] && break
    if [ -d "$d" ] && [ -w "$d" ]; then
        ANCHOR=$d
        break
    fi
done
IFS=$OLD_IFS

write_forwarder() {
    printf '#!/bin/sh\n# 由 cc-dot-files 的 install.sh 生成。实现在 %s/shim/rm。\nexec "%s/shim/rm" "$@"\n' \
        "$DEST" "$DEST" > "$1"
    chmod +x "$1"
}

if [ -n "$ANCHOR" ]; then
    write_forwarder "$ANCHOR/rm"
    echo "已就位  $ANCHOR/rm（替身入口，先于 $REAL_DIR/rm）"
else
    echo "未找到可写且排在 $REAL_DIR 之前的 PATH 目录。" >&2
    echo "请手动放置转发脚本，例如：" >&2
    echo "    sudo sh -c 'printf \"#!/bin/sh\\nexec \\\"$DEST/shim/rm\\\" \\\"\\\$@\\\"\\n\" > /usr/local/bin/rm && chmod +x /usr/local/bin/rm'" >&2
fi

# settings.json 只合并 hooks 一个键，不整文件覆盖：同一个文件里 hooks 是跨机器
# 共享的，model、statusLine、tui 之类是本机口味，整文件同步会把后者一起冲掉。
#
# 合并时把模板里的 ~/.claude 展开成 $DEST 的实际路径。hook command 由哪个 shell
# 执行没有保证，波浪号能否展开不可依赖；展开之后本机路径也不必写进仓库。
#
# Git Bash 下 $DEST 以 /c/... 传入，MSYS 会在交给原生 Windows python 时转成
# C:/...，写进 settings.json 的正是转换后的形式。这是对的：跑 hook 的也是同一个
# Windows python，它读不了 /c/... 这种路径。
python3 - "$SRC/settings.hooks.json" "$DEST" <<'PY'
import json
import os
import sys
import time

template_path, dest = sys.argv[1], sys.argv[2]
settings_path = os.path.join(dest, "settings.json")

with open(template_path, encoding="utf-8") as fh:
    hooks = json.load(fh)["hooks"]

hooks = json.loads(json.dumps(hooks).replace("~/.claude", dest))

try:
    with open(settings_path, encoding="utf-8") as fh:
        settings = json.load(fh)
except FileNotFoundError:
    settings = {}
except ValueError as exc:
    sys.exit(f"{settings_path} 不是合法 JSON（{exc}），已跳过 hooks 合并，请先修复")

if settings.get("hooks") == hooks:
    print("已就位  settings.json 的 hooks")
    sys.exit()

if os.path.exists(settings_path):
    backup = f"{settings_path}.{time.strftime('%Y%m%d-%H%M%S')}.bak"
    with open(backup, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, ensure_ascii=False, indent=2)
    print(f"已备份  {os.path.basename(backup)}")

settings["hooks"] = hooks
with open(settings_path, "w", encoding="utf-8") as fh:
    json.dump(settings, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
print("已更新  settings.json 的 hooks（其余键原样保留）")
PY
echo
echo "安装后需实测确认：在 Claude Code 中执行 command -v rm，"
echo "结果应为上面那个替身入口的路径。若为 $REAL_DIR/rm，说明未生效。"
echo
echo "PowerShell 工具不靠替身：rm 是 Remove-Item 的别名，替身没有介入的机会，"
echo "hook 直接拒绝删除。那边需要一个 PowerShell 能解析的 trash（如 trash.ps1），"
echo "否则拒绝之后没有可用的替代命令。用 Get-Command trash 确认。"
echo
if [ "$COPIED" = 1 ]; then
    echo "本次为拷贝安装。要改规则请改本仓库再重跑 install.sh，不要直接改 $DEST 下的副本。" >&2
    echo "Git Bash 下可设 MSYS=winsymlinks:nativestrict 启用真软链，需开启开发者模式。" >&2
    echo
fi

command -v trash-put >/dev/null 2>&1 || command -v trash >/dev/null 2>&1 \
    || echo "警告：未找到 trash-put 或 trash，rm 替身会直接拒绝执行。Linux 装 trash-cli；Windows 需自备封装回收站的 trash" >&2

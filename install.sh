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
    if [ -e "$dst" ] || [ -L "$dst" ]; then
        echo "已存在  $2（跳过，需要替换请自行移走）" >&2
        return
    fi

    ln -s "$src" "$dst"
    echo "已软链  $2 -> $1"
}

link guard-edit.py  hooks/guard-edit.py
link guard-bash.py  hooks/guard-bash.py
link shellcmds.py   hooks/lib/shellcmds.py
link rm.sh          shim/rm
link CLAUDE.md      CLAUDE.md

chmod +x "$SRC/rm.sh" "$SRC/guard-bash.py" "$SRC/guard-edit.py"

# CLAUDE.md 末尾导入 @LOCAL.md，本机特定信息放在那里，不进本仓库。
# 先建一个空壳，免得导入指向不存在的文件。
if [ ! -e "$DEST/LOCAL.md" ]; then
    printf '# 本机环境\n\n由 CLAUDE.md 末尾导入。只放本机特定的事实，不进公开仓库。\n' > "$DEST/LOCAL.md"
    echo "已创建  LOCAL.md（空壳，本机信息写在这里）"
fi

echo
echo "还需手动完成两步："
echo "  1. 把 settings.hooks.json 的 hooks 字段合并进 $DEST/settings.json"
echo "  2. 在 ~/.bashrc 和 ~/.zshrc 中前置 PATH："
echo "     export PATH=\"$DEST/shim:\$PATH\""
echo
command -v trash-put >/dev/null 2>&1 || echo "警告：未找到 trash-put，请先安装 trash-cli，否则 rm 会直接拒绝执行" >&2

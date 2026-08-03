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

# PATH 片段。不写进 shell rc：Claude Code 的 Bash 工具是非交互非登录 shell，
# 既不读 .bashrc 也不读 .profile，写在那里替身不会进入 PATH。失效过程没有征兆，
# 而 guard-bash.py 有意放行普通 rm，前提正是替身已就位。
# bash 对非交互 shell 会读 $BASH_ENV，故改由它载入。
FRAGMENT="${XDG_CONFIG_HOME:-$HOME/.config}/shell/path.sh"

if [ ! -e "$FRAGMENT" ]; then
    mkdir -p "$(dirname "$FRAGMENT")"
    cat > "$FRAGMENT" <<EOF
# 由 ~/.claude/settings.json 的 env.BASH_ENV 载入。
# 也可从自己的 shell rc 中 source，两者不冲突。
case ":\$PATH:" in
    *":$DEST/shim:"*) ;;
    *) PATH="$DEST/shim:\$PATH" ;;
esac
export PATH
EOF
    echo "已创建  ${FRAGMENT#"$HOME/"}（PATH 片段）"
else
    grep -qF "$DEST/shim" "$FRAGMENT" \
        || echo "注意：$FRAGMENT 已存在但未前置 $DEST/shim，请自行加入" >&2
fi

echo
echo "还需手动完成一步，把下面两个字段合并进 $DEST/settings.json："
echo
echo '  "env": { "BASH_ENV": "'"$FRAGMENT"'" },'
echo "  \"hooks\": …（取自 settings.hooks.json）"
echo
echo "安装后需实测确认：在 Claude Code 中执行 command -v rm，"
echo "结果应为 $DEST/shim/rm。"
echo
if [ "$COPIED" = 1 ]; then
    echo "本次为拷贝安装。要改规则请改本仓库再重跑 install.sh，不要直接改 $DEST 下的副本。" >&2
    echo "Git Bash 下可设 MSYS=winsymlinks:nativestrict 启用真软链，需开启开发者模式。" >&2
    echo
fi

command -v trash-put >/dev/null 2>&1 || command -v trash >/dev/null 2>&1 \
    || echo "警告：未找到 trash-put 或 trash，rm 替身会直接拒绝执行。Linux 装 trash-cli；Windows 需自备封装回收站的 trash" >&2

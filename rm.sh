#!/bin/sh
# PATH 前置的 rm 替身：将删除转为回收站操作。
#
# 位于 PATH 最前，脚本、Makefile 和交互 shell 中的 rm 都会解析到此处。
# 能绕过它的只有三种写法：/bin/rm、sudo rm、find -delete，
# 由 ~/.claude/hooks/guard-shell.py 拦截。
#
# 必须保留的两项 rm 语义，否则安装脚本和 Makefile 会失败：
#   * rm -f 对不存在的路径静默成功
#   * 选项与操作数的边界，-- 之后一律为操作数
#
# 执行不可恢复的删除：CLAUDE_ALLOW_RM=1 rm ...

REAL_RM=/usr/bin/rm

if [ -n "$CLAUDE_ALLOW_RM" ]; then
    exec "$REAL_RM" "$@"
fi

# 回收站命令按平台取。Linux 用 trash-cli 的 trash-put；Git Bash 下没有它，
# 改用封装 Windows 回收站的 trash。后者不接受 `--` 分隔符，故分别记录。
if command -v trash-put >/dev/null 2>&1; then
    TRASH=trash-put
    TRASH_SEP=--
elif command -v trash >/dev/null 2>&1; then
    TRASH=trash
    TRASH_SEP=
else
    echo "rm: 未找到 trash-put 或 trash，拒绝删除。请安装 trash-cli，或加 CLAUDE_ALLOW_RM=1 前缀执行不可恢复的删除" >&2
    exit 1
fi

# 第一遍：跳过选项，将操作数轮转至 $@ 末尾。
force=0
end_of_opts=0
count=$#
i=0
while [ "$i" -lt "$count" ]; do
    arg=$1
    shift
    i=$((i + 1))
    if [ "$end_of_opts" -eq 0 ]; then
        case "$arg" in
            --)
                end_of_opts=1
                continue
                ;;
            --force)
                force=1
                continue
                ;;
            --*)
                continue
                ;;
            -?*)
                case "$arg" in *f*) force=1 ;; esac
                continue
                ;;
        esac
    fi
    set -- "$@" "$arg"
done

if [ $# -eq 0 ]; then
    [ "$force" -eq 1 ] && exit 0
    echo "rm: 缺少操作数" >&2
    exit 1
fi

# 第二遍：剔除不存在的路径。trash-put 对其报错，而 rm -f 必须静默。
missing=0
count=$#
i=0
while [ "$i" -lt "$count" ]; do
    arg=$1
    shift
    i=$((i + 1))
    if [ -e "$arg" ] || [ -L "$arg" ]; then
        set -- "$@" "$arg"
    elif [ "$force" -eq 0 ]; then
        echo "rm: 无法删除 '$arg': 没有那个文件或目录" >&2
        missing=1
    fi
done

[ $# -eq 0 ] && exit "$missing"

if [ -n "$TRASH_SEP" ]; then
    "$TRASH" "$TRASH_SEP" "$@" || exit $?
else
    "$TRASH" "$@" || exit $?
fi
exit "$missing"

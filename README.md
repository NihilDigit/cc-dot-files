# Claude Code 硬门控

三个 PreToolUse hook 加一个 PATH 替身，把三条约束变成 Claude Code 绕不过去的机制：改文件前必有备份、删除一律进回收站、破坏性 git 命令执行前必有快照。这些规则由 hook 强制执行，不依赖模型自觉，也不依赖 CLAUDE.md 里写没写。

## 三条规则

**改文件前留备份**。`guard-edit.py` 在 Edit、Write、NotebookEdit 前检查目标是否被 git 跟踪。已跟踪的直接放行，出错可用 `git diff` 恢复；未跟踪的先复制一份 `<文件名>.<时间戳>.bak`。内容与最新备份一致时跳过，同一秒内重名时向后编号。软链会先解析到真实路径再判断，因此软链进 dotfiles 仓库的配置文件不会重复留备份。

**删除转回收站**。`shim/rm` 前置在 PATH 中，把 `rm` 转为 `trash-put`，脚本和 Makefile 里的 `rm` 一并覆盖。`rm -f` 对不存在路径静默成功的语义被保留，否则安装脚本会失败。三种绕过替身的写法由 `guard-bash.py` 拒绝：

- 绝对路径调用，如 `/bin/rm`
- `sudo rm`，sudo 使用 secure_path，不解析用户 PATH
- `find -delete`，删除在 find 进程内完成，不经过外部命令

**git 破坏性命令前快照**。工作区存在未提交改动时，`reset`、`checkout`、`restore`、`clean`、`rebase`、`merge`、`switch`、`cherry-pick`、`revert`、`am` 执行前先生成快照：已跟踪的改动由 `git stash create` 写入 `refs/claude-autobak/<时间戳>`，未跟踪文件打包至 `~/.claude/backups/git-autobak/`。`stash drop|clear|pop` 前将现有 stash 记录到独立 ref。

用 `git stash create` 而非 `git stash push`：前者只生成一个提交对象，不修改工作区和索引，失败时也不会改变现场。代价是它不含未跟踪文件，因此未跟踪文件单独打包，`git clean` 针对的正是这部分。

## rm 的判定不用正则

`rm -rf build/` 删的是本机文件，`adb shell rm -rf /data/x` 删的是设备文件，正则匹配 `\brm\b` 两条都会命中。

`shellcmds.py` 先做词法切分，再判断 `rm` 位于命令词还是参数位置，只有命令词代表本机执行。因此下列命令不受影响：

```
adb shell rm -rf /data/local/tmp     # 命令词是 adb
ssh box rm -rf /srv                  # 命令词是 ssh
docker exec c1 rm -rf /app           # 命令词是 docker
echo 'rm -rf /'                      # 命令词是 echo
grep -r rm .                         # 命令词是 grep
```

而下列命令仍被识别为本机删除：

```
sudo -u alice rm -rf /opt/x          # 跳过 sudo 及其选项参数
timeout 5 rm x                       # 跳过 timeout 及其时长参数
cat f | xargs -I{} rm {}             # xargs 后的词是新的命令词
sh -c 'cd /tmp && rm -rf junk'       # -c 的参数递归展开
```

`sh -c` 的参数会递归展开，因为那段字符串在本机执行；`adb`、`ssh`、`docker exec` 的参数不展开。

## 安装

依赖 Python 3.10 以上、git、[trash-cli](https://github.com/andreafrancia/trash-cli)。

```sh
sh install.sh
```

脚本把文件软链到 `~/.claude/` 下的对应位置，不覆盖已存在的文件。之后还有两步需要手动完成：

1. 把 `settings.hooks.json` 的 `hooks` 字段合并进 `~/.claude/settings.json`
2. 在 shell rc 中前置 PATH，`~/.bashrc` 和 `~/.zshrc` 都要写

```sh
export PATH="$HOME/.claude/shim:$PATH"
```

## 文件对应

| 本仓库 | 本机路径 |
|---|---|
| `guard-edit.py` | `~/.claude/hooks/guard-edit.py` |
| `guard-bash.py` | `~/.claude/hooks/guard-bash.py` |
| `shellcmds.py` | `~/.claude/hooks/lib/shellcmds.py` |
| `rm.sh` | `~/.claude/shim/rm` |
| `CLAUDE.md` | `~/.claude/CLAUDE.md` |
| `settings.hooks.json` | 合并进 `~/.claude/settings.json` |

`CLAUDE.md` 末尾导入 `@LOCAL.md`，本机特定的环境信息放在那里，不进本仓库。

## 逃生口

`CLAUDE_ALLOW_RM=1` 前缀同时被 shim 和 hook 认可，执行不可恢复的删除：

```sh
CLAUDE_ALLOW_RM=1 rm -rf node_modules
```

## 已知边界

拦不到在进程内部完成的删除：Python 或 Perl 脚本里的 `unlink`、`> file` 截断、`mv` 覆盖。这三类没有可供判定的命令词。

heredoc 正文会被当作命令解析，正文中出现 `/bin/rm` 一类写法会触发误判。拆成多条命令即可绕开。

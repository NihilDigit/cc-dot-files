# Claude Code 硬门控

两个 PreToolUse hook 加一个 PATH 替身，把四条约束变成 Claude Code 绕不过去的机制：改文件前必有备份、删除一律进回收站、破坏性 git 命令执行前必有快照、全局安装一律拒绝。这些规则由 hook 强制执行，不依赖模型自觉，也不依赖 CLAUDE.md 里写没写。

## 四条规则

**改文件前留备份**。`guard-edit.py` 在 Edit、Write、NotebookEdit 前检查目标是否被 git 跟踪。已跟踪的直接放行，出错可用 `git diff` 恢复；未跟踪的先复制一份 `<文件名>.<时间戳>.bak`。内容与最新备份一致时跳过，同一秒内重名时向后编号。软链会先解析到真实路径再判断，因此软链进 dotfiles 仓库的配置文件不会重复留备份。

**删除转回收站**。`shim/rm` 前置在 PATH 中，把 `rm` 转为 `trash-put`，脚本和 Makefile 里的 `rm` 一并覆盖。`rm -f` 对不存在路径静默成功的语义被保留，否则安装脚本会失败。三种绕过替身的写法由 `guard-shell.py` 拒绝：

- 绝对路径调用，如 `/bin/rm`
- `sudo rm`，sudo 使用 secure_path，不解析用户 PATH
- `find -delete`，删除在 find 进程内完成，不经过外部命令

PowerShell 工具走另一套策略，见下节。

**git 破坏性命令前快照**。工作区存在未提交改动时，`reset`、`checkout`、`restore`、`clean`、`rebase`、`merge`、`switch`、`cherry-pick`、`revert`、`am` 执行前先生成快照：已跟踪的改动由 `git stash create` 写入 `refs/claude-autobak/<时间戳>`，未跟踪文件打包至 `~/.claude/backups/git-autobak/`。`stash drop|clear|pop` 前将现有 stash 记录到独立 ref。

用 `git stash create` 而非 `git stash push`：前者只生成一个提交对象，不修改工作区和索引，失败时也不会改变现场。代价是它不含未跟踪文件，因此未跟踪文件单独打包，`git clean` 针对的正是这部分。

**拒绝全局安装**。`npm`/`pnpm` 带 `-g`、`yarn global add`、`pip install`、`python -m pip install` 由 `guard-shell.py` 拒绝，提示改用 `deno x`／`uvx` 一次性执行，或 `npm add`／`uv add`／`pixi add` 装到项目本地。全局安装落在机器级目录，不随项目走，版本也无法在仓库里声明。

逃生口是 `CLAUDE_ALLOW_GLOBAL_INSTALL=1` 前缀，与删除的逃生口相互独立。

## PowerShell 工具：只能拒绝，不能转投

Claude Code 在 Windows 上除 Bash 工具外还有一个 PowerShell 工具，同一个 hook 经 `Bash|PowerShell` matcher 覆盖两者，但删除策略必须不同。

替身在 PowerShell 里没有介入的机会。`rm`、`del`、`ri`、`rd`、`erase` 都是 `Remove-Item` 的内建别名，而 PowerShell 的名字解析顺序是别名 → 函数 → cmdlet → 外部命令，PATH 排在最后。函数覆盖那条路也走不通：Claude Code 以 `-NoProfile` 启动 `pwsh`，profile 里定义的 `rm` 函数根本不加载。

因此 PowerShell 侧一律拒绝文件删除，提示改用 `trash`。这要求本机有一个 PowerShell 能解析的 `trash` —— 无扩展名的 shell 脚本不行，PowerShell 会报 `Cannot run a document`，需要 `trash.ps1` 一类按 PATHEXT 能找到的入口。

三处 PowerShell 特有的判定：

- `Remove-Item Alias:rm`、`Remove-Item Env:FOO` 删的是别名和环境变量，不是文件，按 provider 前缀放行。
- `[IO.File]::Delete(...)`、`$item.Delete()` 是表达式而非命令，命令词的判定不适用，只能按文本匹配。带 `SendToRecycleBin` 的调用是回收站删除（`trash` 自身就这么实现），放行。
- `-EncodedCommand` 的参数是 UTF-16LE 的 base64，会解码后再解析，否则等于留一个明面上的绕过口。

`pwsh -Command "..."`、`Invoke-Expression`、双引号里的 `$(...)` 都会递归展开。PowerShell 里的 `bash -c` 解析到的是 WSL 的 bash，其中的命令按 POSIX 策略判定 —— WSL 侧装着同一套替身，普通 `rm` 在那边仍有兜底。

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

脚本把文件软链到 `~/.claude/` 下的对应位置，不覆盖已存在的文件，并在 PATH 中安装替身入口（见下节）。之后把 `settings.hooks.json` 的 `hooks` 字段合并进 `~/.claude/settings.json`。

## 替身入口放在哪

替身必须落在 Claude Code 继承到的 PATH 中、且排在真正的 `rm` 之前的目录里。有两种看起来可行、实际无效的做法：

**写进 shell rc 无效。** Claude Code 的 Bash 工具起的是非交互非登录 shell（`$-` 为 `hBc`，`shopt login_shell` 为 off），bash 在这种模式下既不读 `.bashrc` 也不读 `.profile`。

**设 `env.BASH_ENV` 也无效。** bash 对非交互 shell 确实会读 `$BASH_ENV`，但 Claude Code 起 shell 后会 source 自己的 shell snapshot，其中有一行 `export PATH=...`，内容取自进程环境，会把 `BASH_ENV` 阶段前置的路径整体覆盖。

`install.sh` 因此从 PATH 中挑一个排在真 `rm` 之前、当前可写的目录，在那里装一个转发到 `~/.claude/shim/rm` 的入口脚本。Git Bash 下通常是 `~/bin`（它被自动前置到 PATH 首位）；Linux 下 `/usr/local/bin` 排在 `/usr/bin` 之前但需要 root，此时脚本会打印出对应的 `sudo` 命令，由你执行。

这一步不能省。失效过程没有任何征兆：`guard-shell.py` 只拦 `/bin/rm`、`sudo rm`、`find -delete` 三种绕过写法，普通的 `rm -rf x` 交由替身接管，因此被有意放行。替身不在 PATH 中时，这条命令解析到真正的 `rm`，删除不可恢复，且不报错。

安装后需实测确认，不能只检查配置文件。在 Claude Code 中执行 `command -v rm`，结果应为入口脚本的路径；若为 `/usr/bin/rm`，说明未生效。

## Windows（Git Bash）

Claude Code 在 Windows 上把 Bash 工具跑在 Git Bash 里，与 Linux 原生环境有三处差异，已在本仓库内处理：

`ln -s` 在 `MSYS` 未设 `winsymlinks` 时静默拷贝而非建链。`install.sh` 会检出这一点并明确报告；此时 `~/.claude/` 下是副本，改规则要改仓库再重跑，否则两端无声分叉。开启开发者模式后可设 `MSYS=winsymlinks:nativestrict` 得到真软链。

Git for Windows 默认 `core.autocrlf=true`，会把 `rm.sh` 检出成 CRLF，shebang 变为 `#!/bin/sh\r`，替身无法执行。仓库根目录的 `.gitattributes` 强制以 LF 检出。

Git Bash 下没有 `trash-put`。`rm.sh` 会退而使用 `trash`，需自备一个把参数送进 Windows 回收站的同名脚本。两个 shell 各需一个入口：Git Bash 不执行 `.ps1`，PowerShell 不执行无扩展名脚本，所以是 `trash` 与 `trash.ps1` 两个文件，实现只留一份，前者转发给后者。

`/usr/bin/rm`、GNU tar 的 `--null -T -`、Python 3.10+ 在 Git Bash 中均可用，无需适配。

## 文件对应

| 本仓库 | 本机路径 |
|---|---|
| `guard-edit.py` | `~/.claude/hooks/guard-edit.py` |
| `guard-shell.py` | `~/.claude/hooks/guard-shell.py` |
| `shellcmds.py` | `~/.claude/hooks/lib/shellcmds.py` |
| `pwshcmds.py` | `~/.claude/hooks/lib/pwshcmds.py` |
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

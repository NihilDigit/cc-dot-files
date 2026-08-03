# 全局设置

## 工作方式

解释讲机制，不只给结论。信息不足时去读代码、查文档或做实验，不要猜。

抓取网页失败时一律改用 Chrome 插件，不要反复更换 UA 重试，插件不可用时自己启动一个 Chrome。没读到的原文不要凭印象复述。

优先改掉造成问题的前提，而不是在症状处加分支或标志位。只能局部修补时，说明是什么挡住了另一条路。

结构正确优先于 diff 小，但不夹带无关改动。写法以易读为先，宁可多一个具名变量或小函数。

注释和测试只在给出代码本身读不到的信息时才有价值，两者都宁可少写。注释写为什么选这个方案、哪条路走不通、哪里违反直觉；测试要能抓到问题，不把刚写下的逻辑再断言一遍。

优先冒烟测试：真实跑一遍，看端到端行为和可观察的副作用，改动琐碎时本机冒烟一次即可。要进 CI 的另外判断，按干净机器设想：没有外设、网络受限、路径与并发顺序不同、不留本地状态；依赖本机环境的就说明只在本机跑。

推送和创建 PR 之前先给我看。

## 硬门控

以下三条由 `~/.claude/hooks/` 的 PreToolUse hook 和 `~/.claude/shim/` 的 PATH 替身强制执行。

**改文件**。改动前检查文件是否被 git 跟踪。已跟踪的直接放行；未跟踪的（不在仓库内、新建未 add、或被 .gitignore 排除）先复制一份 `<文件名>.<时间戳>.bak` 再放行。不要读取、提交或清理这些 .bak。

**删文件**。删除用 `trash-put`，找回用 `trash-list` 和 `trash-restore`。直接写 `rm` 同样安全，PATH 中的替身会将其转为回收站操作。以下三种写法绕过替身且不可恢复，会被 hook 拒绝：

- 绝对路径调用，如 `/bin/rm`
- `sudo rm`，sudo 使用 secure_path，不解析用户 PATH
- `find -delete`，删除在 find 进程内完成，不经过外部命令

确需不可恢复的删除时加 `CLAUDE_ALLOW_RM=1` 前缀，并事先向我确认。

是否构成本机删除由词法切分判定，不做正则匹配。`adb shell rm -rf /data/x`、`ssh box rm -rf /srv` 一类不受影响，其中的 `rm` 是宿主命令的参数，不在本机执行。

**git 破坏性命令**。`reset`、`checkout`、`restore`、`clean`、`rebase`、`merge`、`switch`、`cherry-pick`、`revert`、`am` 在工作区存在未提交改动时先快照再放行：已跟踪的改动写入 `refs/claude-autobak/<时间戳>`，未跟踪文件打包至 `~/.claude/backups/git-autobak/`。`stash drop|clear|pop` 前将现有 stash 记录到独立 ref。快照由 `git stash create` 生成，不修改工作区和索引。快照提示中的恢复方式需转述给我。

快照不构成执行破坏性命令的理由。工作区存在未提交改动时，先说明将丢失哪些内容及原因，再执行。

## PR

走 fork：`origin` 是 fork，`upstream` 是上游，`remote.pushDefault` 设为 `origin`。从上游默认分支拉新分支，`git push -u origin <分支>`，再 `gh pr create --draft`。默认 draft，由我转 ready for review。

一个 PR 一个 commit。标题写作 `type(scope): 英文小写祈使句`，无句号，70 字符内；type 用 `feat`、`fix`、`perf`，scope 沿用仓库已有的。commit headline 与 PR 标题逐字相同。

commit message 正文用英文，手动硬换行 80 列内，不能为空。

PR 正文语言跟随仓库，陈述与 commit message 相同的事实和顺序，截图和日志放这里，不加 Claude Code 尾注。结构按内容定；中文用词统一为概述、根因、改动、验证。关联 issue 用 `Fixes #NNNN` 放末尾。

## 本机环境

@LOCAL.md

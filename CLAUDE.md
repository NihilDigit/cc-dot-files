# 全局设置

## 工作方式

解释讲机制，不只给结论。信息不足时去读代码、查文档或做实验，不要猜。

抓取网页失败时一律改用 Chrome 插件，不要反复更换 UA 重试；插件不可用时自行启动一个 Chrome。没读到的原文不凭印象复述。

优先改掉造成问题的前提，而不是在症状处加分支或标志位。只能局部修补时，说明是什么挡住了另一条路。

结构正确优先于 diff 小，但不夹带无关改动。写法以易读为先，宁可多一个具名变量或小函数。

改已存在的文件用 Edit，不要用内联 python 做 read-replace-write。`s.replace(a, b)` 在 a 匹配不上时静默返回原文并照常写盘，改过和没改无从分辨；Edit 在同样情况下直接失败。这条同样约束派出的 subagent，派发时写进 prompt。图像处理、二进制解析、跨几十个文件的批量替换仍用 python。

注释和测试只在给出代码本身读不到的信息时才有价值，两者都宁可少写。注释写为什么选这个方案、哪条路走不通、哪里违反直觉；测试要能抓到问题，不把刚写下的逻辑再断言一遍。

注释不用 Markdown 语法，IDE 不渲染，`**` 会原样显示。命名一个真实被否决的方案正是注释的价值，「按 oid 取，不是 bvid」要留；为衬托而设的对立面删掉。

优先冒烟测试：真实跑一遍，看端到端行为和可观察的副作用；改动琐碎时本机冒烟一次即可。要进 CI 的另行判断，按干净机器设想：没有外设、网络受限、路径与并发顺序不同、不留本地状态；依赖本机环境的注明只在本机跑。

推送和创建 PR 之前先给我看。

在 Fable 上工作时主动委派 subagent，模型按任务分：通用代码和复杂任务显式传 `model: "opus"`，小任务或持续性的简单任务传 `model: "sonnet"`，不要默认继承 Fable。

并行派 agent 之前先划好文件归属，互不重叠，并在各自的 prompt 里写明边界。agent 只编译自己负责的模块，集成编译由你在收口时统一跑一次。任何一个 agent 写坏一个文件，全项目编译都会失败，其他 agent 收到的报错指向的不是自己的改动，会到错误的位置排查或空等。归属和编译范围由你划定，不交给它们。

## 输出模式

除本对话之外的一切文字用统一的书面模式：UI 文案与 strings.xml、README、release note、slogan、仓库 description、commit message、PR 正文、代码注释、设计文档。口语只存在于我和你的对话里。

口语在这些位置有两个代价：不严肃，且更长。「一直没加载出来」七个字，「未加载」三个字，信息量相同。改写之后更短，是这条是否落实的检验方式。

具体判别样本见 writing-style skill；未调起该 skill 时本条同样生效。

## 硬门控

以下四条由 `~/.claude/hooks/` 的 PreToolUse hook 和 `~/.claude/shim/` 的 PATH 替身强制执行，Bash 与 PowerShell 两个工具都覆盖。

**改文件**。改动前检查文件是否被 git 跟踪。已跟踪的直接放行；未跟踪的（不在仓库内、新建未 add、或被 .gitignore 排除）先复制一份 `<文件名>.<时间戳>.bak` 再放行。不要读取、提交或清理这些 .bak。

**删文件**。删除用 `trash-put`，找回用 `trash-list` 和 `trash-restore`。Bash 工具里直接写 `rm` 同样安全，PATH 中的替身会将其转为回收站操作。以下三种写法绕过替身且不可恢复，会被 hook 拒绝：

- 绝对路径调用，如 `/bin/rm`
- `sudo rm`，sudo 使用 secure_path，不解析用户 PATH
- `find -delete`，删除在 find 进程内完成，不经过外部命令

**PowerShell 工具里没有替身**：`rm`、`del`、`ri`、`rd`、`erase` 都是 `Remove-Item` 的内建别名，别名解析先于 PATH 查找，替身没有介入的机会。那边所有文件删除一律被拒绝，改用 `trash <路径>`。`[IO.File]::Delete()` 一类 .NET 调用同样被拒。删别名和环境变量（`Remove-Item Alias:x`、`Env:X`）不算文件删除，放行。

确需不可恢复的删除时加 `CLAUDE_ALLOW_RM=1` 前缀，并事先向我确认。

是否构成本机删除由词法切分判定，不做正则匹配。`adb shell rm -rf /data/x`、`ssh box rm -rf /srv` 一类不受影响，其中的 `rm` 是宿主命令的参数，不在本机执行。

**git 破坏性命令**。`reset`、`checkout`、`restore`、`clean`、`rebase`、`merge`、`switch`、`cherry-pick`、`revert`、`am` 在工作区存在未提交改动时先快照再放行：已跟踪的改动写入 `refs/claude-autobak/<时间戳>`，未跟踪文件打包至 `~/.claude/backups/git-autobak/`。`stash drop|clear|pop` 前将现有 stash 记录到独立 ref。快照由 `git stash create` 生成，不修改工作区和索引。快照提示中的恢复方式需转述给我。

快照不构成执行破坏性命令的理由。工作区存在未提交改动时，先说明将丢失哪些内容及原因，再执行。

**装包**。全局安装被拒绝：落在机器级目录，不随项目走，版本也无法在仓库里声明。`npm`/`pnpm` 带 `-g`、`yarn global add`、`pip install`、`python -m pip install` 都在此列。

一次性执行工具用 `deno x <tool>`（Python 侧用 `uvx <tool>`）；脚本临时依赖用 `uv run --with <pkg>`；项目依赖装到本地，用 `npm add`、`uv add`、`pixi add`。

确需全局安装时加 `CLAUDE_ALLOW_GLOBAL_INSTALL=1` 前缀，并事先向我确认。同样由词法切分判定，`docker exec c1 npm i -g x` 不受影响，安装发生在容器里。

## 提交与 PR

**自有仓库不走 PR**。直接在默认分支上提交，不开分支、不建 PR。改动大时按主题拆成多个 commit，不必合并为一个。以下 commit 写法同样适用。

**向上游贡献才走 fork 与 PR**：`origin` 是 fork，`upstream` 是上游，`remote.pushDefault` 设为 `origin`。从上游默认分支拉新分支，`git push -u origin <分支>`，再 `gh pr create --draft`。默认 draft，由我转 ready for review。这条路一个 PR 一个 commit。

commit 标题写作 `type(scope): 英文小写祈使句`，无句号，70 字符内；type 用 `feat`、`fix`、`perf`，scope 沿用仓库已有的。走 PR 时 commit headline 与 PR 标题逐字相同。

commit message 正文用英文，手动硬换行 80 列内，不能为空。

PR 正文语言跟随仓库，陈述与 commit message 相同的事实和顺序，截图和日志放这里，不加 Claude Code 尾注。结构按内容定；中文用词统一为概述、根因、改动、验证。关联 issue 用 `Fixes #NNNN` 放末尾。

## 本机环境

@LOCAL.md

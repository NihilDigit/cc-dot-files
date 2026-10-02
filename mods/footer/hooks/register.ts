import type { EngineInterface, Register, SessionRateLimit } from 'claude-code'

// 上下文与配额的警戒线、危险线，单位为百分比
const WARN_CTX = 75, CRIT_CTX = 90
const WARN_QUOTA = 60, CRIT_QUOTA = 85

// 常驻的快捷键提示，? 里都查得到，占掉的宽度留给状态段；
// 「Press Ctrl-C again to exit」这类一次性提示不在此列，照常显示
const NOISE = ['(shift+tab to cycle)', '← for agents', 'esc to interrupt']

type Git = {
  head: string
  ahead: number, behind: number
  staged: number, modified: number, untracked: number, conflicted: number
} | null

const DEFAULT_BRANCHES = ['main', 'master']

// Nerd Font 图标，写成转义：私有区字符在多数编辑器里显示为空白，直接写看不出是哪个
const ICON = {
  branch: '\ue725',
  ahead: '\uf062',
  behind: '\uf063',
  staged: '\uf067',
  modified: '\uf044',
  untracked: '\uf128',
  conflicted: '\uf071',
  clean: '\uf00c',
  compact: '\uf066',
  cold: '\uf253',
}

const GAP = 2
const SEP = ' · '
const CTX_CELLS = 6
const QUOTA_CELLS = 6
// 按 One Dark 取色，与终端配色一致；换浅色主题时轨道色需要跟着换
const HEX = {
  normal: '#7f848e',
  yellow: '#e5c07b',
  red: '#e06c75',
  green: '#98c379',
  cyan: '#56b6c2',
  magenta: '#c678dd',
  track: '#3e4451',
} as const
// 最长的 pill 约为「⏵⏵ accept edits on」加图标余量
const PILL_RESERVE = 24
// band 右上角是 engine 的折叠按钮 [-]，不让开会压住最后几个字符
const COLLAPSE_RESERVE = 4
// 上下文超过这么多 token 就提醒 compact
const COMPACT_AT = 512_000
// 主线程的 prompt cache TTL。mod 读不到缓存是否还热，只能按最后一次回复的时间推算；
// 进入 overage 后 TTL 降为 5 分钟，这时提示会偏晚
const CACHE_TTL_MS = 60 * 60 * 1000

let path = ''
let git: Git = null
// 本模块加载以来最后一次回复结束的时刻；模块重载后归零，到下一次回复前不提示冷缓存
let lastReplyAt = 0

function stripNoise(hint: string): string {
  return hint
    .split(' · ')
    .filter(part => !NOISE.includes(part.trim()))
    .join('  ')
}

// 家目录记作 ~，分隔符统一为 /
function tildePath(cwd: string, home: string | undefined): string {
  const p = cwd.replace(/\\/g, '/').replace(/\/+$/, '')
  const h = home?.replace(/\\/g, '/').replace(/\/+$/, '')
  if (h && (p === h || p.toLowerCase().startsWith(h.toLowerCase() + '/'))) return '~' + p.slice(h.length)
  return p
}

// 宽度不够时的窄版本，同 fish 的 prompt_pwd：中间各级取首字符（隐藏目录保留点），首级与末级写全
function abbreviate(p: string): string {
  const parts = p.split('/')
  return parts
    .map((seg, i) => i === parts.length - 1 || i === 0 ? seg : seg.startsWith('.') ? seg.slice(0, 2) : seg.slice(0, 1))
    .join('/')
}

// 只显示系列名；认不出的 id 原样显示
const FAMILIES = ['Opus', 'Fable', 'Sonnet', 'Haiku']
function modelLabel(id: string): string {
  return FAMILIES.find(f => id.toLowerCase().includes(f.toLowerCase())) ?? id
}

// 300k、1.2M
function tokens(count: number): string {
  if (count >= 1_000_000) return `${+(count / 1_000_000).toFixed(1)}M`
  return `${Math.round(count / 1000)}k`
}

// 未到警戒线时返回 undefined，调用方据此画暗色
function tone(pct: number, warn: number, crit: number): string | undefined {
  if (pct >= crit) return HEX.red
  if (pct >= warn) return HEX.yellow
  return undefined
}

// 距重置还有多久，只取最大的一级单位并四舍五入：2d、5h、45m
function countdown(iso: string, now: number): string {
  const minutes = Math.max(0, Math.round((Date.parse(iso) - now) / 60000))
  if (minutes >= 1440) return `${Math.round(minutes / 1440)}d`
  if (minutes >= 60) return `${Math.round(minutes / 60)}h`
  return `${minutes}m`
}

// porcelain v2：1/2 开头是普通与重命名条目，XY 两位分别是暂存区与工作区；u 是冲突；? 是未跟踪
function parseGit(stdout: string): Git {
  let head: string | null = null, oid: string | null = null
  const state = { ahead: 0, behind: 0, staged: 0, modified: 0, untracked: 0, conflicted: 0 }
  for (const line of stdout.split('\n')) {
    if (line.startsWith('# branch.head ')) head = line.slice(14).trim()
    else if (line.startsWith('# branch.oid ')) oid = line.slice(13).trim()
    else if (line.startsWith('# branch.ab ')) {
      const m = /\+(\d+) -(\d+)/.exec(line)
      if (m) { state.ahead = Number(m[1]); state.behind = Number(m[2]) }
    } else if (line.startsWith('1 ') || line.startsWith('2 ')) {
      if (line[2] !== '.') state.staged++
      if (line[3] !== '.') state.modified++
    } else if (line.startsWith('u ')) state.conflicted++
    else if (line.startsWith('? ')) state.untracked++
  }
  if (head === '(detached)') head = oid && oid !== '(initial)' ? oid.slice(0, 7) : null
  return head ? { head, ...state } : null
}

// git 在事件里跑，不在 ui.render 里跑：render 随 props 变化频繁触发，一次 git 要几十毫秒
async function refreshGit($: EngineInterface) {
  try {
    const { exitCode, stdout } = await $.process.run(
      ['git', 'status', '--porcelain=v2', '--branch', '--untracked-files=normal'], { timeoutMs: 2000 })
    git = exitCode === 0 ? parseGit(stdout) : null
  } catch {
    git = null
  }
  $.ui.invalidate('ui.render')
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    path = tildePath(e.cwd, (await $.env.get('USERPROFILE')) ?? (await $.env.get('HOME')))
    await refreshGit($)
    // 用量在每次 API 响应后变化，props 不变时 engine 不会自己重画；usage() 不发请求，定时重画开销可忽略。
    // 配额倒计时也靠它走动
    $.clock.every(3000, () => $.ui.invalidate('ui.render'))
    return next(e)
  })

  on('tool.call', async ($, e, next) => {
    const result = await next(e)
    if (e.tool === 'Bash' || e.tool === 'PowerShell' || e.tool === 'Edit' || e.tool === 'Write') void refreshGit($)
    return result
  })

  on('turn.complete', async ($, e, next) => {
    lastReplyAt = Date.now()
    void refreshGit($)
    return next(e)
  })

  // 只在有提醒时出现：band 与 prompt 之间隔着一行 engine 的上边距，常驻会让 footer 多出两行
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.surface !== 'terminal' || e.props.hasSurvey) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    const { context } = await $.session.usage()
    const alerts = []

    if (context.tokens !== undefined && context.tokens >= COMPACT_AT) {
      alerts.push(Text({ color: HEX.yellow, children: [`${ICON.compact} ${tokens(context.tokens)}  wrap up and compact`] }))
    }
    // 闲置中且已过 TTL：下一条消息要把整段上下文重新写入缓存
    const isCold = lastReplyAt > 0 && !e.props.isWorking && Date.now() - lastReplyAt > CACHE_TTL_MS
    if (isCold && context.tokens) {
      alerts.push(Text({ color: HEX.cyan, children: [`${ICON.cold} ${tokens(context.tokens)}  cache expired`] }))
    }

    if (!alerts.length) return next(e)
    return Box({ flexDirection: 'row', justifyContent: 'flex-end', columnGap: 3,
      width: e.props.bodyColumns - COLLAPSE_RESERVE, children: alerts })
  })

  // prompt 下方只改 engine 这一行的 hint，不自己画树。
  // 自绘 pill 读不到实时权限模式：shift+tab 不经 config.set，transcript 与 statusLine 输入也要等下一条消息才更新。
  // 把 engine 节点放进 Box 与自绘段并排也不行：它会把 pill 后的「·」折到第二行，
  // 而它的祖先 Box 不许设 width、minWidth、height，撑不开也裁不掉。分支与用量因此画在同一行右端的 SessionMode
  on('ui.render', { component: 'PromptHint' }, async ($, e, next) => {
    if (e.surface !== 'terminal') return next(e)

    // pill 的宽度读不到，按最长的模式名预留；放不下时路径换缩写。
    // 路径并入 hint 后 pill 后的分隔符「·」后面有了内容，不至于悬空
    const rest = stripNoise(e.props.hint)
    const room = (e.viewport?.columns ?? 120) - PILL_RESERVE - (rest ? rest.length + GAP : 0)
    const model = modelLabel(await $.session.model())
    const shown = path.length + SEP.length + model.length <= room ? path : abbreviate(path)
    // 与 pill 后 engine 自带的分隔符同一个字符
    const hint = [rest, shown, model].filter(Boolean).join(SEP)
    return next({ ...e, props: { ...e.props, hint } })
  })

  // prompt 下方那一行的右端。不用 prompt 上方的 band：band 与 prompt 之间隔着 engine 给 prompt 的一行上边距，
  // 这行不归 band 管，负 marginBottom 也压不进去（band 按树自身高度占位，高度为 0 时整块被裁掉）
  on('ui.render', { component: 'SessionMode' }, async ($, e, next) => {
    if (e.surface !== 'terminal') return next(e)
    const { Box, Text } = $.ui.resolve(e)
    const { context, rateLimits } = await $.session.usage()
    const children = []

    const where = []
    if (git) {
      // 默认分支上分支名没有信息量，只在别的分支或 detached 时显示
      if (!DEFAULT_BRANCHES.includes(git.head)) {
        where.push(Text({ color: HEX.magenta, children: [`${ICON.branch} ${git.head}`] }))
      }
      // 只画非零项；全为零时画一个勾，与「不在仓库里」区分开
      const marks: [keyof typeof ICON, number, string][] = [
        ['ahead', git.ahead, HEX.cyan],
        ['behind', git.behind, HEX.cyan],
        ['conflicted', git.conflicted, HEX.red],
        ['staged', git.staged, HEX.green],
        ['modified', git.modified, HEX.yellow],
        ['untracked', git.untracked, HEX.normal],
      ]
      const dirty = marks.filter(([, count]) => count > 0)
      for (const [icon, count, color] of dirty) where.push(Text({ color, children: [`${ICON[icon]} ${count}`] }))
      if (!dirty.length) where.push(Text({ color: HEX.green, children: [ICON.clean] }))
    }

    if (typeof context.percent === 'number') {
      const pct = Math.min(context.percent, 100)
      const c = tone(pct, WARN_CTX, CRIT_CTX)
      const full = Math.min(Math.round(pct / 100 * CTX_CELLS), CTX_CELLS)
      // 整格色块用背景色铺空格，与 5h/7d 叠条等高；制表符线段太细，░ 在部分字体里又渲染成点阵网纹
      const used = context.tokens === undefined ? `${Math.round(pct)}%` : `${tokens(context.tokens)}/${tokens(context.window)}`
      children.push(Text({ children: [
        Text({ dimColor: true, children: ['ctx '] }),
        Text({ backgroundColor: c ?? HEX.normal, children: [' '.repeat(full)] }),
        Text({ backgroundColor: HEX.track, children: [' '.repeat(CTX_CELLS - full)] }),
        Text({ color: c, dimColor: !c, children: [` ${used}`] }),
      ] }))
    }

    // 5h 与 7d 叠在同一行高里：▀ 的上半格取前景色画 5h，下半格取背景色画 7d。
    // 未填满的半格要画成轨道色，否则下半格空着时看不出条的长度；轨道色和填充色因此只能用定值，不能用 dimColor。
    // 条右侧按上下顺序写两个窗口的用量与距重置多久
    const top = rateLimits.find(r => r.kind === 'five_hour')
    const bottom = rateLimits.find(r => r.kind === 'seven_day')
    if (top && bottom) {
      const now = Date.now()
      const fill = (w: SessionRateLimit) => Math.min(Math.round(w.percentUsed / 100 * QUOTA_CELLS), QUOTA_CELLS)
      const color = (w: SessionRateLimit) => tone(w.percentUsed, WARN_QUOTA, CRIT_QUOTA) ?? HEX.normal
      const left = (w: SessionRateLimit) => {
        const c = tone(w.percentUsed, WARN_QUOTA, CRIT_QUOTA)
        const reset = w.resetsAt ? ` ${countdown(w.resetsAt, now)}` : ''
        return Text({ color: c, dimColor: !c, children: [`${Math.round(w.percentUsed)}%${reset}`] })
      }
      children.push(Text({ children: [
        Text({ dimColor: true, children: ['5h/7d '] }),
        ...Array.from({ length: QUOTA_CELLS }, (_, i) => Text({
          color: i < fill(top) ? color(top) : HEX.track,
          backgroundColor: i < fill(bottom) ? color(bottom) : HEX.track,
          children: ['▀'],
        })),
        Text({ children: [' '] }),
        left(top),
        Text({ dimColor: true, children: [' / '] }),
        left(bottom),
      ] }))
    }

    // engine 原本在这里画的模式标签（focus、memory paused 等）照旧保留，自己画成文本，不嵌 engine 节点
    if (e.props.modes.length) children.push(Text({ dimColor: true, children: [e.props.modes.join(' & ')] }))

    return Box({ flexDirection: 'row', columnGap: 3, children: [
      Box({ flexDirection: 'row', columnGap: 2, children: where }),
      ...children,
    ] })
  })
}

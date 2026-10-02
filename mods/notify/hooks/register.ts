import type { Register } from 'claude-code'

// Claude Code 自带的桌面通知只在 Ghostty、Kitty、iTerm2 里发，Windows Terminal 收不到。
// 挂在 classic.Notification 上，沿用 engine 判断「任务结束或停在权限确认、且人不在终端前」的时机，
// 不自己从 turn.complete 推断

// 按 notification_type 换一句口吻轻松的正文，engine 原文降为第三行细节；没列到的类型直接用原文
const CHEER: Record<string, string> = {
  idle_prompt: 'All done! Your turn ✨',
  permission_prompt: 'Psst… may I? Need your OK to keep going',
  agent_needs_input: 'A helper crab is waiting on you',
  agent_completed: 'A helper crab finished its errand',
  elicitation_dialog: 'A tool has a question for you',
  elicitation_url_dialog: 'A tool has a question for you',
  auth_success: 'Logged in, ready to roll',
  quota_auto_resume_fired: 'Quota is back, picking up where we left off',
}

export const register: Register = on => {
  on('classic.Notification', async ($, e, next) => {
    const result = await next(e)
    // 其他平台的终端有 Claude Code 自己的通知
    if ((await $.env.get('OS')) !== 'Windows_NT') return result

    const systemRoot = (await $.env.get('SystemRoot')) ?? 'C:\\Windows'
    const project = e.cwd.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || e.cwd
    const cheer = CHEER[e.notification_type]
    // 不等进程结束：起 powershell 加载 WinRT 要几百毫秒，没必要拖住 engine 的通知流程
    void $.process.run(
      [`${systemRoot}\\System32\\WindowsPowerShell\\v1.0\\powershell.exe`,
        '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', `${$.plugin.root}/notify.ps1`],
      { env: {
        CC_TOAST_TITLE: encodeURIComponent(project),
        CC_TOAST_BODY: encodeURIComponent(cheer ?? e.message),
        CC_TOAST_DETAIL: encodeURIComponent(cheer ? e.message : ''),
      }, timeoutMs: 10_000 },
    ).catch(() => {})
    return result
  })
}

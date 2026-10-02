# 弹一条 Windows toast。标题、正文与可选的细节行经环境变量传入，事先做过 URL 编码：
# 免去命令行引号转义，也避开中文 Windows 上 stdin 默认按 GBK 解码。
#
# 必须由 Windows PowerShell 5.1 执行：pwsh 7 不能直接加载 WinRT 类型。
#
# AppId 是在 HKCU 下自行登记的，只带显示名与图标，没有可启动的应用：点击通知
# 什么也不做，只把它关掉。借 Windows Terminal 的 AppId 会在点击时新开一个终端
# 窗口，借 Windows PowerShell 的则来源显示为 PowerShell。
# IconUri 只认位图，SVG 不显示，故图标为 PNG。

$appId = 'ClaudeCode.Notify'
$key = "HKCU:\Software\Classes\AppUserModelId\$appId"
$icon = Join-Path $PSScriptRoot 'icon.png'
# 仓库移动后图标路径会变，按值比对而不是只看键在不在
if ((Get-ItemProperty -Path $key -Name IconUri -ErrorAction SilentlyContinue).IconUri -ne $icon) {
    New-Item -Path $key -Force | Out-Null
    Set-ItemProperty -Path $key -Name DisplayName -Value 'Claude Code'
    Set-ItemProperty -Path $key -Name IconUri -Value $icon
}

[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

$title = [Security.SecurityElement]::Escape([Uri]::UnescapeDataString($env:CC_TOAST_TITLE))
$body = [Security.SecurityElement]::Escape([Uri]::UnescapeDataString($env:CC_TOAST_BODY))
$detail = [Security.SecurityElement]::Escape([Uri]::UnescapeDataString($env:CC_TOAST_DETAIL))
# 第三行可选，空则不写，免得 toast 底部多一行空白
$detailXml = if ($detail) { "<text>$detail</text>" } else { "" }

$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml("<toast><visual><binding template=`"ToastGeneric`"><text>$title</text><text>$body</text>$detailXml</binding></visual></toast>")

[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show(
    [Windows.UI.Notifications.ToastNotification]::new($xml))

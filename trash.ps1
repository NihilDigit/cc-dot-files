# Windows 的回收站命令：把参数里的文件与目录送进回收站。Git Bash 的 trash 与
# PowerShell 的 trash.ps1 都是 install.sh 生成的转发入口，实现只有这一份。
#
# 不用 npm 的 trash-cli：它先把参数交给 globby 做通配匹配，再只删匹配到的结果。
# globby 把反斜杠当转义符，C:\... 形式的路径一个也匹配不上，于是什么都没删，退出码
# 却是 0，删除失败与成功无从区分。这里按字面路径处理，不展开通配符，删不掉的路径
# 报错并以非零退出。
#
# 用 SHFileOperation 而不用 Microsoft.VisualBasic 的 FileSystem.DeleteFile：后者最多
# 只能隐藏进度框，出错时（文件被占用）仍弹对话框，无人值守的调用会一直卡在那里。
# FOF_NOERRORUI 让错误变成返回码。代价是不能加 FOF_WANTNUKEWARNING（它同样要弹框），
# 超出回收站容量的项会被直接永久删除；trash-cli 自带的 windows-trash.exe 也是如此。

# 错误信息是中文。不设的话 stderr 按控制台代码页（GBK）编码，Git Bash 按 UTF-8 解读成乱码。
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)

if ($args.Count -eq 0) {
    [Console]::Error.WriteLine('trash: 缺少操作数')
    exit 2
}

$definition = @'
[StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
public struct SHFILEOPSTRUCT {
    public IntPtr hwnd;
    public uint wFunc;
    public string pFrom;
    public string pTo;
    public ushort fFlags;
    [MarshalAs(UnmanagedType.Bool)] public bool fAnyOperationsAborted;
    public IntPtr hNameMappings;
    public string lpszProgressTitle;
}
[DllImport("shell32.dll", CharSet = CharSet.Unicode)]
public static extern int SHFileOperationW(ref SHFILEOPSTRUCT op);
'@

# Add-Type 每次现编要 0.8 秒，比 pwsh 启动本身还慢，而 rm 替身的每次删除都经过这里。
# 编译结果缓存成 DLL，文件名带定义的哈希，定义改了自然换新文件。先写临时名再改名，
# 两个进程同时首次运行也不会读到写了一半的 DLL。
$hash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($definition))).Substring(0, 12)
$cacheDir = Join-Path $env:LOCALAPPDATA 'cc-dot-files'
$dll = Join-Path $cacheDir "trash-shell-$hash.dll"
if (-not (Test-Path -LiteralPath $dll)) {
    New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null
    $tmp = "$dll.$PID.tmp"
    Add-Type -Namespace CcDotFiles -Name Shell -MemberDefinition $definition -OutputAssembly $tmp -OutputType Library
    Move-Item -LiteralPath $tmp -Destination $dll -Force
}
Add-Type -LiteralPath $dll

$FO_DELETE = 3
$FOF_SILENT = 0x4
$FOF_NOCONFIRMATION = 0x10
$FOF_ALLOWUNDO = 0x40
$FOF_NOERRORUI = 0x400

$failed = 0
$literal = $false
foreach ($arg in $args) {
    if (-not $literal -and $arg -eq '--') {
        $literal = $true
        continue
    }
    # trash-cli 会忽略 rm 的 -r、-f 一类选项。这里不猜测其含义，直接拒绝：
    # 以 - 开头的路径写在 -- 之后。
    if (-not $literal -and $arg.StartsWith('-')) {
        [Console]::Error.WriteLine("trash: 不支持选项 $arg；以 - 开头的路径写在 -- 之后")
        exit 2
    }

    $item = Get-Item -LiteralPath $arg -Force -ErrorAction SilentlyContinue
    if (-not $item) {
        [Console]::Error.WriteLine("trash: 不存在：$arg")
        $failed++
        continue
    }

    # pFrom 是以双 NUL 结尾的路径列表。逐个路径调用，失败时才能指出是哪一个。
    $op = New-Object CcDotFiles.Shell+SHFILEOPSTRUCT
    $op.wFunc = $FO_DELETE
    $op.pFrom = $item.FullName + "`0`0"
    $op.fFlags = $FOF_SILENT -bor $FOF_NOCONFIRMATION -bor $FOF_ALLOWUNDO -bor $FOF_NOERRORUI
    $code = [CcDotFiles.Shell]::SHFileOperationW([ref]$op)
    if ($code -ne 0 -or $op.fAnyOperationsAborted -or (Test-Path -LiteralPath $item.FullName)) {
        [Console]::Error.WriteLine(('trash: 未能移入回收站：{0}（SHFileOperation 返回 0x{1:X}，常见原因是文件被占用）' -f $arg, $code))
        $failed++
    }
}

exit [int]($failed -gt 0)

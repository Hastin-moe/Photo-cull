# 照片工具：Windows 环境部署。找 Python（没有就用 winget 装），再交给 tools\setup_env.py 建环境、装依赖、做检查。
# 由「安装环境.bat」和启动文件调用；参数原样传给 setup_env.py（例如 -- --mirror tuna、--recreate、--check）。
param([switch]$Quiet, [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest)
$ErrorActionPreference = "Continue"   # 原生程序（pip 等）往 stderr 写警告时不要中断，统一看退出码
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

function Test-Python([string]$exe, [string[]]$pre) {
    try {
        $out = & $exe @pre -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { return $false }
        $parts = "$out".Trim().Split(".")
        return ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 9)
    } catch { return $false }
}

function Find-Python {
    # py 启动器、PATH 里的 python、以及常见安装位置；跳过微软商店的 python 占位程序
    $cands = @(@{ exe = "py"; pre = @("-3") }, @{ exe = "python"; pre = @() })
    foreach ($dir in @("$env:LOCALAPPDATA\Programs\Python", "$env:ProgramFiles\Python*", "$env:ProgramFiles")) {
        Get-ChildItem -Path $dir -Filter "python.exe" -Recurse -Depth 2 -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -notmatch "WindowsApps" } |
            Sort-Object FullName -Descending | ForEach-Object { $cands += @{ exe = $_.FullName; pre = @() } }
    }
    foreach ($c in $cands) {
        if (Test-Python $c.exe $c.pre) { return $c }
    }
    return $null
}

$VPy = Join-Path $Root ".venv-win\Scripts\python.exe"
if ((Test-Path -LiteralPath $VPy) -and (Test-Python $VPy @())) {
    $py = @{ exe = $VPy; pre = @() }          # 环境已经在：用它自己检查／更新即可
} else {
    $py = Find-Python
    if (-not $py) {
        Write-Host "没有找到 Python 3.9 或更高版本。"
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            Write-Host "可以用 Windows 自带的 winget 自动安装 Python 3.12（只装给当前用户，需要联网，约 1–3 分钟）。"
            $ans = Read-Host "按回车开始安装；输入 n 再回车则取消"
            if ($ans -eq "n") { exit 1 }
            winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
            $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
            $py = Find-Python
        }
        if (-not $py) {
            Write-Host "请从 https://www.python.org/downloads/ 安装 Python 3.12（安装时勾选「Add python.exe to PATH」），然后重新运行。"
            exit 1
        }
    }
}

$argsList = @((Join-Path $Root "tools\setup_env.py"))
if ($Quiet) { $argsList += "--quiet-if-ready" }
if ($Rest) { $argsList += $Rest }
& $py.exe @($py.pre) @argsList
exit $LASTEXITCODE

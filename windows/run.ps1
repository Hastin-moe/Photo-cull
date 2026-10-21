# 照片筛选／照片编辑：Windows 启动脚本（由 启动筛选.bat／启动编辑.bat 调用）。
# 环境没准备好时先调用 setup.ps1（第一次运行会联网安装），然后启动程序。
param([ValidateSet("cull", "edit")][string]$App = "cull")
$ErrorActionPreference = "Continue"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root
$Names = @{ cull = "照片筛选"; edit = "照片编辑" }
try { $Host.UI.RawUI.WindowTitle = $Names[$App] } catch {}
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

& (Join-Path $PSScriptRoot "setup.ps1") -Quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "运行环境没有准备好。可以双击「安装环境.bat」查看详细检查结果。"
    Read-Host "按回车键关闭" | Out-Null
    exit 1
}
$VPy = Join-Path $Root ".venv-win\Scripts\python.exe"
& $VPy (Join-Path $Root "gui.py") --app $App
if ($LASTEXITCODE -ne 0) { Read-Host "程序异常退出，按回车键关闭" | Out-Null; exit $LASTEXITCODE }

# deploy.ps1 —— 一键把 IPTV 自动采集器部署到 GitHub 私人仓库
# 在你的电脑上（git 能正常登录 GitHub 的环境）运行：
#   powershell -ExecutionPolicy Bypass -File deploy.ps1
# 或在文件管理器里右键「使用 PowerShell 运行」。
$ErrorActionPreference = "Stop"

$Repo      = "admin11044/iptv-1080p-4k"   # 你的私人仓库
$Base      = $PSScriptRoot                # 本脚本所在目录（iptv-auto-collector）
$DeployDir = Join-Path $Base "_repo"

if (Test-Path $DeployDir) { Remove-Item $DeployDir -Recurse -Force }

Write-Host "== 1/4 克隆仓库 $Repo =="
git clone "https://github.com/$Repo.git" "$DeployDir"

Write-Host "== 2/4 复制项目文件 =="
Copy-Item "$Base\collect.py"       "$DeployDir\collect.py"       -Force
Copy-Item "$Base\sources.txt"      "$DeployDir\sources.txt"      -Force
Copy-Item "$Base\requirements.txt" "$DeployDir\requirements.txt" -Force
Copy-Item "$Base\README.md"        "$DeployDir\README.md"        -Force
Copy-Item "$Base\.github"          "$DeployDir\.github"          -Recurse -Force

Write-Host "== 3/4 提交 =="
Set-Location $DeployDir
git add -A
git commit -m "feat: IPTV auto-collector (1080p/4k) + GitHub Actions"

Write-Host "== 4/4 推送（会弹出 GitHub 登录就正常登录）=="
git push origin HEAD

Write-Host ""
Write-Host "==== 完成 ===="
Write-Host "订阅链接（把下面任一镜像前缀拼到 raw 地址前，挑能打开的）："
Write-Host "原始:  https://raw.githubusercontent.com/$Repo/main/output/4k.m3u"
Write-Host "镜像1: https://ghproxy.net/https://raw.githubusercontent.com/$Repo/main/output/4k.m3u"
Write-Host "镜像2: https://ghfast.top/https://raw.githubusercontent.com/$Repo/main/output/4k.m3u"
Write-Host "镜像3: https://gh.llkk.cc/https://raw.githubusercontent.com/$Repo/main/output/4k.m3u"
Write-Host "（想要 1080P 为主用 hd.m3u；全量用 index.m3u；直播 TXT 用 index.txt）"

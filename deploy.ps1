# ========================================
# NovaMind 一键部署脚本 (Windows PowerShell)
# ========================================
# 用法:
#   .\deploy.ps1 deploy    # 全新部署（默认）
#   .\deploy.ps1 update    # 重新构建并更新 app 容器
#   .\deploy.ps1 status    # 显示所有服务状态
#   .\deploy.ps1 logs      # 跟踪应用日志
#   .\deploy.ps1 stop      # 停止服务（保留数据）
#   .\deploy.ps1 clean     # 停止并清除数据卷
#   .\deploy.ps1           # 等同于 deploy
#
# 需要: Docker Desktop 20.10+, Docker Compose V2+
# 执行策略: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

$ErrorActionPreference = "Stop"

# ─── 颜色函数 ──────────────────────────────────────────
function Write-Info($msg)  { Write-Host "✓ $msg" -ForegroundColor Green }
function Write-Warn($msg)  { Write-Host "⚠ $msg" -ForegroundColor Yellow }
function Write-Err($msg)   { Write-Host "✗ $msg" -ForegroundColor Red }
function Write-Step($msg)  { Write-Host "▸ $msg" -ForegroundColor Cyan }
function Write-Bold($msg)  { Write-Host $msg -ForegroundColor White }

# ─── ASCII Banner ──────────────────────────────────────
function Print-Banner {
    Write-Host ""
    Write-Host "  _   _                  _   __  __ _       _" -ForegroundColor Cyan
    Write-Host " | \ | |                | | |  \/  (_)     (_)" -ForegroundColor Cyan
    Write-Host " |  \| | ___ _ __   ___| | | \  / |_ _ __  _  ___" -ForegroundColor Cyan
    Write-Host " | . `` |/ _ \ '_ \ / _ \ | | |\/| | | '_ \| |/ _ \" -ForegroundColor Cyan
    Write-Host " | |\  |  __/ | | |  __/ | | |  | | | | | | |  __/" -ForegroundColor Cyan
    Write-Host " |_| \_|\___|_| |_|\___|_| |_|  |_|_|_| |_|_|\___|" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  NovaMind 智能知识库部署工具" -ForegroundColor White
    Write-Host ""
}

# ─── 密码生成 ──────────────────────────────────────────
function New-RandomPassword {
    param([int]$Length = 16)
    $chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $bytes = New-Object byte[] $Length
    $rng.GetBytes($bytes)
    -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
}

function New-RandomHex {
    param([int]$Bytes = 16)
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $buf = New-Object byte[] $Bytes
    $rng.GetBytes($buf)
    -join ($buf | ForEach-Object { $_.ToString("x2") })
}

# ─── 前置检查 ──────────────────────────────────────────
function Test-Docker {
    Write-Step "检查 Docker 环境..."

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Err "未找到 Docker，请先安装 Docker Desktop: https://docs.docker.com/desktop/install/windows-install/"
        exit 1
    }

    try {
        $null = docker info 2>&1
    }
    catch {
        Write-Err "Docker daemon 未运行，请先启动 Docker Desktop"
        exit 1
    }

    $dockerVer = (docker --version) -replace ".*?(\d+\.\d+\.\d+).*", '$1'
    Write-Info "Docker $dockerVer"

    if (-not (docker compose version 2>$null)) {
        Write-Err "未找到 Docker Compose V2，请升级 Docker Desktop"
        exit 1
    }
    $composeVer = (docker compose version --short 2>$null) ?? "V2"
    Write-Info "Docker Compose $composeVer"
}

function Test-Ports {
    $ports = @(80, 3306, 6379, 9005, 9200)
    $names = @("App(80)", "MySQL(3306)", "Redis(6379)", "MinIO(9005)", "ES(9200)")
    $conflicts = 0

    Write-Step "检查端口占用..."

    for ($i = 0; $i -lt $ports.Count; $i++) {
        $port = $ports[$i]
        $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
        if ($conn) {
            # 检查是否被 Docker 容器占用
            $dockerPorts = (docker ps --format "{{.Ports}}" 2>$null) -join ""
            if ($dockerPorts -notmatch "$port") {
                Write-Warn "$($names[$i]) 端口已被占用"
                $conflicts++
            }
        }
    }

    if ($conflicts -gt 0) {
        Write-Warn "检测到 $conflicts 个端口冲突，可能导致服务启动失败"
        $reply = Read-Host "  继续部署？[y/N]"
        if ($reply -notmatch "^[Yy]$") {
            Write-Host "已取消"
            exit 0
        }
    }
    else {
        Write-Info "所有端口可用"
    }
}

# ─── 配置生成 ──────────────────────────────────────────
function New-EnvFile {
    if (Test-Path .env) {
        Write-Info ".env 已存在，跳过"
        return
    }

    Write-Step "创建 .env 配置文件（自动生成随机密码）..."
    Copy-Item .env.example .env

    $mysqlPass = New-RandomHex 16
    $minioUser = New-RandomPassword 8
    $minioPass = New-RandomPassword 16
    $secretKey = New-RandomHex 32
    $encKey = New-RandomHex 16
    $adminPass = "Admin@$(New-RandomPassword 4)"

    $content = Get-Content .env -Raw
    $content = $content -replace "your-mysql-password", $mysqlPass
    $content = $content -replace "your-minio-access-key", $minioUser
    $content = $content -replace "your-minio-secret-key", $minioPass
    $content = $content -replace "your-jwt-secret-key", $secretKey
    $content = $content -replace "your-aes256-encryption-key", $encKey
    $content = $content -replace "your-admin-password", $adminPass
    Set-Content .env $content -NoNewline

    Write-Info ".env 已创建"
    Write-Host ""
    Write-Warn "管理员密码: $adminPass"
    Write-Warn "请妥善保管 .env 文件"
}

function New-ConfigFiles {
    # docker.yaml
    if (-not (Test-Path docker/configs/docker.yaml)) {
        Write-Step "创建 Docker 配置..."
        Copy-Item docker/configs/docker.example docker/configs/docker.yaml
        Write-Info "docker.yaml 已创建"
    }
    else {
        Write-Info "docker.yaml 已存在，跳过"
    }

    # default.yaml
    if (-not (Test-Path backend/src/setting/yaml_config/yaml/default.yaml)) {
        Write-Step "创建后端基础配置..."
        Copy-Item backend/src/setting/yaml_config/yaml/default.example backend/src/setting/yaml_config/yaml/default.yaml
        Write-Info "default.yaml 已创建"
    }
    else {
        Write-Info "default.yaml 已存在，跳过"
    }

    Write-Warn "Docker 部署时敏感配置由 docker.yaml (.env) 覆盖，无需手动编辑"
}

# ─── 健康检查 ──────────────────────────────────────────
function Wait-Healthy {
    param([int]$TimeoutSeconds = 180)

    Write-Step "等待服务就绪（最长 ${TimeoutSeconds}s）..."

    $elapsed = 0
    $interval = 5

    while ($elapsed -lt $TimeoutSeconds) {
        $allHealthy = $true
        $running = (docker compose ps -q 2>$null | Measure-Object).Count

        if ($running -ge 5) {
            $statuses = docker compose ps --format "{{.Health}}" 2>$null
            foreach ($s in $statuses) {
                if ($s -and $s -ne "healthy") {
                    $allHealthy = $false
                    break
                }
            }
            if ($allHealthy) {
                Write-Info "所有服务已启动"
                return
            }
        }

        Start-Sleep -Seconds $interval
        $elapsed += $interval
        Write-Host -NoNewline "  ⏳ 已等待 ${elapsed}s / ${TimeoutSeconds}s`r"
    }

    Write-Host ""
    Write-Warn "等待超时，部分服务可能未就绪"
}

function Test-AppHealth {
    Write-Step "检查应用健康状态..."

    for ($retry = 0; $retry -lt 10; $retry++) {
        try {
            $null = Invoke-WebRequest -Uri "http://localhost/health" -TimeoutSec 5 -UseBasicParsing
            Write-Info "后端健康检查通过"
            return
        }
        catch {
            Start-Sleep -Seconds 3
        }
    }

    Write-Warn "后端健康检查未通过（服务可能仍在初始化）"
}

# ─── 状态打印 ──────────────────────────────────────────
function Print-StatusTable {
    Write-Host ""
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
    Write-Host "  ✅ 部署完成！" -ForegroundColor Green
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
    Write-Host ""
    Write-Bold "服务状态:"
    docker compose ps
    Write-Host ""
    Write-Bold "访问地址:"
    Write-Host "  🌐 前端:      http://localhost"
    Write-Host "  📖 API 文档:  http://localhost/api/v1/docs"
    Write-Host "  📦 MinIO:     http://localhost:9001"
    Write-Host ""
    Write-Bold "管理员账号:"
    Write-Host "  用户名: admin"
    if (Test-Path .env) {
        Write-Host "  密码:   查看 .env 中的 ADMIN_PASSWORD"
    }
    Write-Host ""
    Write-Bold "常用命令:"
    Write-Host "  .\deploy.ps1 status    # 查看服务状态"
    Write-Host "  .\deploy.ps1 logs      # 查看应用日志"
    Write-Host "  .\deploy.ps1 update    # 更新应用"
    Write-Host "  .\deploy.ps1 stop      # 停止服务"
    Write-Host "  .\deploy.ps1 clean     # 停止并清除数据"
    Write-Host ""
}

# ─── 子命令: deploy ────────────────────────────────────
function Invoke-Deploy {
    Print-Banner

    Write-Bold "📋 部署前检查"
    Write-Host ""

    Test-Docker
    Test-Ports
    Write-Host ""

    Write-Bold "📝 生成配置"
    Write-Host ""
    New-EnvFile
    New-ConfigFiles
    Write-Host ""

    # 确认
    Write-Bold "准备启动以下服务:"
    Write-Host "  • app           (前端 + 后端 + Nginx) → http://localhost"
    Write-Host "  • mysql         (MySQL 8.0)            → localhost:3306"
    Write-Host "  • redis         (Redis 7)              → localhost:6379"
    Write-Host "  • minio         (MinIO)                → localhost:9005 / :9001"
    Write-Host "  • elasticsearch (ES 8.15)              → localhost:9200"
    Write-Host ""
    $reply = Read-Host "确认部署？[Y/n]"
    if ($reply -and $reply -notmatch "^[Yy]$") {
        Write-Host "已取消"
        exit 0
    }

    # 构建 & 启动
    Write-Host ""
    Write-Bold "🐳 启动 Docker 服务（首次约 5-10 分钟）..."
    Write-Host ""

    docker compose up -d --build

    Write-Host ""
    Wait-Healthy 180
    Test-AppHealth
    Print-StatusTable
}

# ─── 子命令: update ────────────────────────────────────
function Invoke-Update {
    Print-Banner
    Write-Bold "🔄 更新应用"
    Write-Host ""

    Test-Docker

    Write-Step "重新构建 app 镜像..."
    docker compose build app

    Write-Step "更新 app 容器..."
    docker compose up -d app

    Write-Host ""
    Wait-Healthy 120
    Test-AppHealth

    Write-Host ""
    Write-Info "应用更新完成！"
    Print-StatusTable
}

# ─── 子命令: status ────────────────────────────────────
function Invoke-Status {
    Write-Host ""
    Write-Bold "📊 NovaMind 服务状态"
    Write-Host ""

    try {
        docker compose ps
    }
    catch {
        Write-Err "无法获取服务状态，请确认 Docker 正在运行"
        exit 1
    }

    Write-Host ""

    # 后端健康检查
    try {
        $null = Invoke-WebRequest -Uri "http://localhost/health" -TimeoutSec 5 -UseBasicParsing
        Write-Info "后端健康检查: 正常"
    }
    catch {
        Write-Warn "后端健康检查: 无响应（服务可能未启动）"
    }

    Write-Host ""
}

# ─── 子命令: logs ──────────────────────────────────────
function Invoke-Logs {
    Write-Bold "📜 应用日志（Ctrl+C 退出）"
    Write-Host ""
    docker compose logs -f app
}

# ─── 子命令: stop ──────────────────────────────────────
function Invoke-Stop {
    Print-Banner
    Write-Bold "⏹ 停止服务"
    Write-Host ""

    docker compose down
    Write-Host ""
    Write-Info "所有服务已停止（数据已保留）"
    Write-Host "  使用 .\deploy.ps1 deploy 重新启动"
    Write-Host ""
}

# ─── 子命令: clean ─────────────────────────────────────
function Invoke-Clean {
    Print-Banner
    Write-Host "🗑 清除所有服务和数据" -ForegroundColor Red
    Write-Host ""
    Write-Warn "此操作将删除所有数据卷（MySQL、Redis、MinIO、ES），不可恢复！"
    $reply = Read-Host "确认清除？输入 YES 继续"

    if ($reply -ne "YES") {
        Write-Host "已取消"
        exit 0
    }

    docker compose down -v
    Write-Host ""
    Write-Info "所有服务和数据已清除"
    Write-Host ""
}

# ─── 帮助信息 ──────────────────────────────────────────
function Show-Help {
    Print-Banner
    Write-Bold "用法:"
    Write-Host "  .\deploy.ps1 [命令]"
    Write-Host ""
    Write-Bold "命令:"
    Write-Host "  deploy    全新部署（默认）"
    Write-Host "  update    重新构建并更新 app 容器"
    Write-Host "  status    显示所有服务状态"
    Write-Host "  logs      跟踪应用日志 (Ctrl+C 退出)"
    Write-Host "  stop      停止服务（保留数据）"
    Write-Host "  clean     停止并清除所有数据卷"
    Write-Host ""
}

# ─── 主入口 ────────────────────────────────────────────
$command = if ($args.Count -gt 0) { $args[0].ToLower() } else { "" }

switch ($command) {
    "deploy" { Invoke-Deploy }
    "update" { Invoke-Update }
    "status" { Invoke-Status }
    "logs"   { Invoke-Logs }
    "stop"   { Invoke-Stop }
    "clean"  { Invoke-Clean }
    "help"   { Show-Help }
    "--help" { Show-Help }
    "-h"     { Show-Help }
    ""       { Invoke-Deploy }
    default  {
        Write-Err "未知命令: $command"
        Write-Host ""
        Show-Help
        exit 1
    }
}

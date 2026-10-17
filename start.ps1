<#
NovaMind 本机一键启动：Elasticsearch / MinIO / 后端(8100) / 前端(5173)

前提：环境已安装配置好（服务直装路径、backend/.venv、frontend/node_modules 均就绪）。
本脚本不做依赖安装，只负责启动与探活；幂等可重复执行，已在跑的服务自动跳过。
服务以独立进程（Start-Process Hidden）启动，日志落 $LogDir，随用随查。
#>
param(
    [string]$EsHome = "D:\elasticsearch\elasticsearch-9.3.2",
    [string]$MinioHome = "D:\Minio",
    [string]$LogDir = "C:\tmp\nm_logs",
    [string]$EsJavaOpts = "-Xms512m -Xmx512m",
    [int]$EsPort = 9200,
    [int]$MinioPort = 9005,
    [int]$MinioConsolePort = 9006,
    [int]$BackendPort = 8100,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Write-Info($Message) { Write-Host "[INFO] $Message" -ForegroundColor Green }
function Write-Warn($Message) { Write-Host "[WARN] $Message" -ForegroundColor Yellow }
function Write-Step($Message) { Write-Host "[STEP] $Message" -ForegroundColor Cyan }
function Write-Skip($Message) { Write-Host "[SKIP] $Message" -ForegroundColor DarkGray }

function Test-Port {
    param([string]$HostName, [int]$Port, [int]$TimeoutMs = 800)
    # .NET Framework 的 ConnectAsync(hostname,port) 只按解析顺序逐个试，
    # 前面的 IPv4 地址被防火墙静默丢包时会悬挂，轮不到 ::1——
    # 因此自行解析地址并按地址族逐个直连，任一连通即可
    try {
        $addrs = [System.Net.Dns]::GetHostAddresses($HostName)
    } catch {
        return $false
    }
    foreach ($addr in $addrs) {
        $client = New-Object System.Net.Sockets.TcpClient($addr.AddressFamily)
        try {
            $task = $client.ConnectAsync($addr.ToString(), $Port)
            if ($task.Wait($TimeoutMs) -and $client.Connected) { return $true }
        } catch {
        } finally {
            $client.Dispose()
        }
    }
    return $false
}

function Wait-Port {
    param([string]$Name, [string]$HostName, [int]$Port, [int]$TimeoutSec)
    Write-Step "等待 $Name 就绪 (${HostName}:${Port}，最长 ${TimeoutSec}s) ..."
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-Port -HostName $HostName -Port $Port) {
            Write-Info "$Name 就绪"
            return $true
        }
        Start-Sleep -Seconds 2
    }
    Write-Warn "$Name 在 ${TimeoutSec}s 内未就绪，请查看日志：$LogDir"
    return $false
}

$script:AllReady = $true

function Start-Detached {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$ArgumentList = @(),
        [string]$WorkingDirectory,
        [string]$OutLog,
        [string]$ErrLog
    )
    Write-Step "启动 $Name ..."
    # PS5.1 的 Start-Process -ArgumentList 不接受空数组，空参时省略该参数
    $p = if ($ArgumentList.Count -gt 0) {
        Start-Process -FilePath $FilePath -ArgumentList $ArgumentList `
            -WorkingDirectory $WorkingDirectory -WindowStyle Hidden `
            -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog -PassThru
    } else {
        Start-Process -FilePath $FilePath `
            -WorkingDirectory $WorkingDirectory -WindowStyle Hidden `
            -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog -PassThru
    }
    Write-Info "$Name 已启动 (PID $($p.Id))"
}

Write-Host ""
Write-Host "NovaMind 本地一键启动" -ForegroundColor White
Write-Host ""

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# 1. Elasticsearch（bat 内部起 java，约 40-70s 就绪）
if (Test-Port -HostName "127.0.0.1" -Port $EsPort) {
    Write-Skip "Elasticsearch 已在运行 (端口 $EsPort)"
} else {
    if (-not (Test-Path "$EsHome\bin\elasticsearch.bat")) {
        throw "未找到 $EsHome\bin\elasticsearch.bat，请用 -EsHome 指定安装目录"
    }
    $env:ES_JAVA_OPTS = $EsJavaOpts
    Start-Detached -Name "Elasticsearch" -FilePath "$EsHome\bin\elasticsearch.bat" `
        -WorkingDirectory $EsHome `
        -OutLog "$LogDir\es_out.log" -ErrLog "$LogDir\es_err.log"
    Remove-Item Env:\ES_JAVA_OPTS -ErrorAction SilentlyContinue
    if (-not (Wait-Port -Name "Elasticsearch" -HostName "127.0.0.1" -Port $EsPort -TimeoutSec 120)) { $script:AllReady = $false }
}

# 2. MinIO
if (Test-Port -HostName "127.0.0.1" -Port $MinioPort) {
    Write-Skip "MinIO 已在运行 (端口 $MinioPort)"
} else {
    if (-not (Test-Path "$MinioHome\bin\minio.exe")) {
        throw "未找到 $MinioHome\bin\minio.exe，请用 -MinioHome 指定安装目录"
    }
    Start-Detached -Name "MinIO" -FilePath "$MinioHome\bin\minio.exe" `
        -ArgumentList @('server', "$MinioHome\data", '--address', ":$MinioPort", '--console-address', ":$MinioConsolePort") `
        -WorkingDirectory $MinioHome `
        -OutLog "$LogDir\minio_out.log" -ErrLog "$LogDir\minio_err.log"
    if (-not (Wait-Port -Name "MinIO" -HostName "127.0.0.1" -Port $MinioPort -TimeoutSec 30)) { $script:AllReady = $false }
}

# 3. 后端（端口 8100）
$backendPython = "$RootDir\backend\.venv\Scripts\python.exe"
if (Test-Port -HostName "127.0.0.1" -Port $BackendPort) {
    Write-Skip "后端已在运行 (端口 $BackendPort)"
} else {
    if (-not (Test-Path $backendPython)) {
        throw "未找到 $backendPython，请先在 backend/ 执行 uv sync"
    }
    Start-Detached -Name "后端" -FilePath $backendPython `
        -ArgumentList @('main.py') `
        -WorkingDirectory "$RootDir\backend" `
        -OutLog "$LogDir\backend_out.log" -ErrLog "$LogDir\backend_err.log"
    if (-not (Wait-Port -Name "后端" -HostName "127.0.0.1" -Port $BackendPort -TimeoutSec 60)) { $script:AllReady = $false }
}

# 4. 前端（vite 绑定 localhost，注意用 localhost 而非 127.0.0.1 探活）
if (Test-Port -HostName "localhost" -Port $FrontendPort) {
    Write-Skip "前端已在运行 (端口 $FrontendPort)"
} else {
    if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
        throw "npm 不在 PATH 中，请确认 Node.js 已安装"
    }
    Start-Detached -Name "前端" -FilePath "npm.cmd" `
        -ArgumentList @('run', 'dev') `
        -WorkingDirectory "$RootDir\frontend" `
        -OutLog "$LogDir\frontend_out.log" -ErrLog "$LogDir\frontend_err.log"
    if (-not (Wait-Port -Name "前端" -HostName "localhost" -Port $FrontendPort -TimeoutSec 60)) { $script:AllReady = $false }
}

Write-Host ""
Write-Info "本地环境入口："
Write-Host "  前端    http://localhost:$FrontendPort"
Write-Host "  后端    http://127.0.0.1:$BackendPort  (健康检查 /health/detailed)"
Write-Host "  MinIO   http://127.0.0.1:$MinioPort  (控制台 :$MinioConsolePort)"
Write-Host "  ES      http://127.0.0.1:$EsPort"
Write-Host "日志目录：$LogDir"
Write-Host ""
if (-not $script:AllReady) { exit 1 }

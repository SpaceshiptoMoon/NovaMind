$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RootDir

function Write-Info($Message) { Write-Host "[INFO] $Message" -ForegroundColor Green }
function Write-Warn($Message) { Write-Host "[WARN] $Message" -ForegroundColor Yellow }
function Write-Err($Message) { Write-Host "[ERROR] $Message" -ForegroundColor Red }
function Write-Step($Message) { Write-Host "[STEP] $Message" -ForegroundColor Cyan }

function Show-Banner {
    Write-Host ""
    Write-Host "NovaMind Docker Deploy" -ForegroundColor White
    Write-Host ""
}

function Test-Command($Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing required command: $Name"
    }
}

function Test-DockerEnvironment {
    Write-Step "Checking Docker environment"
    Test-Command "docker"
    docker info *> $null
    docker compose version *> $null
}

function New-RandomPassword([int]$Length = 16) {
    # 含大小写+数字，保证生成的管理员密码满足后端强度校验（四类字符缺一不可）
    $chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789".ToCharArray()
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $bytes = New-Object byte[] $Length
    $rng.GetBytes($bytes)
    -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
}

function New-RandomHex([int]$Bytes = 16) {
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $buffer = New-Object byte[] $Bytes
    $rng.GetBytes($buffer)
    -join ($buffer | ForEach-Object { $_.ToString("x2") })
}

function Ensure-EnvFile {
    if (Test-Path ".env") {
        Write-Info ".env already exists"
        return
    }

    if (-not (Test-Path ".env.example")) {
        throw "Missing .env.example"
    }

    Write-Step "Creating .env from .env.example"
    Copy-Item ".env.example" ".env"

    $content = Get-Content ".env" -Raw
    $content = $content.Replace("your-mysql-password", (New-RandomHex 16))
    $content = $content.Replace("your-minio-access-key", (New-RandomPassword 8))
    $content = $content.Replace("your-minio-secret-key", (New-RandomPassword 16))
    $content = $content.Replace("your-es-password", (New-RandomHex 16))
    $content = $content.Replace("your-jwt-secret-key", (New-RandomHex 32))
    $content = $content.Replace("your-aes256-encryption-key", (New-RandomHex 16))
    # Admin@ 前缀带大写+特殊字符；追加固定段保证小写与数字必现（随机 hex 可能全同字符类，
    # 例如全小写无大写、全字母无数字），彻底满足四类字符校验。
    $content = $content.Replace("your-admin-password", "Admin@1$(New-RandomPassword 8)")
    Set-Content ".env" $content -NoNewline

    Write-Info ".env created"
}

function Ensure-ConfigFiles {
    if (-not (Test-Path "docker/configs/docker.yaml")) {
        Write-Step "Creating docker/configs/docker.yaml"
        Copy-Item "docker/configs/docker.example" "docker/configs/docker.yaml"
    } else {
        Write-Info "docker/configs/docker.yaml already exists"
    }

    if (-not (Test-Path "backend/src/setting/yaml_config/yaml/default.yaml")) {
        Write-Step "Creating backend default.yaml"
        Copy-Item "backend/src/setting/yaml_config/yaml/default.example" "backend/src/setting/yaml_config/yaml/default.yaml"
    } else {
        Write-Info "backend default.yaml already exists"
    }
}

function Wait-AppHealth([int]$TimeoutSeconds = 180) {
    Write-Step "Waiting for application health"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)

    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-WebRequest -Uri "http://localhost/health" -UseBasicParsing -TimeoutSec 5 *> $null
            Write-Info "Application health check passed"
            return
        } catch {
            Start-Sleep -Seconds 5
        }
    }

    Write-Warn "Health check did not pass within $TimeoutSeconds seconds"
}

function Show-Summary {
    Write-Host ""
    docker compose ps
    Write-Host ""
    Write-Host "Frontend: http://localhost"
    Write-Host "API docs: http://localhost/docs"
    Write-Host "MinIO:    http://localhost:9001"
    Write-Host ""
}

function Invoke-PrepareDeepdocModels {
    # 模型必须在部署期就绪（运行期下载仅是兜底）：deepdoc prepare 下载 OCR/版面/表格
    # 视觉模型 + 段落合并 XGBoost + 公式识别 pix2text-mfr（含 INT8 量化），落宿主机
    # ./backend/.cache/deepdoc（compose 已挂载为 /app/.cache/deepdoc，容器重建不丢）。
    Write-Step "Preparing DeepDoc models (deploy-time download)"
    New-Item -ItemType Directory -Force -Path "backend/.cache/deepdoc" | Out-Null

    # 国内默认走 hf-mirror.com（HF_ENDPOINT 可覆盖为官方源/其它镜像）。
    # 主源失败后的降级换源清单由 .env 的 DEEPDOC_MIRRORS 配置（见 .env.example）。
    # --user 0：宿主机目录属主 uid 与容器 appuser 不同也能写入；文件默认 644，
    # 运行容器 appuser 只读即可。--no-deps：模型下载不依赖 mysql/redis 等基础设施。
    $hfEndpoint = if ($env:HF_ENDPOINT) { $env:HF_ENDPOINT } else { "https://hf-mirror.com" }
    docker compose run --rm --no-deps --user 0 `
        -e PYTHONPATH=/app/src `
        -e HF_ENDPOINT=$hfEndpoint `
        app python -m novamind.engines.document.integrations.deepdoc `
        prepare --include-text-concat --include-formula
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "DeepDoc model download failed — parsing will degrade (formula recognition skipped,"
        Write-Warn "deepdoc full mode unavailable). Retry manually after fixing the network:"
        Write-Warn "  HF_ENDPOINT=https://hf-mirror.com docker compose run --rm --no-deps --user 0 -e PYTHONPATH=/app/src -e HF_ENDPOINT=https://hf-mirror.com app python -m novamind.engines.document.integrations.deepdoc prepare --include-text-concat --include-formula"
        Write-Warn "After the app is up, verify via: curl -s http://localhost/health/detailed (see deepdoc_models)"
    } else {
        Write-Info "DeepDoc models ready under ./backend/.cache/deepdoc"
    }
}

function Invoke-Deploy {
    Show-Banner
    Test-DockerEnvironment
    Ensure-EnvFile
    Ensure-ConfigFiles
    Write-Step "Building and starting services"
    docker compose up -d --build
    Invoke-PrepareDeepdocModels
    Wait-AppHealth 180
    Show-Summary
}

function Invoke-Update {
    Show-Banner
    Test-DockerEnvironment
    Write-Step "Rebuilding app service"
    docker compose up -d --build app
    Invoke-PrepareDeepdocModels
    Wait-AppHealth 120
    Show-Summary
}

function Invoke-Status {
    Test-DockerEnvironment
    docker compose ps
}

function Invoke-Logs {
    Test-DockerEnvironment
    docker compose logs -f app
}

function Invoke-Stop {
    Test-DockerEnvironment
    docker compose down
}

function Invoke-Clean {
    Test-DockerEnvironment
    Write-Warn "This will remove all containers and volumes."
    $reply = Read-Host "Type YES to continue"
    if ($reply -ne "YES") {
        Write-Info "Cancelled"
        return
    }
    docker compose down -v
}

function Show-Help {
    @"
Usage:
  .\deploy.ps1 [command]

Commands:
  deploy   Build and start the full stack
  update   Rebuild and restart the app service
  status   Show compose service status
  logs     Follow app logs
  stop     Stop services
  clean    Stop services and remove volumes
  help     Show this help
"@ | Write-Host
}

$Command = if ($args.Count -gt 0) { $args[0].ToLower() } else { "deploy" }

switch ($Command) {
    "deploy" { Invoke-Deploy }
    "update" { Invoke-Update }
    "status" { Invoke-Status }
    "logs" { Invoke-Logs }
    "stop" { Invoke-Stop }
    "clean" { Invoke-Clean }
    "help" { Show-Help }
    "--help" { Show-Help }
    "-h" { Show-Help }
    default {
        Write-Err "Unknown command: $Command"
        Show-Help
        exit 1
    }
}

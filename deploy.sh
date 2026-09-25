#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }
step() { echo -e "${CYAN}[STEP]${NC} $1"; }

banner() {
  echo ""
  echo -e "${BOLD}NovaMind Docker Deploy${NC}"
  echo ""
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    error "Missing required command: $1"
    exit 1
  fi
}

check_docker() {
  step "Checking Docker environment"
  require_cmd docker
  docker info >/dev/null 2>&1 || { error "Docker daemon is not running"; exit 1; }
  docker compose version >/dev/null 2>&1 || { error "Docker Compose V2 is required"; exit 1; }
}

# 密码/密钥生成直接内联在 ensure_env 的 python heredoc 中（无独立函数）

ensure_env() {
  if [[ -f .env ]]; then
    info ".env already exists"
    return
  fi

  # python 只在首次生成 .env 时需要（密码/密钥随机段）。
  # 探测放在 .env 不存在分支内：无 python 的 Linux 宿主机二次部署/update
  # 不再被无谓阻断。Windows Git Bash 的 `python` 可能是 WindowsApps 存根
  # （退出码 49、不执行代码），实跑检查可筛掉；Linux 新装机常常只有 python3，按 python → python3 顺序探测。
  PYTHON_BIN=""
  for candidate in python python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "import secrets" >/dev/null 2>&1; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
  if [[ -z "$PYTHON_BIN" ]]; then
    error "python is required by deploy.sh to generate secrets but was not found or is not runnable."
    error "On Windows, use deploy.ps1 instead (pure PowerShell, no python dependency):"
    error "  powershell -ExecutionPolicy Bypass -File deploy.ps1"
    error "On Linux/Debian/Ubuntu, install it with: sudo apt-get install python3"
    exit 1
  fi

  if [[ ! -f .env.example ]]; then
    error "Missing .env.example"
    exit 1
  fi

  step "Creating .env from .env.example"
  cp .env.example .env

  "$PYTHON_BIN" - <<'PY'
from pathlib import Path
import secrets
import string

env_path = Path(".env")
text = env_path.read_text(encoding="utf-8")

def password(length: int) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))

replacements = {
    "your-mysql-password": secrets.token_hex(16),
    "your-minio-access-key": password(8),
    "your-minio-secret-key": password(16),
    "your-es-password": secrets.token_hex(16),
    "your-jwt-secret-key": secrets.token_hex(32),
    "your-aes256-encryption-key": secrets.token_hex(16),
    # 管理员密码必须满足后端强度校验（大写+小写+数字+特殊字符，8-30 位）；
    # admin 账户已存在时 reset_password_if_exists 会在每次重启走 UserUpdate 校验，
    # 校验失败 = 启动期 ValidationError 崩溃循环。Admin@1 前缀固定带大写/特殊字符/
    # 数字，随机段保证小写必现（token_hex 可能全同字符类）。
    "your-admin-password": f"Admin@1{secrets.token_hex(8)}",
}

for old, new in replacements.items():
    text = text.replace(old, new)

env_path.write_text(text, encoding="utf-8")
PY

  info ".env created"
}

ensure_configs() {
  if [[ ! -f docker/configs/docker.yaml ]]; then
    step "Creating docker/configs/docker.yaml"
    cp docker/configs/docker.example docker/configs/docker.yaml
  else
    info "docker/configs/docker.yaml already exists"
  fi

  if [[ ! -f backend/src/setting/yaml_config/yaml/default.yaml ]]; then
    step "Creating backend default.yaml"
    cp backend/src/setting/yaml_config/yaml/default.example backend/src/setting/yaml_config/yaml/default.yaml
  else
    info "backend default.yaml already exists"
  fi
}

wait_for_health() {
  local timeout="${1:-180}"
  local elapsed=0

  step "Waiting for services to become healthy"

  while [[ "$elapsed" -lt "$timeout" ]]; do
    if curl -sf http://localhost/health >/dev/null 2>&1; then
      info "Application health check passed"
      return 0
    fi
    sleep 5
    elapsed=$((elapsed + 5))
  done

  warn "Health check did not pass within ${timeout}s"
  warn "The app may still be starting (model downloads, DB migrations). Inspect with: bash deploy.sh logs"
  return 1
}

print_summary() {
  local healthy="${1:-}"
  echo ""
  docker compose ps
  echo ""
  if [[ "$healthy" == "unhealthy" ]]; then
    warn "Deployment finished but the health check did NOT pass — do not treat this as a success."
    warn "Check logs: bash deploy.sh logs   Detailed component status: curl -s http://localhost/health/detailed"
  else
    echo "Frontend: http://localhost"
    echo "API docs: http://localhost/docs"
    echo "MinIO:    http://localhost:9001 (credentials in .env: MINIO_ROOT_USER / MINIO_ROOT_PASSWORD)"
  fi
}

# 从 .env 读 HF_ENDPOINT（部署期下载与运行期同源）。
# 优先级：进程环境变量 > .env 文件值 > 默认值。
# 不用 shell 默认值兜底（${HF_ENDPOINT:-...}）的原因：docker compose run -e 的优先级高于服务的 env_file，
# 兜底会把用户在 .env 里配置的官方源覆盖回默认镜像。
read_env_hf_endpoint() {
  local value=""
  if [[ -f .env ]]; then
    value="$(grep -E '^HF_ENDPOINT=' .env | tail -n 1 | cut -d '=' -f 2- | tr -d '' | sed 's/^"//; s/"$//')"
  fi
  if [[ -n "${HF_ENDPOINT:-}" ]]; then
    echo "$HF_ENDPOINT"
  elif [[ -n "$value" ]]; then
    echo "$value"
  else
    echo "https://huggingface.co"
  fi
}

prepare_deepdoc_models() {
  # 模型必须在部署期就绪（运行期下载仅是兜底）：deepdoc prepare 下载 OCR/版面/表格
  # 视觉模型 + 段落合并 XGBoost + 公式识别 pix2text-mfr（含 INT8 量化），落宿主机
  # ./backend/.cache/deepdoc（compose 已挂载为 /app/.cache/deepdoc，容器重建不丢）。
  step "Preparing DeepDoc models (deploy-time download)"
  mkdir -p backend/.cache/deepdoc

  # 下载源从 .env 的 HF_ENDPOINT 读取（默认官方源，国内环境在 .env 里配 hf-mirror.com）。
  # 主源失败后的降级换源清单由 .env 的 DEEPDOC_MIRRORS 配置（见 .env.example）。
  # --user 0：宿主机目录属主 uid 与容器 appuser 不同也能写入；文件默认 644，
  # 运行容器 appuser 只读即可。--no-deps：模型下载不依赖 mysql/redis 等基础设施。
  if docker compose run --rm --no-deps --user 0 \
      -e PYTHONPATH=/app/src \
      -e HF_ENDPOINT="$(read_env_hf_endpoint)" \
      app python -m novamind.engines.document.integrations.deepdoc \
      prepare --include-text-concat --include-formula; then
    info "DeepDoc models ready under ./backend/.cache/deepdoc"
  else
    warn "DeepDoc model download failed — parsing will degrade (formula recognition skipped,"
    warn "deepdoc full mode unavailable). Retry manually after fixing the network:"
    warn "  HF_ENDPOINT from .env docker compose run --rm --no-deps --user 0 \\"
    warn "    -e PYTHONPATH=/app/src -e HF_ENDPOINT=\"$(bash -c 'source .env 2>/dev/null; echo ${HF_ENDPOINT:-https://huggingface.co}')\" \\"
    warn "    app python -m novamind.engines.document.integrations.deepdoc prepare --include-text-concat --include-formula"
    warn "After the app is up, verify via: curl -s http://localhost/health/detailed | grep -A3 deepdoc_models"
  fi
}

prepare_local_whisper_model() {
  # 本地 ASR 默认模型（faster-whisper-tiny）部署期预装：音频文档未显式配置
  # asr_model 时默认走本地 faster-whisper 转写，模型缺失会让音频解析直接失败。
  # 落宿主机 ./backend/.cache/faster-whisper/tiny（compose 挂载为
  # /app/.cache/faster-whisper，容器重建不丢；运行时默认解析路径已含此目录）。
  step "Preparing local faster-whisper model (deploy-time download)"
  mkdir -p backend/.cache/faster-whisper

  if docker compose run --rm --no-deps --user 0 \
      -e PYTHONPATH=/app/src \
      -e HF_ENDPOINT="$(read_env_hf_endpoint)" \
      -e NOVAMIND_LOCAL_WHISPER_MODEL_DIR=/app/.cache/faster-whisper/tiny \
      app python scripts/download_faster_whisper_model.py; then
    info "faster-whisper tiny model ready under ./backend/.cache/faster-whisper/tiny"
  else
    warn "faster-whisper model download failed — audio parsing without an explicit"
    warn "asr_model will fail until the model is in place. Retry manually:"
    warn "  HF_ENDPOINT from .env docker compose run --rm --no-deps --user 0 \\"
    warn "    -e PYTHONPATH=/app/src -e HF_ENDPOINT=\"$(bash -c 'source .env 2>/dev/null; echo ${HF_ENDPOINT:-https://huggingface.co}')\" \\"
    warn "    -e NOVAMIND_LOCAL_WHISPER_MODEL_DIR=/app/.cache/faster-whisper/tiny \\"
    warn "    app python scripts/download_faster_whisper_model.py"
    warn "Or set knowledge_base.parsing.local_whisper_model_dir to an existing model path."
  fi
}

cmd_deploy() {
  banner
  check_docker
  ensure_env
  ensure_configs
  step "Building and starting services"
  docker compose up -d --build
  prepare_deepdoc_models
  prepare_local_whisper_model
  if wait_for_health 180; then
    print_summary
  else
    print_summary unhealthy
  fi
}

cmd_update() {
  banner
  check_docker
  step "Rebuilding app service"
  docker compose up -d --build app
  prepare_deepdoc_models
  prepare_local_whisper_model
  if wait_for_health 120; then
    print_summary
  else
    print_summary unhealthy
  fi
}

cmd_status() {
  check_docker
  docker compose ps
}

cmd_logs() {
  check_docker
  docker compose logs -f app
}

cmd_stop() {
  check_docker
  docker compose down
}

cmd_clean() {
  check_docker
  warn "This will remove all containers and volumes."
  read -r -p "Type YES to continue: " reply
  if [[ "$reply" != "YES" ]]; then
    info "Cancelled"
    exit 0
  fi
  docker compose down -v
}

cmd_help() {
  cat <<'EOF'
Usage:
  bash deploy.sh [command]

Commands:
  deploy   Build and start the full stack
  update   Rebuild and restart the app service
  status   Show compose service status
  logs     Follow app logs
  stop     Stop services
  clean    Stop services and remove volumes
  help     Show this help
EOF
}

COMMAND="${1:-deploy}"

case "$COMMAND" in
  deploy) cmd_deploy ;;
  update) cmd_update ;;
  status) cmd_status ;;
  logs) cmd_logs ;;
  stop) cmd_stop ;;
  clean) cmd_clean ;;
  help|--help|-h) cmd_help ;;
  *)
    error "Unknown command: $COMMAND"
    cmd_help
    exit 1
    ;;
esac

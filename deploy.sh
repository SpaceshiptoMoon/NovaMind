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

generate_hex() {
  local bytes="${1:-16}"
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$bytes"
  else
    python - <<PY
import secrets
print(secrets.token_hex($bytes))
PY
  fi
}

generate_password() {
  local length="${1:-16}"
  python - <<PY
import secrets, string
alphabet = string.ascii_letters + string.digits
print("".join(secrets.choice(alphabet) for _ in range($length)))
PY
}

ensure_env() {
  if [[ -f .env ]]; then
    info ".env already exists"
    return
  fi

  if [[ ! -f .env.example ]]; then
    error "Missing .env.example"
    exit 1
  fi

  step "Creating .env from .env.example"
  cp .env.example .env

  python - <<'PY'
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
    "your-jwt-secret-key": secrets.token_hex(32),
    "your-aes256-encryption-key": secrets.token_hex(16),
    "your-admin-password": f"Admin@{password(4)}",
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
  return 1
}

print_summary() {
  echo ""
  docker compose ps
  echo ""
  echo "Frontend: http://localhost"
  echo "API docs: http://localhost/api/v1/docs"
  echo "MinIO:    http://localhost:9001"
  echo ""
}

cmd_deploy() {
  banner
  check_docker
  ensure_env
  ensure_configs
  step "Building and starting services"
  docker compose up -d --build
  wait_for_health 180 || true
  print_summary
}

cmd_update() {
  banner
  check_docker
  step "Rebuilding app service"
  docker compose up -d --build app
  wait_for_health 120 || true
  print_summary
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

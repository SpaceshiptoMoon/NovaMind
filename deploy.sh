#!/bin/bash
# ========================================
# NovaMind 一键部署脚本
# ========================================
# 用法:
#   bash deploy.sh          # 交互式部署
#   bash deploy.sh --quick  # 跳过确认直接部署
#
# 需要: Docker 20.10+, Docker Compose V2+

set -e

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo "  _   _                  _   __  __ _       _"
echo " | \ | |                | | |  \/  (_)     (_)"
echo " |  \| | ___ _ __   ___| | | \  / |_ _ __  _  ___"
echo " | . \` |/ _ \ '_ \ / _ \ | | |\/| | | '_ \| |/ _ \\"
echo " | |\  |  __/ | | |  __/ | | |  | | | | | | |  __/"
echo " |_| \_|\___|_| |_|\___|_| |_|  |_|_|_| |_|_|\___|"
echo ""
echo "  🚀 智能知识库一键部署"
echo ""

QUICK_MODE=false
if [ "$1" = "--quick" ] || [ "$1" = "-q" ]; then
    QUICK_MODE=true
fi

# ---- 工具函数 ----
info()  { echo -e "${GREEN}✓${NC} $1"; }
warn()  { echo -e "${YELLOW}⚠${NC} $1"; }
error() { echo -e "${RED}✗${NC} $1"; }

generate_password() {
    # 兼容 Linux 和 macOS
    if command -v openssl &>/dev/null; then
        openssl rand -hex "$1"
    else
        cat /dev/urandom | head -c "$(( $1 * 2 ))" | hexdump -e '"%02x"'
    fi
}

# ---- 1. 前置检查 ----
echo "📋 检查环境..."

if ! command -v docker &>/dev/null; then
    error "未找到 Docker，请先安装: https://docs.docker.com/get-docker/"
    exit 1
fi
info "Docker $(docker --version | grep -oP '\d+\.\d+\.\d+')"

if ! docker compose version &>/dev/null; then
    error "未找到 Docker Compose V2，请升级 Docker"
    exit 1
fi
info "Docker Compose $(docker compose version --short 2>/dev/null || echo 'V2')"

echo ""

# ---- 2. 创建 .env ----
if [ ! -f .env ]; then
    echo "📝 创建 .env 配置文件（自动生成随机密码）..."
    cp .env.example .env

    # 生成随机密码并替换占位符
    MYSQL_PASS=$(generate_password 16)
    MINIO_USER=$(generate_password 8)
    MINIO_PASS=$(generate_password 16)
    ES_PASS=$(generate_password 16)
    SECRET_KEY=$(generate_password 32)
    ENCRYPTION_KEY=$(generate_password 16)
    ADMIN_PASS="Admin@$(generate_password 4)"

    # 跨平台 sed (macOS sed -i 需要 '' 参数，使用 perl 替代)
    replace_in_file() {
        perl -pi -e "s/$1/$2/g" .env
    }

    replace_in_file "your-mysql-password" "$MYSQL_PASS"
    replace_in_file "your-minio-access-key" "$MINIO_USER"
    replace_in_file "your-minio-secret-key" "$MINIO_PASS"
    replace_in_file "your-elasticsearch-password" "$ES_PASS"
    replace_in_file "your-jwt-secret-key" "$SECRET_KEY"
    replace_in_file "your-aes256-encryption-key" "$ENCRYPTION_KEY"
    replace_in_file "your-admin-password" "$ADMIN_PASS"

    info ".env 已创建（随机密码）"
    echo ""
    warn "管理员密码: $ADMIN_PASS"
    warn "请妥善保管 .env 文件"
else
    info ".env 已存在，跳过"
fi

echo ""

# ---- 3. 创建 docker.yaml ----
if [ ! -f docker/configs/docker.yaml ]; then
    echo "📝 创建 Docker 配置..."
    cp docker/configs/docker.example docker/configs/docker.yaml
    info "docker.yaml 已创建"
else
    info "docker.yaml 已存在，跳过"
fi

# ---- 4. 创建 default.yaml (Docker 构建需要) ----
if [ ! -f backend/src/setting/yaml_config/yaml/default.yaml ]; then
    echo "📝 创建后端基础配置..."
    cp backend/src/setting/yaml_config/yaml/default.example backend/src/setting/yaml_config/yaml/default.yaml
    info "default.yaml 已创建"
    warn "Docker 部署时敏感配置由 docker.yaml (.env) 覆盖，无需手动编辑"
else
    info "default.yaml 已存在，跳过"
fi

echo ""

# ---- 5. 确认部署 ----
if [ "$QUICK_MODE" = false ]; then
    echo "准备启动以下服务:"
    echo "  • app          (前端 + 后端 + Nginx) → http://localhost"
    echo "  • mysql        (MySQL 8.0)            → localhost:3306"
    echo "  • redis        (Redis 7)              → localhost:6379"
    echo "  • minio        (MinIO)                → localhost:9005 / :9001"
    echo "  • elasticsearch (ES 8.15)             → localhost:9200"
    echo ""
    read -p "确认部署？[Y/n] " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]] && [[ -n $REPLY ]]; then
        echo "已取消"
        exit 0
    fi
fi

# ---- 6. 启动 ----
echo ""
echo "🐳 启动 Docker 服务（首次约 5-10 分钟）..."
echo ""

docker compose up -d --build

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  ✅ 部署完成！${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "访问地址:"
echo "  🌐 前端:    http://localhost"
echo "  📖 API 文档: http://localhost/api/v1/docs"
echo "  📦 MinIO:   http://localhost:9001"
echo ""
echo "管理员账号: admin"
echo "管理员密码: 查看 .env 中的 ADMIN_PASSWORD"
echo ""
echo "常用命令:"
echo "  docker compose logs -f app      # 查看应用日志"
echo "  docker compose ps               # 查看服务状态"
echo "  docker compose down             # 停止（保留数据）"
echo "  docker compose down -v          # 停止并清除数据"
echo ""

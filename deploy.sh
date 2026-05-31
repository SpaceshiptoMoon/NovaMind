#!/bin/bash
# ========================================
# NovaMind 一键部署脚本
# ========================================
# 用法:
#   bash deploy.sh deploy    # 全新部署（默认）
#   bash deploy.sh update    # 重新构建并更新 app 容器
#   bash deploy.sh status    # 显示所有服务状态
#   bash deploy.sh logs      # 跟踪应用日志
#   bash deploy.sh stop      # 停止服务（保留数据）
#   bash deploy.sh clean     # 停止并清除数据卷
#   bash deploy.sh           # 等同于 deploy
#
# 需要: Docker 20.10+, Docker Compose V2+

set -e

# ─── 颜色 ──────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ─── ASCII Banner ──────────────────────────────────────
print_banner() {
    echo ""
    echo -e "${CYAN}  _   _                  _   __  __ _       _"
    echo " | \\ | |                | | |  \\/  (_)     (_)"
    echo " |  \\| | ___ _ __   ___| | | \\  / |_ _ __  _  ___"
    echo " | . \` |/ _ \\ '_ \\ / _ \\ | | |\\/| | | '_ \\| |/ _ \\"
    echo " | |\\  |  __/ | | |  __/ | | |  | | | | | | |  __/"
    echo " |_| \\_|\\___|_| |_|\\___|_| |_|  |_|_|_| |_|_|\\___|"
    echo -e "${NC}"
    echo -e "  ${BOLD}NovaMind 智能知识库部署工具${NC}"
    echo ""
}

# ─── 工具函数 ──────────────────────────────────────────
info()  { echo -e "${GREEN}✓${NC} $1"; }
warn()  { echo -e "${YELLOW}⚠${NC} $1"; }
error() { echo -e "${RED}✗${NC} $1"; }
step()  { echo -e "${CYAN}▸${NC} $1"; }

generate_password() {
    if command -v openssl &>/dev/null; then
        openssl rand -hex "$1"
    else
        cat /dev/urandom | head -c "$(( $1 * 2 ))" | hexdump -e '"%02x"'
    fi
}

# 跨平台文件内容替换 (兼容 macOS sed)
replace_in_file() {
    local file="$1" pattern="$2" replacement="$3"
    if command -v perl &>/dev/null; then
        perl -pi -e "s/\Q$pattern\E/$replacement/g" "$file"
    elif [[ "$(uname)" == "Darwin" ]]; then
        sed -i '' "s/$pattern/$replacement/g" "$file"
    else
        sed -i "s/$pattern/$replacement/g" "$file"
    fi
}

# ─── 前置检查 ──────────────────────────────────────────
check_docker() {
    step "检查 Docker 环境..."

    if ! command -v docker &>/dev/null; then
        error "未找到 Docker，请先安装: https://docs.docker.com/get-docker/"
        exit 1
    fi

    # 检查 Docker daemon 是否运行
    if ! docker info &>/dev/null; then
        error "Docker daemon 未运行，请先启动 Docker"
        exit 1
    fi
    info "Docker $(docker --version | grep -oP '\d+\.\d+\.\d+')"

    if ! docker compose version &>/dev/null; then
        error "未找到 Docker Compose V2，请升级 Docker"
        exit 1
    fi
    info "Docker Compose $(docker compose version --short 2>/dev/null || echo 'V2')"
}

check_ports() {
    local ports=(80 3306 6379 9005 9200)
    local names=("App(80)" "MySQL(3306)" "Redis(6379)" "MinIO(9005)" "ES(9200)")
    local conflicts=0

    step "检查端口占用..."

    for i in "${!ports[@]}"; do
        if command -v ss &>/dev/null; then
            if ss -tlnp 2>/dev/null | grep -q ":${ports[$i]} " ; then
                # 检查是否被本项目容器占用
                if ! docker ps --format "{{.Ports}}" 2>/dev/null | grep -q "${ports[$i]}" ; then
                    warn "${names[$i]} 端口已被占用"
                    conflicts=$((conflicts + 1))
                fi
            fi
        elif command -v netstat &>/dev/null; then
            if netstat -tlnp 2>/dev/null | grep -q ":${ports[$i]} " ; then
                if ! docker ps --format "{{.Ports}}" 2>/dev/null | grep -q "${ports[$i]}" ; then
                    warn "${names[$i]} 端口已被占用"
                    conflicts=$((conflicts + 1))
                fi
            fi
        fi
    done

    if [ "$conflicts" -gt 0 ]; then
        warn "检测到 ${conflicts} 个端口冲突，可能导致服务启动失败"
        if [ "$QUICK_MODE" != "true" ]; then
            read -p "  继续部署？[y/N] " -n 1 -r
            echo ""
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                echo "已取消"
                exit 0
            fi
        fi
    else
        info "所有端口可用"
    fi
}

# ─── 配置生成 ──────────────────────────────────────────
generate_env() {
    if [ -f .env ]; then
        info ".env 已存在，跳过"
        return
    fi

    step "创建 .env 配置文件（自动生成随机密码）..."
    cp .env.example .env

    MYSQL_PASS=$(generate_password 16)
    MINIO_USER=$(generate_password 8)
    MINIO_PASS=$(generate_password 16)
    SECRET_KEY=$(generate_password 32)
    ENCRYPTION_KEY=$(generate_password 16)
    ADMIN_PASS="Admin@$(generate_password 4)"

    replace_in_file .env "your-mysql-password" "$MYSQL_PASS"
    replace_in_file .env "your-minio-access-key" "$MINIO_USER"
    replace_in_file .env "your-minio-secret-key" "$MINIO_PASS"
    replace_in_file .env "your-jwt-secret-key" "$SECRET_KEY"
    replace_in_file .env "your-aes256-encryption-key" "$ENCRYPTION_KEY"
    replace_in_file .env "your-admin-password" "$ADMIN_PASS"

    info ".env 已创建"
    echo ""
    warn "管理员密码: $ADMIN_PASS"
    warn "请妥善保管 .env 文件"
}

generate_configs() {
    # docker.yaml
    if [ ! -f docker/configs/docker.yaml ]; then
        step "创建 Docker 配置..."
        cp docker/configs/docker.example docker/configs/docker.yaml
        info "docker.yaml 已创建"
    else
        info "docker.yaml 已存在，跳过"
    fi

    # default.yaml
    if [ ! -f backend/src/setting/yaml_config/yaml/default.yaml ]; then
        step "创建后端基础配置..."
        cp backend/src/setting/yaml_config/yaml/default.example backend/src/setting/yaml_config/yaml/default.yaml
        info "default.yaml 已创建"
    else
        info "default.yaml 已存在，跳过"
    fi

    warn "Docker 部署时敏感配置由 docker.yaml (.env) 覆盖，无需手动编辑"
}

# ─── 健康检查 ──────────────────────────────────────────
wait_healthy() {
    local timeout="${1:-180}"
    local interval=5
    local elapsed=0

    step "等待服务就绪（最长 ${timeout}s）..."

    while [ $elapsed -lt $timeout ]; do
        local all_healthy=true

        # 检查所有容器是否 healthy
        local unhealthy
        unhealthy=$(docker compose ps --format "{{.Health}}" 2>/dev/null | grep -v -E "^(healthy|)$" || true)

        if [ -z "$unhealthy" ]; then
            local running
            running=$(docker compose ps -q 2>/dev/null | wc -l)
            if [ "$running" -ge 5 ]; then
                info "所有服务已启动"
                return 0
            fi
        fi

        sleep $interval
        elapsed=$((elapsed + interval))
        echo -ne "  ⏳ 已等待 ${elapsed}s / ${timeout}s\r"
    done

    echo ""
    warn "等待超时，部分服务可能未就绪"
    return 1
}

check_app_health() {
    step "检查应用健康状态..."
    local max_retries=10
    local retry=0

    while [ $retry -lt $max_retries ]; do
        if curl -sf http://localhost/health &>/dev/null; then
            info "后端健康检查通过"
            return 0
        fi
        retry=$((retry + 1))
        sleep 3
    done

    warn "后端健康检查未通过（服务可能仍在初始化）"
    return 1
}

# ─── 状态打印 ──────────────────────────────────────────
print_status_table() {
    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}  ✅ 部署完成！${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo -e "${BOLD}服务状态:${NC}"
    docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || docker compose ps
    echo ""
    echo -e "${BOLD}访问地址:${NC}"
    echo "  🌐 前端:      http://localhost"
    echo "  📖 API 文档:  http://localhost/api/v1/docs"
    echo "  📦 MinIO:     http://localhost:9001"
    echo ""
    echo -e "${BOLD}管理员账号:${NC}"
    echo "  用户名: admin"
    if [ -f .env ]; then
        echo "  密码:   查看 .env 中的 ADMIN_PASSWORD"
    fi
    echo ""
    echo -e "${BOLD}常用命令:${NC}"
    echo "  bash deploy.sh status    # 查看服务状态"
    echo "  bash deploy.sh logs      # 查看应用日志"
    echo "  bash deploy.sh update    # 更新应用"
    echo "  bash deploy.sh stop      # 停止服务"
    echo "  bash deploy.sh clean     # 停止并清除数据"
    echo ""
}

# ─── 子命令: deploy ────────────────────────────────────
cmd_deploy() {
    print_banner
    QUICK_MODE="${QUICK_MODE:-false}"

    echo -e "${BOLD}📋 部署前检查${NC}"
    echo ""

    check_docker
    check_ports
    echo ""

    echo -e "${BOLD}📝 生成配置${NC}"
    echo ""
    generate_env
    generate_configs
    echo ""

    # 确认
    if [ "$QUICK_MODE" != "true" ]; then
        echo -e "${BOLD}准备启动以下服务:${NC}"
        echo "  • app           (前端 + 后端 + Nginx) → http://localhost"
        echo "  • mysql         (MySQL 8.0)            → localhost:3306"
        echo "  • redis         (Redis 7)              → localhost:6379"
        echo "  • minio         (MinIO)                → localhost:9005 / :9001"
        echo "  • elasticsearch (ES 8.15)              → localhost:9200"
        echo ""
        read -p "确认部署？[Y/n] " -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Yy]$ ]] && [[ -n $REPLY ]]; then
            echo "已取消"
            exit 0
        fi
    fi

    # 构建 & 启动
    echo ""
    echo -e "${BOLD}🐳 启动 Docker 服务${NC}（首次约 5-10 分钟）..."
    echo ""

    docker compose up -d --build

    echo ""
    wait_healthy 180 || true
    check_app_health || true
    print_status_table
}

# ─── 子命令: update ────────────────────────────────────
cmd_update() {
    print_banner
    echo -e "${BOLD}🔄 更新应用${NC}"
    echo ""

    check_docker

    step "重新构建 app 镜像..."
    docker compose build app

    step "更新 app 容器..."
    docker compose up -d app

    echo ""
    wait_healthy 120 || true
    check_app_health || true

    echo ""
    info "应用更新完成！"
    print_status_table
}

# ─── 子命令: status ────────────────────────────────────
cmd_status() {
    echo ""
    echo -e "${BOLD}📊 NovaMind 服务状态${NC}"
    echo ""

    if ! docker compose ps &>/dev/null; then
        error "无法获取服务状态，请确认 Docker 正在运行"
        exit 1
    fi

    docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || docker compose ps
    echo ""

    # 后端健康检查
    if curl -sf http://localhost/health &>/dev/null; then
        info "后端健康检查: 正常"
    else
        warn "后端健康检查: 无响应（服务可能未启动）"
    fi

    echo ""
}

# ─── 子命令: logs ──────────────────────────────────────
cmd_logs() {
    echo -e "${BOLD}📜 应用日志（Ctrl+C 退出）${NC}"
    echo ""
    docker compose logs -f app
}

# ─── 子命令: stop ──────────────────────────────────────
cmd_stop() {
    print_banner
    echo -e "${BOLD}⏹ 停止服务${NC}"
    echo ""

    docker compose down
    echo ""
    info "所有服务已停止（数据已保留）"
    echo "  使用 bash deploy.sh deploy 重新启动"
    echo ""
}

# ─── 子命令: clean ─────────────────────────────────────
cmd_clean() {
    print_banner
    echo -e "${RED}${BOLD}🗑 清除所有服务和数据${NC}"
    echo ""
    warn "此操作将删除所有数据卷（MySQL、Redis、MinIO、ES），不可恢复！"
    read -p "确认清除？输入 YES 继续: " -r
    echo ""

    if [ "$REPLY" != "YES" ]; then
        echo "已取消"
        exit 0
    fi

    docker compose down -v
    echo ""
    info "所有服务和数据已清除"
    echo ""
}

# ─── 帮助信息 ──────────────────────────────────────────
cmd_help() {
    print_banner
    echo -e "${BOLD}用法:${NC}"
    echo "  bash deploy.sh [命令]"
    echo ""
    echo -e "${BOLD}命令:${NC}"
    echo "  deploy    全新部署（默认）"
    echo "  update    重新构建并更新 app 容器"
    echo "  status    显示所有服务状态"
    echo "  logs      跟踪应用日志 (Ctrl+C 退出)"
    echo "  stop      停止服务（保留数据）"
    echo "  clean     停止并清除所有数据卷"
    echo ""
    echo -e "${BOLD}快捷模式:${NC}"
    echo "  bash deploy.sh -q       # 跳过确认直接部署"
    echo "  bash deploy.sh --quick  # 同上"
    echo ""
}

# ─── 主入口 ────────────────────────────────────────────
COMMAND="$1"
shift 2>/dev/null || true

# 处理快捷模式参数
if [ "$COMMAND" = "--quick" ] || [ "$COMMAND" = "-q" ]; then
    QUICK_MODE=true
    COMMAND=""
fi

case "$COMMAND" in
    deploy|"")
        cmd_deploy
        ;;
    update)
        cmd_update
        ;;
    status)
        cmd_status
        ;;
    logs)
        cmd_logs
        ;;
    stop)
        cmd_stop
        ;;
    clean)
        cmd_clean
        ;;
    help|--help|-h)
        cmd_help
        ;;
    *)
        error "未知命令: $COMMAND"
        echo ""
        cmd_help
        exit 1
        ;;
esac

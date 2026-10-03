# ========================================
# NovaMind - Unified Dockerfile
# Frontend (Vue 3) + Backend (FastAPI) + Nginx
# Multi-stage: build frontend + compile python deps in builder,
# runtime image carries no compilers and runs as non-root.
# ========================================

# ---- Stage 1: build frontend ----
FROM node:22.23.1-alpine AS frontend-build

WORKDIR /build

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build-only

# ---- Stage 2: build backend deps (has gcc, dropped at runtime) ----
FROM python:3.12.13-slim AS backend-build

# gcc + tzdata only for compiling C extensions during dependency install;
# neither leaves this stage.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# uv 安装走 uv.lock 冻结复现，与 CI（uv sync --frozen）同源同版本策略：镜像钉在
# 生成 lock 的 uv 版本，--frozen 才能精确复现。此前 builder 用 unlocked
# pip install .，镜像依赖可与 CI 实测版本漂移。
COPY --from=ghcr.io/astral-sh/uv:0.9.11 /uv /uvx /usr/local/bin/

WORKDIR /app

# UV_PYTHON 钉住系统解释器（避免 uv 联网下载托管 Python）；编译字节码与拷贝
# 模式分别为容器启动提速和跨层拷贝保险。
ENV UV_PYTHON=/usr/local/bin/python3.12 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# --no-install-project：只装 lock 中的第三方依赖——novamind 本体运行期从
# /app/src 加载（main.py 注入 sys.path），不装进 venv，源码也不必进 builder。
# deepdoc-vision extras：仅多装 onnx（量化用，其余与 core 重复）——deploy 期下载
# 公式模型时容器内需具备 onnx 包做 INT8 动态量化（112MB→30MB），缺则 fp32 入库。
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN uv sync --frozen --no-install-project --extra deepdoc-vision --no-cache

# ---- Stage 3: runtime (no gcc, non-root) ----
FROM python:3.12.13-slim

# 时区可构建期覆盖：docker build --build-arg TZ=... 或 compose build args。
# 默认 Asia/Shanghai 保持既有行为；海外部署建议改回 UTC。
ARG TZ=Asia/Shanghai
ENV TZ=${TZ}
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Runtime packages only: no build toolchain. curl is for HEALTHCHECK.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    nginx \
    supervisor \
    curl \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for all processes.
RUN groupadd --system --gid 1001 appuser \
    && useradd --system --uid 1001 --gid appuser --home-dir /app --shell /usr/sbin/nologin appuser

# 依赖以独立 venv 整体带入（uv 官方多阶段模式）：两个 stage 同为
# python:3.12.13-slim，venv 内解释器符号链接在本镜像同样有效。novamind 本体
# 仍从 /app/src 加载，不进 venv；supervisord 与 compose run 的 `python` 均经
# PATH 解析到 venv 解释器。
COPY --from=backend-build /app/.venv /app/.venv
ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Backend source (loaded from disk via main.py sys.path insertion) + manifest.
COPY backend/pyproject.toml backend/README.md ./
COPY backend/src/ ./src/
COPY backend/main.py ./
# 运维脚本（模型下载等）：deploy 期 faster-whisper 模型预装与 README 手动补救
# 命令都在容器内执行 scripts/download_faster_whisper_model.py，缺了会以
# "can't open file" 失败且 WARN-不阻断，模型静默缺失。
COPY backend/scripts/ ./scripts/

# Frontend static assets served by Nginx.
COPY --from=frontend-build /build/dist /usr/share/nginx/html

# Non-root Nginx: complete main config (no `user` directive, pid + temp under /tmp).
COPY docker/nginx.conf /etc/nginx/nginx.conf

# Supervisord: complete main config, non-root (no unix_http_server socket,
# pidfile under /tmp so no write to the root-owned /run tmpfs).
COPY docker/supervisord.conf /etc/supervisor/supervisord.conf

# Writable dirs owned by appuser (nginx temp + supervisor logs + pid).
RUN mkdir -p /var/log/supervisor /var/log/nginx /var/lib/nginx /var/cache/nginx /tmp/nginx \
    && chown -R appuser:appuser /app /usr/share/nginx/html \
        /var/log/supervisor /var/log/nginx /var/lib/nginx /var/cache/nginx /tmp/nginx \
    && chmod -R a+rwX /tmp/nginx

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -sf http://localhost:8080/health || exit 1

USER appuser

CMD ["supervisord", "-n", "-c", "/etc/supervisor/supervisord.conf"]
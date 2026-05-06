# ========================================
# 智能知识库系统 - 一体化 Dockerfile
# 前端 (Vue 3) + 后端 (FastAPI) + Nginx
# ========================================

# ---- Stage 1: 构建前端 ----
FROM node:22-alpine AS frontend-build

WORKDIR /build

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ .
RUN npm run build-only

# ---- Stage 2: 运行时 (前端 + 后端 + Nginx) ----
FROM python:3.12-slim

ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    nginx \
    supervisor \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 安装 Python 依赖
COPY backend/pyproject.toml backend/README.md ./
RUN mkdir -p src && touch src/__init__.py && \
    pip install --no-cache-dir . && \
    rm -rf src/__init__.py

# 复制后端源码
COPY backend/src/ ./src/
COPY backend/main.py ./

# 复制前端构建产物到 Nginx 目录
COPY --from=frontend-build /build/dist /usr/share/nginx/html

# 复制 Nginx 配置
COPY docker/nginx.conf /etc/nginx/sites-available/default
RUN rm -f /etc/nginx/sites-enabled/default && \
    ln -s /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default && \
    rm -f /etc/nginx/conf.d/default.conf

# 复制 Supervisord 配置
COPY docker/supervisord.conf /etc/supervisor/conf.d/app.conf

EXPOSE 80

CMD ["supervisord", "-c", "/etc/supervisor/supervisord.conf"]

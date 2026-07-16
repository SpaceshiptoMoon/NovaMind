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

# gcc + tzdata only for compiling C extensions during pip install;
# neither leaves this stage.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy source so setuptools can resolve packages from src/ (pip install .).
# main.py loads novamind from /app/src at runtime, so pip install . here is
# mainly to compile/install third-party dependencies into site-packages.
COPY backend/pyproject.toml backend/README.md ./
COPY backend/src/ ./src/
COPY backend/main.py ./
RUN pip install --no-cache-dir .

# ---- Stage 3: runtime (no gcc, non-root) ----
FROM python:3.12.13-slim

ENV TZ=Asia/Shanghai
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

# Bring compiled third-party deps from the builder. novamind itself is loaded
# from /app/src at runtime, so we only need the installed site-packages.
COPY --from=backend-build /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages

WORKDIR /app

# Backend source (loaded from disk via main.py sys.path insertion) + manifest.
COPY backend/pyproject.toml backend/README.md ./
COPY backend/src/ ./src/
COPY backend/main.py ./

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
# ========================================
# NovaMind - Unified Dockerfile
# Frontend (Vue 3) + Backend (FastAPI) + Nginx
# ========================================

# ---- Stage 1: build frontend ----
FROM node:22.23.1-alpine AS frontend-build

WORKDIR /build

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build-only

# ---- Stage 2: runtime ----
FROM python:3.12.13-slim

ENV TZ=Asia/Shanghai
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    gcc \
    nginx \
    supervisor \
    curl \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy backend source before pip install so setuptools can resolve packages from src/
COPY backend/pyproject.toml backend/README.md ./
COPY backend/src/ ./src/
COPY backend/main.py ./
RUN pip install --no-cache-dir .

COPY --from=frontend-build /build/dist /usr/share/nginx/html

COPY docker/nginx.conf /etc/nginx/sites-available/default
RUN rm -f /etc/nginx/sites-enabled/default \
    && ln -s /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default \
    && rm -f /etc/nginx/conf.d/default.conf

COPY docker/supervisord.conf /etc/supervisor/conf.d/app.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -sf http://localhost/health || exit 1

CMD ["supervisord", "-c", "/etc/supervisor/supervisord.conf"]

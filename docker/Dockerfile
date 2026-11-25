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

# 依赖层只以 pyproject.toml + uv.lock 为输入：--no-install-project 不构建 novamind
# 本体，README.md 不参与依赖解析，不要并进这一层的 COPY——否则纯文档提交也会使
# 依赖层失效、全量重装。源码在 runtime stage 才拷入，改代码不影响这里。
# --no-install-project：只装 lock 中的第三方依赖——novamind 本体运行期从
# /app/src 加载（main.py 注入 sys.path），不装进 venv，源码也不必进 builder。
# deepdoc-vision extras：仅多装 onnx（量化用，其余与 core 重复）——deploy 期下载
# 公式模型时容器内需具备 onnx 包做 INT8 动态量化（112MB→30MB），缺则 fp32 入库。
# cache mount：uv 下载缓存留在宿主机构建缓存里（不进镜像层），依赖层重跑时命中
# 已缓存的 wheel，只下缺失或变更的包。
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --extra deepdoc-vision

# GPU 部署可选层（构建参数 ASR_GPU=true，compose 经 build.args 传入）：本地 ASR
# （CTranslate2）的 CUDA 实现运行时 dlopen cuBLAS，默认镜像不含。只在开启时追加
# asr-gpu extra（pyproject.toml）。独立成层：默认构建（false）此层为空，不触碰上面
# 的依赖层。显卡驱动库 libcuda.so.1 不装——由宿主机驱动经 NVIDIA Container Toolkit
# 在容器启动时注入。
ARG ASR_GPU=false
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$ASR_GPU" = "true" ]; then \
      uv sync --frozen --no-install-project --extra deepdoc-vision --extra asr-gpu; \
    fi

# GPU 部署可选层（构建参数 VISION_GPU=true，deploy 脚本宿主检测注入——构建容器内
# 见不到 nvidia-smi，检测必须在宿主侧）：DeepDoc 视觉组件（OCR/layout/TSR/公式）
# 的 ONNX CUDA 推理需要 onnxruntime-gpu + CUDA 运行库。torch 一并安装——它既是
# 全系统唯一设备探针（runtime_settings.resolve_device_policy）的判定依据，其
# wheel 依赖又顺带拉齐 nvidia 运行库。CUDA 大版本必须三方对齐（宿主驱动 +
# torch + ORT-gpu；二进制 soname 实测 2026-11-26）：
# - 宿主驱动 566.26 = CUDA 12.7 → cu13 栈（torch 2.11+/ORT-gpu 1.27）在本机
#   永远起不来（"NVIDIA driver too old (12070)" 实测）；
# - onnxruntime-gpu 1.27 = 仅 cu13 构建 → 弃用；
# - onnxruntime-gpu 1.26 = cu12 构建，且 [cuda,cudnn] extras 可 pip 直装
#   nvidia-cuda-runtime/nvrtc/cufft/curand/cudnn 的 cu12 轮子 → 采用；
# - torch 2.10.x = cu12 栈（cublas 12.8 + cudnn-cu12 9.10）→ 采用。
# CUDA 12.x 系列跨小版本兼容（12.8 库跑 12.7 驱动，ASR cu12 先例实测）。
# onnxruntime（CPU）与 onnxruntime-gpu 是同 import 名的互斥发行版无法共存，
# 此处原子置换；独立成层不动上面的 --frozen 主依赖层。默认构建（false）此层
# 为空、镜像零增量。UV_HTTP_TIMEOUT=3600：冷缓存首装 torch 系列 wheel 达 GB 级
#（单 wheel 最大 ~900MB），uv 默认 30s 在慢速网络必炸（600s 也兜不住单请求总
# 时长语义）——超时值按最慢预期带宽 × 最大单 wheel 估算。
# 显卡驱动库 libcuda.so.1 不装——由宿主机驱动经 NVIDIA Container Toolkit 注入。
ARG VISION_GPU=false
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$VISION_GPU" = "true" ]; then \
      UV_HTTP_TIMEOUT=3600 uv pip uninstall --python /app/.venv/bin/python onnxruntime \
      && UV_HTTP_TIMEOUT=3600 uv pip install --python /app/.venv/bin/python \
        "torch>=2.10.0,<2.11" \
        "onnxruntime-gpu[cuda,cudnn]==1.26.0"; \
    fi

# ---- Stage 3: runtime (no gcc, non-root) ----
FROM python:3.12.13-slim

# 时区可构建期覆盖：docker build --build-arg TZ=... 或 compose build args。
# 默认 Asia/Shanghai 保持既有行为；海外部署建议改回 UTC。
ARG TZ=Asia/Shanghai
ENV TZ=${TZ}
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Runtime packages only: no build toolchain. curl is for HEALTHCHECK.
# gettext-base provides envsubst for nginx template rendering at startup.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    nginx \
    supervisor \
    curl \
    gettext-base \
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
# 属主在复制时直接设为 appuser（--chown）：若留到后面的 chown -R 统一改，2GB 的
# venv 会被整层再复制一遍（镜像解压体积接近翻倍、构建多花约 45 秒）。
COPY --from=backend-build --chown=appuser:appuser /app/.venv /app/.venv
ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

# ASR_GPU=true 时 cuBLAS 位于 venv 的 site-packages/nvidia 下，不在动态链接器的默认
# 搜索路径（CTranslate2 按名字 libcublas.so.12 dlopen）。把包内 lib 目录登记进链接器
# 配置并刷新缓存：容器内所有进程（含 ASR 推理子进程）都能找到，且不依赖 LD_LIBRARY_PATH。
# 必须登记整个目录而不是只软链 libcublas.so.12——它依赖同目录的 libcublasLt.so.12，
# 经软链打开时后者解析不到，dlopen 照样失败（实测）。
ARG ASR_GPU=false
RUN if [ "$ASR_GPU" = "true" ]; then \
      printf '%s\n' \
        /app/.venv/lib/python3.12/site-packages/nvidia/cublas/lib \
        /app/.venv/lib/python3.12/site-packages/nvidia/cuda_nvrtc/lib \
        > /etc/ld.so.conf.d/asr-gpu.conf \
      && ldconfig; \
    fi

# VISION_GPU=true 时登记 torch / onnxruntime-gpu 依赖链带入的全部 nvidia 运行库
# 目录（cudnn/cublas/cufft 等）：ORT CUDA EP 按名字 dlopen 时能找到。整树扫描
# */lib 与 asr-gpu.conf 并存（重复目录对 ldconfig 无害）。
ARG VISION_GPU=false
RUN if [ "$VISION_GPU" = "true" ]; then \
      find /app/.venv/lib/python3.12/site-packages/nvidia -maxdepth 2 -type d -name lib \
        | sort > /etc/ld.so.conf.d/vision-gpu.conf \
      && ldconfig; \
    fi

# 安装期 flavor 标记（true/false，settings 侧归一为 gpu/cpu）：运行时唯一探针
# 首次判定时与之对账——一致记 info，不一致仅告警、行为始终以运行时判定为准
# （GPU flavor 镜像在无卡机器自动落 CPU；CPU flavor 镜像在有卡机器维持 CPU）。
ENV DEVICE_FLAVOR=${VISION_GPU}

# PPT×VLM 转写线的视觉化依赖（构建参数 OFFICE_CONVERT=true，compose override
# 或 deploy 环境注入）：LibreOffice Impress headless 把 pptx 转 PDF 再走统一页
# 渲染。fonts-noto-cjk 必装——缺中文字体时中文幻灯片转出乱码方块。约 +600MB；
# 默认不装、镜像零增量。未装时 PPT×vlm 在解析期显式终态失败并给安装指引
# （能力缺失方向安全，与 mineru cli_path 空 = 未安装 同语义）。
ARG OFFICE_CONVERT=false
RUN if [ "$OFFICE_CONVERT" = "true" ]; then \
      apt-get update \
      && apt-get install -y --no-install-recommends \
        libreoffice-impress \
        fonts-noto-cjk \
      && rm -rf /var/lib/apt/lists/*; \
    fi

WORKDIR /app

# Backend source (loaded from disk via main.py sys.path insertion) + manifest.
COPY --chown=appuser:appuser backend/pyproject.toml backend/README.md ./
COPY --chown=appuser:appuser backend/src/ ./src/
COPY --chown=appuser:appuser backend/main.py ./
# 解析管道独立 worker 进程（supervisord.conf 的 [program:parse_worker] 入口）：
# backend=stream 时必需；默认 backend=arq 时它自检测后正常退出。漏拷会以
# "can't open file" 启动失败并刷错误日志。
COPY --chown=appuser:appuser backend/parse_worker.py ./
# 运维脚本（模型下载等）：deploy 期 faster-whisper 模型预装与 README 手动补救
# 命令都在容器内执行 scripts/download_faster_whisper_model.py，缺了会以
# "can't open file" 失败且 WARN-不阻断，模型静默缺失。
COPY --chown=appuser:appuser backend/scripts/ ./scripts/

# Frontend static assets served by Nginx.
COPY --from=frontend-build --chown=appuser:appuser /build/dist /usr/share/nginx/html

# Non-root Nginx: main config is a template rendered at startup by
# render-nginx-conf.sh (TLS 块与 client_max_body_size 由环境变量注入；
# 渲染产物在 /tmp/nginx/nginx.conf，pid + temp 也在 /tmp)。
COPY docker/nginx.template.conf /etc/nginx/nginx.template.conf
COPY docker/render-nginx-conf.sh /usr/local/bin/render-nginx-conf.sh
RUN chmod +x /usr/local/bin/render-nginx-conf.sh

# TLS 证书挂载点（默认为空目录；启用 TLS 时 compose 挂载证书并注入路径 env）。
RUN mkdir -p /etc/nginx/tls

# Supervisord: complete main config, non-root (no unix_http_server socket,
# pidfile under /tmp so no write to the root-owned /run tmpfs).
COPY docker/supervisord.conf /etc/supervisor/supervisord.conf

# Writable dirs owned by appuser (nginx temp + supervisor logs + pid).
# /app 下各目录与文件的属主已由上面的 COPY --chown 设定，这里不再对 /app 做 chown -R；
# /app 本身由 WORKDIR 以 root 创建，只改这两个目录自身（不递归，不触发整层复制）。
# /app/.cache 必须预建并归属 appuser：镜像本身无此目录时，运行时 Docker 为挂载
# deepdoc/faster-whisper 两个 bind 卷会以 root 自动补建父目录，appuser 对 root
# 属主的 .cache 无写权限——DeepDoc full 模式 vendor bootstrap 要在 .cache/rag 下
# 拷模型，直接 PermissionError（实测 2026-11-25）。
RUN mkdir -p /var/log/supervisor /var/log/nginx /var/lib/nginx /var/cache/nginx /tmp/nginx /app/.cache \
    && chown appuser:appuser /app /usr/share/nginx/html /app/.cache \
    && chown -R appuser:appuser \
        /var/log/supervisor /var/log/nginx /var/lib/nginx /var/cache/nginx /tmp/nginx \
    && chmod -R a+rwX /tmp/nginx

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -sf http://localhost:8080/health || exit 1

USER appuser

CMD ["supervisord", "-n", "-c", "/etc/supervisor/supervisord.conf"]
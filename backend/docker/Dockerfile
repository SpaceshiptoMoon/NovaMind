# 智能知识库系统 - 开发环境 Dockerfile
FROM python:3.12-slim

# 设置时区
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 安装系统依赖（PDF 解析等需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先复制依赖文件，利用 Docker 缓存层加速构建
COPY pyproject.toml README.md ./

# 安装 Python 依赖
RUN pip install --no-cache-dir .

# 复制项目源码
COPY src/ ./src/
COPY main.py ./

# 暴露端口
EXPOSE 8100


# 启动命令
CMD ["python", "main.py", "--config", "development", "--host", "0.0.0.0", "--port", "8100"]

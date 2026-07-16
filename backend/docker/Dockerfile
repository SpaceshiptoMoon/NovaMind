# NovaMind backend - development Dockerfile
FROM python:3.12.13-slim

ENV TZ=Asia/Shanghai
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    gcc \
    curl \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY main.py ./
RUN pip install --no-cache-dir .

EXPOSE 8100

CMD ["python", "main.py", "--config", "development", "--host", "0.0.0.0", "--port", "8100"]

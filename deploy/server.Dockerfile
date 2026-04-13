# ===== Stage 1: Builder =====
FROM python:3.11-slim AS builder

# 使用与 runtime 相同的路径，避免 venv shebang 路径不一致
WORKDIR /app

# 安装编译依赖
RUN apt-get update && apt-get install -y --no-install-recommends gcc git && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖到 .venv
COPY server/requirements.txt .
RUN python -m venv .venv && \
    . .venv/bin/activate && \
    pip install --no-cache-dir git+https://github.com/xiaolutang/log-service.git@v0.1.0#subdirectory=sdks/python && \
    pip install --no-cache-dir -r requirements.txt

# ===== Stage 2: Runtime =====
FROM python:3.11-slim

WORKDIR /app

# 创建非 root 用户
RUN useradd -r -s /bin/false appuser && \
    mkdir -p /data && chown appuser:appuser /data

# 从 builder 复制虚拟环境（路径一致：/app/.venv）
COPY --from=builder /app/.venv .venv

# 复制应用代码
COPY server/app ./app

# 设置文件所有权
RUN chown -R appuser:appuser /app

# 环境变量
ENV PATH="/app/.venv/bin:$PATH"
ENV LOG_SERVICE_URL=http://log-service:8001
ENV LOG_LEVEL=INFO

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]

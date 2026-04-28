# ===== Stage 1: Builder =====
FROM python:3.11-slim AS builder

# 使用与 runtime 相同的路径，避免 venv shebang 路径不一致
WORKDIR /app

# 安装 git（pip install git+https 需要）
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖到 .venv
COPY agent/requirements.txt .
RUN python -m venv .venv && \
    . .venv/bin/activate && \
    pip install --no-cache-dir --no-deps git+https://github.com/xiaolutang/log-service.git@v0.1.0#subdirectory=sdks/python ; \
    pip install --no-cache-dir -r requirements.txt

# ===== Stage 2: Runtime =====
FROM python:3.11-slim

# 本地构建传 RUN_USER=root（绕过 volume 权限），远端默认 appuser
ARG RUN_USER=appuser

WORKDIR /app

# 始终创建非 root 用户（创建 home 目录用于配置持久化）
RUN useradd -r -m -s /bin/false appuser

# 从 builder 复制虚拟环境（路径一致：/app/.venv）
COPY --from=builder /app/.venv .venv

# 复制应用代码
COPY agent/app ./app
COPY agent/local_server.py ./local_server.py

# 内置知识文件（随分发包）
# knowledge/ 已包含在 agent/app/ 中，无需额外 COPY

# 设置文件所有权（非 root 时）
RUN if [ "$RUN_USER" != "root" ]; then chown -R appuser:appuser /app; fi

# 环境变量
ENV PATH="/app/.venv/bin:$PATH"
ENV LOG_SERVICE_URL=http://log-service:8001
ENV LOG_LEVEL=INFO

USER ${RUN_USER}

CMD ["python", "-m", "app.cli", "run"]

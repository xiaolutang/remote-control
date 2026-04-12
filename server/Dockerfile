FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends gcc git && rm -rf /var/lib/apt/lists/*

# 安装 log-service-sdk（从 GitHub 拉取）+ 其他依赖
COPY requirements.txt .
RUN pip install --no-cache-dir git+https://github.com/xiaolutang/log-service.git@v0.1.0#subdirectory=sdks/python && \
    pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY app ./app

# 环境变量
ENV LOG_SERVICE_URL=http://localhost:8001
ENV LOG_LEVEL=INFO

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]

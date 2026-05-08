"""
Server 基础设施层统一常量。

分散在各模块的重复常量集中定义于此，其他模块统一引用。
"""
import os

# log-service 基地址（单一来源，避免各模块重复读取 LOG_SERVICE_URL 环境变量）
LOG_SERVICE_URL: str = os.environ.get("LOG_SERVICE_URL", "http://localhost:8001")

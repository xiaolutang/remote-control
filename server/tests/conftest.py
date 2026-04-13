"""
pytest 配置
"""
import pytest
import sys
import os

# 添加项目根目录到 path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# JWT_SECRET 必填，测试环境使用固定值
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-pytest")

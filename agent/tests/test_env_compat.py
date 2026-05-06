"""env_compat.ensure_shell_path() 单元测试"""
import os

import pytest

from app.core.env_compat import ensure_shell_path


@pytest.fixture(autouse=True)
def _isolate_path(monkeypatch):
    """每个测试隔离 PATH 环境。"""
    original = os.environ.get("PATH", "")
    yield
    os.environ["PATH"] = original


def test_no_op_when_path_already_full():
    """PATH 已含 homebrew 路径时函数不修改。"""
    full_path = "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    os.environ["PATH"] = full_path
    ensure_shell_path()
    assert os.environ["PATH"] == full_path


def test_no_op_when_local_bin_present():
    """PATH 含 /usr/local/bin 但无 homebrew 也不修改。"""
    path_with_local = "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    os.environ["PATH"] = path_with_local
    ensure_shell_path()
    assert os.environ["PATH"] == path_with_local


def test_expands_minimal_path(monkeypatch):
    """模拟 launchd 最小 PATH 时扩展。"""
    os.environ["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    monkeypatch.delenv("SHELL", raising=False)
    ensure_shell_path()
    new_path = os.environ["PATH"]
    assert "/opt/homebrew/bin" in new_path
    assert "/usr/local/bin" in new_path
    assert "/usr/bin" in new_path


def test_expands_partial_path(monkeypatch):
    """PATH 有系统路径但缺失所有关键路径时触发修复。"""
    os.environ["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin:/extra/path"
    monkeypatch.delenv("SHELL", raising=False)
    ensure_shell_path()
    assert "/opt/homebrew/bin" in os.environ["PATH"]


def test_shell_fallback(monkeypatch):
    """shell 命令失败时使用 fallback 路径。"""
    os.environ["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    monkeypatch.setenv("SHELL", "/nonexistent/shell")
    ensure_shell_path()
    assert "/opt/homebrew/bin" in os.environ["PATH"]
    assert "/usr/local/bin" in os.environ["PATH"]


def test_shell_missing(monkeypatch):
    """$SHELL 环境变量缺失时 fallback。"""
    os.environ["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    monkeypatch.delenv("SHELL", raising=False)
    ensure_shell_path()
    assert "/opt/homebrew/bin" in os.environ["PATH"]


def test_shell_empty_path(monkeypatch, tmp_path):
    """shell 返回空 PATH 时 fallback。"""
    os.environ["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    fake_shell = tmp_path / "fake_shell"
    fake_shell.write_text("#!/bin/sh\necho ''\n")
    fake_shell.chmod(0o755)
    monkeypatch.setenv("SHELL", str(fake_shell))
    ensure_shell_path()
    assert "/opt/homebrew/bin" in os.environ["PATH"]


def test_idempotent(monkeypatch):
    """重复调用幂等。"""
    os.environ["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    monkeypatch.delenv("SHELL", raising=False)
    ensure_shell_path()
    first = os.environ["PATH"]
    ensure_shell_path()
    assert os.environ["PATH"] == first

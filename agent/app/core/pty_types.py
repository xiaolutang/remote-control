"""
PTY 相关类型和辅助函数。
"""
import fcntl
import os
from dataclasses import dataclass
from typing import Optional


def _create_exec_pipe():
    """创建 exec 同步管道，write end 设为 CLOEXEC。"""
    try:
        r, w = os.pipe2(os.O_CLOEXEC)
    except AttributeError:
        r, w = os.pipe()
        flags = fcntl.fcntl(w, fcntl.F_GETFD)
        fcntl.fcntl(w, fcntl.F_SETFD, flags | fcntl.FD_CLOEXEC)
    return r, w


@dataclass
class PTYConfig:
    """PTY 配置"""
    rows: int = 24
    cols: int = 80
    env: Optional[dict] = None
    cwd: Optional[str] = None

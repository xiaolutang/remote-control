"""
Agent 协议类型与常量定义。
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TerminalSpec:
    """终端运行参数。"""
    terminal_id: str
    command: str
    args: list[str] = field(default_factory=list)
    cwd: Optional[str] = None
    env: dict = field(default_factory=dict)
    title: str = ""
    rows: int = 24
    cols: int = 80


@dataclass
class TerminalSnapshotState:
    """单个 terminal 的可恢复 snapshot 状态。"""

    terminal_id: str
    rows: int
    cols: int
    active_buffer: str = "main"
    payload: bytearray = field(default_factory=bytearray)


# 不可恢复的 WebSocket close code
NON_RECOVERABLE_CODES = {4001, 4004, 4009}

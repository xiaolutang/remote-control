"""
PTY (伪终端) 包装器
"""
import asyncio
import logging
import os
import pty
import select
import signal
import struct
import sys
import fcntl
import termios
import time
from typing import Optional, Callable

from app.core.pty_process import cleanup_wrapper, configure_child_process, wait_for_termination
from app.core.pty_types import PTYConfig, _create_exec_pipe

logger = logging.getLogger(__name__)


class PTYWrapper:
    """PTY 包装器，用于创建和管理伪终端"""

    WRITE_RETRY_TIMEOUT = 1.0
    WRITE_WAIT_INTERVAL = 0.05

    def __init__(self, command: str, args: Optional[list] = None, config: Optional[PTYConfig] = None):
        """
        初始化 PTY 包装器

        Args:
            command: 要执行的命令
            args: 命令参数
            config: PTY 配置
        """
        self.command = command
        self.args = args or []
        self.config = config or PTYConfig()

        self.master_fd: Optional[int] = None
        self.slave_fd: Optional[int] = None
        self.pid: Optional[int] = None
        self._running = False
        self._output_callback: Optional[Callable[[bytes], None]] = None
        self._exec_errno: Optional[int] = None

        self._original_sigwinch_handler = None
        self.signal_module = signal

    def set_output_callback(self, callback: Callable[[bytes], None]):
        """设置输出回调函数"""
        self._output_callback = callback

    @property
    def start_error(self) -> Optional[str]:
        """最近一次 start() 失败的错误描述，成功时为 None"""
        if self._exec_errno is None:
            return None
        return os.strerror(self._exec_errno)

    def start(self) -> bool:
        """
        启动 PTY 进程

        使用 pipe + CLOEXEC 同步 fork-exec：
        - exec 成功 → write_end 被 CLOEXEC 自动关闭 → 父进程 read 返回 EOF
        - exec 失败 → 子进程写 errno 到管道 → 父进程 read 得到 errno

        Returns:
            是否启动成功
        """
        if self._running:
            return False

        self._exec_errno = None

        # 创建 exec 同步管道（CLOEXEC 模式）
        exec_pipe_r, exec_pipe_w = _create_exec_pipe()

        try:
            # 创建伪终端
            self.master_fd, self.slave_fd = pty.openpty()
            # 设置终端大小
            self._set_window_size(self.config.rows, self.config.cols)
        except Exception:
            os.close(exec_pipe_r)
            os.close(exec_pipe_w)
            raise

        # fork 子进程
        self.pid = os.fork()

        if self.pid == 0:
            # 子进程
            os.close(exec_pipe_r)
            self._child_process(exec_pipe_w)
            return True  # 不会执行到这里

        elif self.pid > 0:
            # 父进程
            os.close(exec_pipe_w)
            try:
                # 用 select 加超时，防止子进程卡住导致父进程永久阻塞
                ready, _, _ = select.select([exec_pipe_r], [], [], 5.0)
                if ready:
                    err_data = os.read(exec_pipe_r, 4)
                    if err_data:
                        # 子进程 exec 失败，读取 errno
                        self._exec_errno = struct.unpack("i", err_data)[0]
                        # 回收子进程
                        os.waitpid(self.pid, 0)
                        self._cleanup()
                        return False
                    # EOF (b"") → exec 成功
                else:
                    # 超时：无法确定 exec 是否成功，视为失败
                    os.waitpid(self.pid, 0)
                    self._cleanup()
                    return False
            except OSError:
                # 管道通信异常，回退到检查子进程状态
                try:
                    pid, _ = os.waitpid(self.pid, os.WNOHANG)
                    if pid != 0:
                        self._cleanup()
                        return False
                except ChildProcessError:
                    self._cleanup()
                    return False
            finally:
                try:
                    os.close(exec_pipe_r)
                except OSError:
                    pass

            self._running = True
            logger.info("PTY started: pid=%d", self.pid)
            self._original_sigwinch_handler = signal.signal(signal.SIGWINCH, self._handle_sigwinch)
            # 设置非阻塞模式
            flags = fcntl.fcntl(self.master_fd, fcntl.F_GETFL)
            fcntl.fcntl(self.master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            return True
        else:
            # fork 失败
            os.close(exec_pipe_r)
            os.close(exec_pipe_w)
            self._cleanup()
            return False

    def _child_process(self, exec_pipe_w: int):
        """子进程逻辑"""
        configure_child_process(self, exec_pipe_w)

    def _handle_sigwinch(self, signum, frame):
        """处理终端窗口大小变化"""
        if not self._running:
            return

        try:
            # 获取当前终端大小
            rows, cols = self._get_terminal_size()
            self._set_window_size(rows, cols)
        except Exception:
            pass

    def _get_terminal_size(self) -> tuple[int, int]:
        """获取当前终端大小"""
        try:
            result = fcntl.ioctl(0, termios.TIOCGWINSZ, b"\x00" * 8)
            rows, cols, _, _ = struct.unpack("hhhh", result)
            return rows, cols
        except Exception:
            return self.config.rows, self.config.cols

    def _set_window_size(self, rows: int, cols: int):
        """设置终端窗口大小"""
        if self.master_fd is None:
            return

        try:
            # 设置窗口大小
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
        except Exception:
            pass

    def resize(self, rows: int, cols: int):
        """
        调整终端窗口大小

        Args:
            rows: 行数
            cols: 列数
        """
        self.config.rows = rows
        self.config.cols = cols
        self._set_window_size(rows, cols)

    def write(self, data: bytes) -> bool:
        """
        写入数据到 PTY

        循环写入保证完整性：os.write 可能返回小于 len(data) 的值，
        需要继续写入剩余部分直到全部写完或发生错误。

        Args:
            data: 要写入的数据

        Returns:
            是否写入成功
        """
        if not self._running or self.master_fd is None:
            return False

        try:
            written = 0
            total = len(data)
            deadline = time.monotonic() + self.WRITE_RETRY_TIMEOUT
            while written < total:
                try:
                    n = os.write(self.master_fd, data[written:])
                    if n == 0:
                        # os.write 返回 0 表示无法写入（不应发生，但防御性处理）
                        return False
                    written += n
                    continue
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        return False
                    _, writable, _ = select.select(
                        [],
                        [self.master_fd],
                        [],
                        self.WRITE_WAIT_INTERVAL,
                    )
                    if not writable:
                        continue
                except InterruptedError:
                    continue
            return True
        except Exception:
            return False

    async def read(self) -> Optional[bytes]:
        """
        异步读取 PTY 输出

        Returns:
            读取到的数据，如果连接已关闭则返回 None
        """
        if not self._running or self.master_fd is None:
            return None

        try:
            # 使用 asyncio 读取
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(None, self._sync_read)
            return data
        except Exception:
            return None

    def _sync_read(self) -> Optional[bytes]:
        """同步读取"""
        try:
            data = os.read(self.master_fd, 65536)
            if data == b"":
                self._running = False
                return None
            return data
        except BlockingIOError:
            return None
        except Exception:
            return None

    def is_running(self) -> bool:
        """检查 PTY 是否正在运行"""
        if not self._running or self.pid is None:
            return False

        try:
            # 检查进程是否存活
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            return pid == 0
        except ChildProcessError:
            return False

    GRACEFUL_TIMEOUT = 3  # SIGTERM 后等待进程退出的超时时间
    POLL_INTERVAL = 0.05  # 进程状态轮询间隔（50ms）
    CLEANUP_GRACE_PERIOD = 0.01  # 清理前等待异步操作检测停止信号的缓冲时间（10ms）

    def stop(self):
        """停止 PTY 进程及其整个进程组

        流程：
        1. 发送 SIGTERM 到整个进程组
        2. 等待进程退出（最多 GRACEFUL_TIMEOUT 秒）
        3. 超时后发送 SIGKILL 强制终止
        4. 确保进程被 waitpid 回收
        """
        if not self._running:
            return

        self._running = False

        if not self.pid:
            self._cleanup()
            return

        try:
            # 步骤 1：发送 SIGTERM 到整个进程组
            try:
                os.killpg(-self.pid, signal.SIGTERM)
            except ProcessLookupError:
                # 进程组不存在，进程可能已退出
                self._cleanup()
                return

            # 步骤 2：等待进程退出（带超时）
            terminated = self._wait_for_termination(self.pid, self.GRACEFUL_TIMEOUT)

            if not terminated:
                # 步骤 3：超时后发送 SIGKILL 强制终止
                print(f"Warning: PTY process {self.pid} did not exit after SIGTERM, sending SIGKILL", file=sys.stderr)
                logger.warning("PTY process did not exit after SIGTERM: pid=%d", self.pid)
                try:
                    os.killpg(-self.pid, signal.SIGKILL)
                    self._wait_for_termination(self.pid, 1.0)  # 最多等待 1 秒
                except ProcessLookupError:
                    pass
                except ChildProcessError:
                    pass

        except ChildProcessError:
            # 子进程已经结束
            pass
        except OSError as e:
            print(f"Warning: OSError while stopping PTY: {e}", file=sys.stderr)
            logger.error("OSError while stopping PTY: pid=%d error=%s", self.pid, e)

        logger.info("PTY stopped: pid=%d", self.pid)
        self._cleanup()

    def _wait_for_termination(self, pid: int, timeout: float) -> bool:
        """等待进程终止。"""
        return wait_for_termination(pid, timeout, self.POLL_INTERVAL)

    def _cleanup(self):
        """清理资源。"""
        cleanup_wrapper(self)

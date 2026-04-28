"""
PTY 进程组管理辅助函数。
"""
import os
import struct
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.pty_wrapper import PTYWrapper


def configure_child_process(wrapper: "PTYWrapper", exec_pipe_w: int) -> None:
    """配置 PTY 子进程环境并 exec 目标命令。"""
    os.setsid()
    os.dup2(wrapper.slave_fd, 0)
    os.dup2(wrapper.slave_fd, 1)
    os.dup2(wrapper.slave_fd, 2)
    os.close(wrapper.master_fd)

    env = os.environ.copy()
    if wrapper.config.env:
        env.update(wrapper.config.env)

    env["TERM"] = env.get("TERM", "xterm-256color")
    env["LANG"] = env.get("LANG", "C.UTF-8")
    env["LC_ALL"] = env.get("LC_ALL", env["LANG"])

    if wrapper.config.cwd:
        try:
            os.chdir(os.path.expanduser(wrapper.config.cwd))
        except OSError:
            pass

    try:
        os.execvpe(wrapper.command, [wrapper.command] + wrapper.args, env)
    except OSError as exc:
        try:
            os.write(exec_pipe_w, struct.pack("i", exc.errno or 1))
        except Exception:
            pass
        os.close(exec_pipe_w)
        os._exit(1)
    except Exception:
        os.close(exec_pipe_w)
        os._exit(1)


def wait_for_termination(pid: int, timeout: float, poll_interval: float) -> bool:
    """等待子进程退出。"""
    start_time = time.monotonic()
    while True:
        try:
            result_pid, _ = os.waitpid(pid, os.WNOHANG)
            if result_pid != 0:
                return True
        except ChildProcessError:
            return True

        if time.monotonic() - start_time >= timeout:
            return False

        time.sleep(poll_interval)


def cleanup_wrapper(wrapper: "PTYWrapper") -> None:
    """清理 PTY 资源并重置状态。"""
    time.sleep(wrapper.CLEANUP_GRACE_PERIOD)

    if wrapper._original_sigwinch_handler:
        try:
            wrapper.signal_module.signal(
                wrapper.signal_module.SIGWINCH,
                wrapper._original_sigwinch_handler,
            )
        except Exception:
            pass
        wrapper._original_sigwinch_handler = None

    if wrapper.master_fd is not None:
        try:
            os.close(wrapper.master_fd)
        except OSError:
            pass
        wrapper.master_fd = None

    if wrapper.slave_fd is not None:
        try:
            os.close(wrapper.slave_fd)
        except OSError:
            pass
        wrapper.slave_fd = None

    wrapper.pid = None
    wrapper._running = False

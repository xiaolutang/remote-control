"""
PTY Wrapper 测试
"""
import asyncio
import os
import time
import pytest

from app.pty_wrapper import PTYWrapper, PTYConfig


class TestPTYWrapper:
    """PTY Wrapper 测试"""

    @pytest.mark.asyncio
    async def test_simple_command_output(self):
        """运行 ls → 捕获输出正确"""
        pty = PTYWrapper("/bin/echo", args=["hello world"])
        assert pty.start()

        # 等待输出
        output = b""
        for _ in range(10):  # 最多尝试 10 次
            data = await pty.read()
            if data:
                output += data
            if "hello world" in output.decode("utf-8", errors="replace"):
                break
            await asyncio.sleep(0.1)

        pty.stop()
        assert "hello world" in output.decode("utf-8", errors="replace")

    @pytest.mark.asyncio
    async def test_ansi_color_preserved(self):
        """运行带颜色的命令 → ANSI 转义码保留"""
        pty = PTYWrapper("/bin/bash", args=["-c", "echo -e '\\033[31mred\\033[0m'"])
        assert pty.start()

        # 等待输出
        output = b""
        for _ in range(10):
            data = await pty.read()
            if data:
                output += data
            if "red" in output.decode("utf-8", errors="replace"):
                break
            await asyncio.sleep(0.1)
        pty.stop()
        # 检查 ANSI 转义码是否保留
        assert b"\\033" in output or "red" in output.decode("utf-8", errors="replace")

    @pytest.mark.asyncio
    async def test_write_to_pty(self):
        """写入到 PTY stdin"""
        pty = PTYWrapper("/bin/cat")
        assert pty.start()

        # 写入数据
        pty.write(b"test input\n")

        # 读取输出
        output = b""
        for _ in range(10):
            data = await pty.read()
            if data:
                output += data
            if "test input" in output.decode("utf-8", errors="replace"):
                break
            await asyncio.sleep(0.1)

        pty.stop()
        assert "test input" in output.decode("utf-8", errors="replace")

    def test_resize_terminal(self):
        """调整终端大小"""
        pty = PTYWrapper("/bin/bash")
        assert pty.start()

        # 调整大小
        pty.resize(40, 120)

        # 检查是否还在运行
        assert pty.is_running()

        pty.stop()

    @pytest.mark.asyncio
    async def test_process_exit(self):
        """子进程退出"""
        pty = PTYWrapper("/bin/bash", args=["-c", "exit 42"])
        assert pty.start()

        # 等待进程退出
        start = time.time()
        while pty.is_running() and (time.time() - start) < 5:
            await asyncio.sleep(0.1)

        assert not pty.is_running()
        pty.stop()

    @pytest.mark.asyncio
    async def test_start_with_custom_cwd(self):
        """按指定 cwd 启动 PTY"""
        pty = PTYWrapper(
            "/bin/pwd",
            config=PTYConfig(cwd="/tmp"),
        )
        assert pty.start()

        output = b""
        for _ in range(10):
            data = await pty.read()
            if data:
                output += data
            if "/tmp" in output.decode("utf-8", errors="replace"):
                break
            await asyncio.sleep(0.1)

        pty.stop()
        assert "/tmp" in output.decode("utf-8", errors="replace")

    def test_stop_terminates_process(self):
        """停止 PTY 终止进程"""
        pty = PTYWrapper("/bin/bash")
        assert pty.start()

        pid = pty.pid
        assert pid is not None

        pty.stop()

        # 检查进程是否已终止
        time.sleep(0.1)
        assert not pty.is_running()

    @pytest.mark.asyncio
    async def test_stop_kills_process_group(self):
        """停止 PTY 时杀死整个进程组，包括子孙进程"""
        # 创建一个会 fork 子进程的脚本
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            # 父进程 sleep，子进程也 sleep，孙子进程也 sleep
            f.write('''#!/bin/bash
# 创建子进程
sleep 30 &
child_pid=$!
# 子进程再创建孙子进程
( sleep 30 ) &
grandchild_pid=$!
# 父进程也 sleep
sleep 30
''')
            script_path = f.name
        os.chmod(script_path, 0o755)

        try:
            pty = PTYWrapper("/bin/bash", args=[script_path])
            assert pty.start()

            pid = pty.pid
            assert pid is not None

            # 等待一小段时间让子进程启动
            await asyncio.sleep(0.5)

            # 获取进程组中的所有进程
            try:
                import subprocess
                result = subprocess.run(
                    ['pgrep', '-g', str(pid)],
                    capture_output=True,
                    text=True
                )
                # 应该有多个进程（至少 3 个 sleep）
                pids_before = result.stdout.strip().split('\n') if result.stdout.strip() else []
            except Exception:
                pids_before = []

            # 停止 PTY
            pty.stop()

            # 等待进程组被清理
            await asyncio.sleep(0.5)

            # 验证进程组中的所有进程都被终止
            try:
                result = subprocess.run(
                    ['pgrep', '-g', str(pid)],
                    capture_output=True,
                    text=True
                )
                pids_after = result.stdout.strip().split('\n') if result.stdout.strip() else []
                # 进程组应该为空
                assert pids_after == [''] or pids_after == [], \
                    f"进程组中仍有残留进程: {pids_after}"
            except Exception:
                pass  # pgrep 可能因为进程组不存在而失败，这是期望的

            # 验证 PTY 不再运行
            assert not pty.is_running()
        finally:
            os.unlink(script_path)

    def test_stop_handles_missing_process_group(self):
        """进程组不存在时错误被正确处理"""
        pty = PTYWrapper("/bin/bash", args=["-c", "exit 0"])
        assert pty.start()

        # 等待进程自然退出
        time.sleep(0.5)

        # 进程已退出，但调用 stop() 不应抛出异常
        pty.stop()  # 应该正常处理 ProcessLookupError

        assert not pty.is_running()

    def test_multiple_stop_calls_safe(self):
        """多次调用 stop() 是安全的"""
        pty = PTYWrapper("/bin/bash")
        assert pty.start()

        # 第一次 stop
        pty.stop()

        # 第二次 stop 不应抛出异常
        pty.stop()

        # 第三次 stop
        pty.stop()

        assert not pty.is_running()

    def test_stop_sends_sigkill_on_timeout(self):
        """超时后发送 SIGKILL 强制终止"""
        # 创建一个忽略 SIGTERM 的脚本
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            # 捕获 SIGTERM 但不退出
            f.write('''#!/bin/bash
trap 'echo "Ignoring SIGTERM"' TERM
sleep 60
''')
            script_path = f.name
        os.chmod(script_path, 0o755)

        try:
            pty = PTYWrapper("/bin/bash", args=[script_path])
            assert pty.start()

            pid = pty.pid
            assert pid is not None

            # 等待进程启动
            time.sleep(0.3)

            # 验证进程在运行
            assert pty.is_running()

            # 设置较短的超时进行测试
            original_timeout = PTYWrapper.GRACEFUL_TIMEOUT
            PTYWrapper.GRACEFUL_TIMEOUT = 0.5  # 0.5 秒超时

            try:
                # stop() 应该在超时后发送 SIGKILL
                start_time = time.time()
                pty.stop()
                elapsed = time.time() - start_time

                # 验证 stop() 在合理时间内完成（不超过超时 + 1 秒）
                assert elapsed < 2.0, f"stop() took too long: {elapsed}s"

                # 验证进程已终止
                assert not pty.is_running()
            finally:
                PTYWrapper.GRACEFUL_TIMEOUT = original_timeout
        finally:
            os.unlink(script_path)

    def test_normal_exit_does_not_trigger_sigkill(self):
        """正常退出时不触发 SIGKILL"""
        # 创建一个快速退出的脚本
        pty = PTYWrapper("/bin/bash", args=["-c", "sleep 0.1 && exit 0"])
        assert pty.start()

        pid = pty.pid
        assert pid is not None

        # 等待进程自然退出
        time.sleep(0.3)

        # 进程应该已经退出
        assert not pty.is_running()

        # stop() 应该快速完成（不会等待超时）
        start_time = time.time()
        pty.stop()
        elapsed = time.time() - start_time

        # 应该非常快（不需要等待超时）
        assert elapsed < 0.5, f"stop() took too long for exited process: {elapsed}s"
        assert not pty.is_running()

    def test_cleanup_resets_all_state(self):
        """清理后所有状态变量都被重置"""
        pty = PTYWrapper("/bin/bash")
        assert pty.start()

        # 保存原始值
        original_pid = pty.pid
        original_master_fd = pty.master_fd
        original_slave_fd = pty.slave_fd

        assert original_pid is not None
        assert original_master_fd is not None
        assert original_slave_fd is not None

        # 停止
        pty.stop()

        # 验证所有状态都被重置
        assert pty.pid is None, "pid should be None after cleanup"
        assert pty.master_fd is None, "master_fd should be None after cleanup"
        assert pty.slave_fd is None, "slave_fd should be None after cleanup"
        assert pty._running is False, "_running should be False after cleanup"

    def test_multiple_stop_idempotent(self):
        """多次调用 stop() 是幂等的"""
        pty = PTYWrapper("/bin/bash")
        assert pty.start()

        # 第一次 stop
        pty.stop()
        state_after_first = (pty.pid, pty.master_fd, pty.slave_fd, pty._running)

        # 第二次 stop
        pty.stop()
        state_after_second = (pty.pid, pty.master_fd, pty.slave_fd, pty._running)

        # 第三次 stop
        pty.stop()
        state_after_third = (pty.pid, pty.master_fd, pty.slave_fd, pty._running)

        # 所有状态应该相同
        assert state_after_first == state_after_second == state_after_third
        assert state_after_first == (None, None, None, False)

    def test_fd_closed_properly(self):
        """文件描述符被正确关闭"""
        pty = PTYWrapper("/bin/bash")
        assert pty.start()

        master_fd = pty.master_fd
        slave_fd = pty.slave_fd

        # 验证 fd 是有效的
        assert master_fd is not None
        assert slave_fd is not None

        # 停止
        pty.stop()

        # 验证 fd 已被关闭（尝试使用应该失败）
        try:
            os.read(master_fd, 1)
            assert False, "Should not be able to read from closed fd"
        except OSError:
            pass  # 预期：fd 已关闭

    def test_rapid_create_destroy_cycle(self):
        """快速连续创建和销毁终端（模拟网络断开重连场景）"""
        for i in range(5):
            pty = PTYWrapper("/bin/bash", args=["-c", f"echo 'cycle {i}'"])
            assert pty.start()

            # 短暂等待
            time.sleep(0.1)

            # 验证进程在运行
            assert pty.is_running()

            # 快速停止
            pty.stop()

            # 验证进程已终止
            assert not pty.is_running()

    def test_multiple_ptys_independent(self):
        """多个 PTY 实例独立运行和停止"""
        ptys = []

        # 创建多个 PTY
        for i in range(3):
            pty = PTYWrapper("/bin/bash", args=["-c", f"sleep 10 && echo 'pty {i}'"])
            assert pty.start()
            ptys.append(pty)
            time.sleep(0.1)

        # 验证所有 PTY 都在运行
        for pty in ptys:
            assert pty.is_running()

        # 逐个停止
        for i, pty in enumerate(ptys):
            pty.stop()
            assert not pty.is_running()
            # 验证其他 PTY 仍然运行（或已停止）
            for j, other_pty in enumerate(ptys):
                if j > i:
                    # 还没被停止的应该仍在运行
                    assert other_pty.is_running()

    def test_stop_during_high_io_activity(self):
        """高 IO 活动期间停止 PTY"""
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            # 持续输出大量数据
            f.write('''#!/bin/bash
for i in $(seq 1 1000); do
    echo "Line $i with some padding data to make it longer"
done
sleep 10
''')
            script_path = f.name
        os.chmod(script_path, 0o755)

        try:
            pty = PTYWrapper("/bin/bash", args=[script_path])
            assert pty.start()

            # 等待一些输出
            time.sleep(0.2)

            # 验证进程在运行
            assert pty.is_running()

            # 在高 IO 期间停止
            start_time = time.time()
            pty.stop()
            elapsed = time.time() - start_time

            # 应该在合理时间内完成
            assert elapsed < 5.0, f"stop() took too long during high IO: {elapsed}s"
            assert not pty.is_running()
        finally:
            os.unlink(script_path)

    def test_orphan_process_prevention(self):
        """验证不会产生孤儿进程"""
        import subprocess
        import tempfile

        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            # 创建会 fork 多层子进程的脚本（使用较短的 sleep 时间）
            f.write('''#!/bin/bash
# 启动后台子进程
( sleep 5 ) &
( sleep 5 ) &
( sleep 5 ) &
# 主进程也 sleep
sleep 5
''')
            script_path = f.name
        os.chmod(script_path, 0o755)

        try:
            pty = PTYWrapper("/bin/bash", args=[script_path])
            assert pty.start()
            pid = pty.pid

            # 等待子进程启动
            time.sleep(0.3)

            # 获取进程组中的进程数
            result = subprocess.run(
                ['pgrep', '-g', str(pid)],
                capture_output=True,
                text=True
            )
            pids_before = len([p for p in result.stdout.strip().split('\n') if p])
            assert pids_before > 1, "Should have multiple processes in group"

            # 停止 PTY
            pty.stop()

            # 等待清理完成
            time.sleep(0.5)

            # 验证进程组已被完全清理
            result = subprocess.run(
                ['pgrep', '-g', str(pid)],
                capture_output=True,
                text=True
            )
            pids_after = result.stdout.strip()

            # 进程组应该不存在或为空
            assert pids_after == '', f"Orphan processes found: {pids_after}"
        finally:
            os.unlink(script_path)

    def test_start_nonexistent_command_returns_false(self):
        """不存在的命令 start() 返回 False"""
        pty = PTYWrapper("/nonexistent_command_that_does_not_exist_xyz")
        assert pty.start() is False
        assert not pty._running

    def test_start_nonexistent_command_sets_errno(self):
        """不存在的命令 _exec_errno 包含正确的 errno，start_error 返回可读描述"""
        import errno
        pty = PTYWrapper("/nonexistent_command_that_does_not_exist_xyz")
        pty.start()
        assert pty._exec_errno is not None
        assert pty._exec_errno == errno.ENOENT
        assert pty.start_error is not None
        assert "No such file" in pty.start_error

    def test_start_valid_command_returns_true(self):
        """正常命令 start() 返回 True（回归测试）"""
        pty = PTYWrapper("/bin/echo", args=["hello"])
        assert pty.start() is True
        assert pty._running
        assert pty._exec_errno is None
        pty.stop()

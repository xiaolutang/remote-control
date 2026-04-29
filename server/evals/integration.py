"""
Eval Integration Runner — Docker 构建 + 部署 + 真实 API 测试

S127: 集成测试框架核心。
通过 Docker 构建部署真实 Server 服务，eval 通过 HTTP API 打真实接口，
覆盖完整链路（Agent 框架 + message_history 重建 + SSE 流式 + 数据库）。

用法（CLI 自动调用，不直接使用）：
    python -m evals run --mode integration --tasks server/evals/tasks --trials 1

核心类：
    IntegrationRunner: 上下文管理器，封装 Docker 构建/部署/health-check/tear-down
    IntegrationEvalClient: 通过 HTTP API 调用真实 Server 执行 eval task
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from uuid import uuid4

import httpx

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────

DEFAULT_BASE_URL = "http://localhost:8880"
DEFAULT_HEALTH_PATH = "/health"
DEFAULT_HEALTH_TIMEOUT = 90  # 秒
DEFAULT_HEALTH_INTERVAL = 2  # 秒
DEFAULT_AGENT_ONLINE_TIMEOUT = 60  # 秒
DEFAULT_AGENT_STREAM_TIMEOUT = 180.0  # 秒

# eval 测试用户前缀
EVAL_TEST_USER_PREFIX = "eval_test_"
EVAL_TEST_PASSWORD = "EvalTest123!"
EVAL_AGENT_USER_PREFIX = "eval_agent_"
EVAL_AGENT_PASSWORD = "AgentPass123456"


# ── Docker 构建/部署 ─────────────────────────────────────────────────────


class DockerBuildError(Exception):
    """Docker 构建或部署失败"""


class HealthCheckTimeout(Exception):
    """健康检查超时"""


class AgentStartupError(Exception):
    """集成测试 Agent 启动或上线失败"""


class IntegrationRunner:
    """集成测试运行器：构建 Docker 镜像、启动服务、健康检查、最终 tear down。

    支持上下文管理器：

        with IntegrationRunner() as runner:
            runner.build_and_deploy()
            runner.wait_for_healthy()
            # ... 运行 eval ...
        # 自动 tear down

    也支持手动调用：

        runner = IntegrationRunner()
        try:
            runner.build_and_deploy()
            runner.wait_for_healthy()
            # ...
        finally:
            runner.tear_down()
    """

    def __init__(
        self,
        project_root: str | Path | None = None,
        base_url: str = DEFAULT_BASE_URL,
        health_path: str = DEFAULT_HEALTH_PATH,
        health_timeout: int = DEFAULT_HEALTH_TIMEOUT,
        health_interval: int = DEFAULT_HEALTH_INTERVAL,
        compose_file: str | None = None,
        build_target: str = "server",
        skip_build: bool = False,
        env_file: str | None = None,
    ):
        """
        Args:
            project_root: 项目根目录（默认自动检测）
            base_url: 服务基础 URL
            health_path: 健康检查路径
            health_timeout: 健康检查超时秒数
            health_interval: 健康检查轮询间隔秒数
            compose_file: docker-compose 文件路径（默认 deploy/docker-compose.yml）
            build_target: 构建目标（server / agent / all）
            skip_build: 跳过构建（使用已有镜像）
            env_file: .env 文件路径（默认项目根目录 .env）
        """
        if project_root is None:
            # 自动检测：从本文件向上找 git root
            project_root = self._find_project_root()
        self.project_root = Path(project_root)
        self.base_url = base_url.rstrip("/")
        self.health_path = health_path
        self.health_timeout = health_timeout
        self.health_interval = health_interval
        self.build_target = build_target
        self.skip_build = skip_build

        # compose 文件路径
        if compose_file:
            self.compose_file = Path(compose_file)
        else:
            self.compose_file = self.project_root / "deploy" / "docker-compose.yml"

        # .env 文件
        if env_file:
            self.env_file = Path(env_file)
        else:
            self.env_file = self.project_root / ".env"

        self._deployed = False
        self._process: subprocess.Popen | None = None

    @staticmethod
    def _find_project_root() -> Path:
        """从当前文件向上查找 git 项目根目录。"""
        current = Path(__file__).resolve().parent
        for parent in [current] + list(current.parents):
            if (parent / ".git").exists():
                return parent
        # 回退到 remote-control 目录
        return Path(__file__).resolve().parent.parent.parent

    def __enter__(self) -> "IntegrationRunner":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.tear_down()

    def install_signal_handlers(self) -> None:
        """注册 SIGINT/SIGTERM 信号处理器，确保进程退出前执行 tear_down。

        典型用法：在 build_and_deploy 之前调用，确保 Ctrl+C 或 kill 时清理 Docker。
        """
        runner_self = self  # closure capture

        original_sigint = signal.getsignal(signal.SIGINT)
        original_sigterm = signal.getsignal(signal.SIGTERM)

        def _signal_handler(signum: int, frame) -> None:
            logger.info("Received signal %s, cleaning up ...", signum)
            runner_self.tear_down()
            # 恢复原始处理器
            signal.signal(signal.SIGINT, original_sigint)
            signal.signal(signal.SIGTERM, original_sigterm)
            raise KeyboardInterrupt()

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        # 保存以便稍后恢复
        self._original_sigint = original_sigint
        self._original_sigterm = original_sigterm

    def restore_signal_handlers(self) -> None:
        """恢复原始信号处理器。"""
        if hasattr(self, "_original_sigint"):
            signal.signal(signal.SIGINT, self._original_sigint)
        if hasattr(self, "_original_sigterm"):
            signal.signal(signal.SIGTERM, self._original_sigterm)

    def _compose_cmd(self, *args: str, include_agent_profile: bool = False) -> list[str]:
        """构建 docker compose 命令。"""
        cmd = ["docker", "compose", "-f", str(self.compose_file)]
        if self.env_file.exists():
            cmd.extend(["--env-file", str(self.env_file)])
        if include_agent_profile:
            cmd.extend(["--profile", "standalone-agent"])
        cmd.extend(args)
        return cmd

    def _load_env_values(self) -> dict[str, str]:
        """读取 .env 与当前进程环境变量。"""
        values: dict[str, str] = {}
        if self.env_file.exists():
            for raw_line in self.env_file.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("'\"")

        for key in ("AGENT_USERNAME", "AGENT_PASSWORD"):
            env_value = os.environ.get(key)
            if env_value:
                values[key] = env_value

        return values

    def _resolve_agent_auth(
        self,
        *,
        agent_token: str = "",
        agent_username: str = "",
        agent_password: str = "",
    ) -> dict[str, str]:
        """解析 integration Agent 启动凭据。优先显式参数，其次环境变量/.env。"""
        values = self._load_env_values()
        if agent_token:
            values["AGENT_TOKEN"] = agent_token
        if agent_username:
            values["AGENT_USERNAME"] = agent_username
        if agent_password:
            values["AGENT_PASSWORD"] = agent_password

        if values.get("AGENT_TOKEN"):
            return values

        missing = [
            key for key in ("AGENT_USERNAME", "AGENT_PASSWORD")
            if not values.get(key)
        ]
        if missing:
            missing_str = "AGENT_TOKEN 或 " + ", ".join(missing)
            raise AgentStartupError(
                f"integration 模式缺少 Agent 凭据: {missing_str}。"
                "请在 .env 或环境变量中设置。"
            )
        return values

    def _collect_agent_failure_output(self) -> str:
        """收集已退出 Agent 进程的 stdout/stderr 片段。"""
        if self._process is None:
            return ""
        try:
            stdout, stderr = self._process.communicate(timeout=1)
        except Exception:
            return ""

        chunks = [text.strip() for text in (stderr, stdout) if text and text.strip()]
        if not chunks:
            return ""
        return "\n".join(chunks)[-2000:]

    def start_agent(
        self,
        *,
        agent_token: str = "",
        agent_username: str = "",
        agent_password: str = "",
    ) -> None:
        """启动 integration 模式下的 Agent 进程。"""
        auth_values = self._resolve_agent_auth(
            agent_token=agent_token,
            agent_username=agent_username,
            agent_password=agent_password,
        )
        if self._process and self._process.poll() is None:
            logger.info("[integration] Agent 进程已在运行，跳过重复启动")
            return

        cmd = self._compose_cmd(
            "run", "--rm", "--use-aliases", "agent",
            include_agent_profile=True,
        )
        logger.info("[integration] 启动 Agent 进程 ...")

        try:
            child_env = os.environ.copy()
            for key in ("AGENT_TOKEN", "AGENT_USERNAME", "AGENT_PASSWORD"):
                if auth_values.get(key):
                    child_env[key] = auth_values[key]
            self._process = subprocess.Popen(
                cmd,
                cwd=str(self.project_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=child_env,
            )
        except FileNotFoundError:
            raise AgentStartupError("docker 不可用，无法启动 integration Agent")

        time.sleep(1.0)
        if self._process.poll() is not None:
            output = self._collect_agent_failure_output()
            raise AgentStartupError(
                "Agent 进程启动失败"
                + (f":\n{output}" if output else "")
            )

    async def wait_agent_online(
        self,
        eval_client: "IntegrationEvalClient",
        timeout: int = DEFAULT_AGENT_ONLINE_TIMEOUT,
    ) -> str:
        """等待 Agent 设备上线并返回 device_id。"""
        logger.info("[integration] 等待 Agent 上线 (timeout=%ds) ...", timeout)
        start = time.monotonic()
        last_error = ""

        while time.monotonic() - start < timeout:
            if self._process and self._process.poll() is not None:
                output = self._collect_agent_failure_output()
                raise AgentStartupError(
                    "Agent 进程异常退出"
                    + (f":\n{output}" if output else "")
                )

            try:
                device_id = await eval_client.get_or_create_device()
                if device_id:
                    logger.info("[integration] Agent 已上线: %s", device_id)
                    return device_id
            except Exception as exc:
                last_error = str(exc)

            await asyncio.sleep(self.health_interval)

        detail = f"，最后错误: {last_error}" if last_error else ""
        raise AgentStartupError(f"Agent 未在 {timeout}s 内上线{detail}")

    def stop_agent(self) -> None:
        """停止 integration 模式下的 Agent 进程。"""
        if self._process is None:
            return

        process = self._process
        self._process = None
        if process.poll() is not None:
            self._collect_agent_failure_output()
            return

        logger.info("[integration] 停止 Agent 进程 ...")
        try:
            process.terminate()
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        except Exception as e:
            logger.warning("[integration] 停止 Agent 进程失败: %s", e)

    # ── 构建 ─────────────────────────────────────────────────────────────

    def build_and_deploy(self) -> None:
        """执行 Docker 构建并启动服务。

        流程：
        1. 调用 deploy/build.sh 构建 Docker 镜像
        2. docker compose up -d 启动服务

        Raises:
            DockerBuildError: 构建或部署失败
        """
        if self.skip_build:
            logger.info("[integration] 跳过 Docker 构建（skip_build=True）")
        else:
            self._build_images()

        self._deploy_services()

    def _build_images(self) -> None:
        """调用 deploy/build.sh 构建 Docker 镜像。"""
        build_script = self.project_root / "deploy" / "build.sh"
        if not build_script.exists():
            raise DockerBuildError(
                f"构建脚本不存在: {build_script}。"
                f"请确认项目结构正确。"
            )

        logger.info(
            "[integration] 开始 Docker 构建 (target=%s) ...",
            self.build_target,
        )
        start = time.monotonic()

        try:
            result = subprocess.run(
                ["bash", str(build_script), self.build_target],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=600,  # 构建最多 10 分钟
            )

            elapsed = time.monotonic() - start
            if result.returncode != 0:
                stderr_preview = result.stderr[-2000:] if result.stderr else "(无 stderr)"
                raise DockerBuildError(
                    f"Docker 构建失败 (exit={result.returncode}, {elapsed:.1f}s):\n"
                    f"{stderr_preview}"
                )

            logger.info(
                "[integration] Docker 构建完成 (%.1fs)", elapsed,
            )

        except subprocess.TimeoutExpired:
            raise DockerBuildError(
                "Docker 构建超时（10 分钟）。"
                "请检查 Docker buildx 是否正常。"
            )
        except FileNotFoundError:
            raise DockerBuildError(
                "bash 未找到，请确认运行环境中 bash 可用。"
            )

    def _deploy_services(self) -> None:
        """启动 docker compose 服务。"""
        if not self.compose_file.exists():
            raise DockerBuildError(
                f"docker-compose 文件不存在: {self.compose_file}"
            )

        logger.info("[integration] 启动 docker compose 服务 ...")

        cmd = self._compose_cmd("up", "-d", "--wait-timeout", "60")

        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode != 0:
                stderr_preview = result.stderr[-2000:] if result.stderr else "(无 stderr)"
                raise DockerBuildError(
                    f"docker compose up 失败 (exit={result.returncode}):\n"
                    f"{stderr_preview}"
                )

            self._deployed = True
            logger.info("[integration] docker compose 服务已启动")

        except subprocess.TimeoutExpired:
            raise DockerBuildError(
                "docker compose up 超时（120 秒）。"
                "请检查服务是否正常启动。"
            )

    # ── 健康检查 ─────────────────────────────────────────────────────────

    def wait_for_healthy(self, timeout: int | None = None) -> bool:
        """轮询 /health 端点，等待服务就绪。

        Args:
            timeout: 超时秒数（默认使用构造参数）

        Returns:
            True 如果服务健康

        Raises:
            HealthCheckTimeout: 超时时
        """
        actual_timeout = timeout or self.health_timeout
        url = f"{self.base_url}{self.health_path}"
        logger.info(
            "[integration] 等待服务就绪 (url=%s, timeout=%ds) ...",
            url, actual_timeout,
        )

        start = time.monotonic()
        while time.monotonic() - start < actual_timeout:
            try:
                resp = httpx.get(url, timeout=5, follow_redirects=True)
                if resp.status_code == 200:
                    elapsed = time.monotonic() - start
                    logger.info(
                        "[integration] 服务就绪 (%.1fs) — %s",
                        elapsed, resp.json(),
                    )
                    return True
            except (httpx.ConnectError, httpx.TimeoutException):
                pass

            time.sleep(self.health_interval)

        raise HealthCheckTimeout(
            f"服务未在 {actual_timeout}s 内就绪 (url={url})"
        )

    # ── Tear Down ────────────────────────────────────────────────────────

    def tear_down(self) -> None:
        """停止 docker compose 服务。"""
        self.stop_agent()
        if not self._deployed:
            return

        logger.info("[integration] 停止 docker compose 服务 ...")
        cmd = self._compose_cmd("down")

        try:
            subprocess.run(
                cmd,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=60,
            )
            logger.info("[integration] docker compose 服务已停止")
        except Exception as e:
            logger.warning("[integration] tear down 失败: %s", e)
        finally:
            self._deployed = False


# ── 集成测试 HTTP Client ────────────────────────────────────────────────


class IntegrationEvalClient:
    """通过真实 HTTP API 调用 Server，执行 eval task。

    流程：
    1. 注册/登录测试用户获取 JWT
    2. 对每个 eval task：
       a. 调用 Agent session API 创建会话
       b. 发送用户消息
       c. 收集 SSE 流式响应
       d. 解析最终结果
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        test_user_prefix: str = EVAL_TEST_USER_PREFIX,
        test_password: str = EVAL_TEST_PASSWORD,
        http_timeout: float = 60.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.test_user_prefix = test_user_prefix
        self.test_password = test_password
        self.http_timeout = http_timeout
        self._token: str = ""
        self._user_id: str = ""
        self._device_id: str = ""
        self._terminal_id: str = ""
        self._conversation_id: str = ""
        self._session_id: str = ""
        self._pending_question_id: str = ""
        self._stream_offset: int = 0
        self._http_client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端。"""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.http_timeout,
            )
        return self._http_client

    async def close(self) -> None:
        """关闭 HTTP 客户端。"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    async def setup(self) -> None:
        """注册测试用户并获取 JWT token。"""
        ts = int(time.time())
        username = f"{self.test_user_prefix}{ts}"
        body = await self.register_user(username=username, password=self.test_password)
        self._token = body.get("token", "")
        self._user_id = body.get("user_id", "")

        if not self._token:
            raise RuntimeError("注册响应中无 token")

        logger.info(
            "[integration] 测试用户已注册: %s (user_id=%s)",
            username, self._user_id,
        )

    def use_access_token(self, token: str, user_id: str = "") -> None:
        """直接注入已获取的 access token，供 integration runtime 复用同一用户上下文。"""
        self._token = token
        self._user_id = user_id

    async def register_user(self, *, username: str, password: str) -> Dict[str, Any]:
        """注册测试用户并返回响应体。"""
        client = await self._get_client()
        resp = await client.post(
            "/api/register",
            json={"username": username, "password": password},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"注册测试用户失败: {resp.status_code} {resp.text}")
        return resp.json()

    async def provision_agent_identity(self) -> Dict[str, str]:
        """为 integration Agent 注册独立测试用户，并返回同用户的 token / user_id。"""
        ts = int(time.time())
        username = f"{EVAL_AGENT_USER_PREFIX}{ts}"
        body = await self.register_user(
            username=username,
            password=EVAL_AGENT_PASSWORD,
        )
        access_token = body.get("access_token") or body.get("token") or ""
        user_id = body.get("user_id", "")
        if not access_token:
            raise RuntimeError("Agent 测试用户注册响应中无 token")
        logger.info("[integration] Agent 测试用户已注册: %s", username)
        return {
            "username": username,
            "access_token": access_token,
            "user_id": user_id,
        }

    async def provision_agent_access_token(self) -> str:
        """为 integration Agent 注册独立测试用户并返回 access token。"""
        identity = await self.provision_agent_identity()
        return identity["access_token"]

    async def get_auth_headers(self) -> Dict[str, str]:
        """获取认证头。"""
        return {"Authorization": f"Bearer {self._token}"}

    def _next_client_event_id(self, prefix: str) -> str:
        return f"{prefix}-{uuid4().hex[:12]}"

    def _reset_runtime_state(self, *, preserve_terminal: bool = False) -> None:
        """清理当前 integration task/runtime 的会话状态。"""
        self._session_id = ""
        self._pending_question_id = ""
        self._stream_offset = 0
        if not preserve_terminal:
            self._terminal_id = ""
            self._conversation_id = ""

    def runtime_state(self) -> Dict[str, str | int]:
        """暴露当前 runtime 状态，供 integration harness 记录。"""
        return {
            "device_id": self._device_id,
            "terminal_id": self._terminal_id,
            "conversation_id": self._conversation_id,
            "session_id": self._session_id,
            "pending_question_id": self._pending_question_id,
            "stream_offset": self._stream_offset,
        }

    async def call_agent_api(
        self,
        task_intent: str,
        device_id: str = "",
        terminal_id: str = "",
        conversation_id: str = "",
    ) -> Dict[str, Any]:
        """通过真实 Agent API 发送 eval task 并收集结果。

        根据是否有 device_id/terminal_id 选择不同的 API 路径：
        - 有 terminal_id: 调用 Agent SSE run API
        - 无 terminal_id: 调用基础 agent API（如果可用）

        Args:
            task_intent: 用户意图（eval task 的 input.intent）
            device_id: 设备 ID（可选）
            terminal_id: 终端 ID（可选）
            conversation_id: 会话 ID（可选）

        Returns:
            Agent 结果 dict（与 unit mode 格式一致）
        """
        client = await self._get_client()
        headers = await self.get_auth_headers()

        # 尝试通过 Agent SSE API 调用
        if device_id and terminal_id:
            result = await self.create_terminal_then_run(
                device_id=device_id,
                task_intent=task_intent,
                terminal_id=terminal_id,
                conversation_id=conversation_id,
            )
            return result["agent_result"]

        # 尝试通过 assistant plan API 调用
        if device_id:
            return await self._call_assistant_plan(
                client, headers, device_id, task_intent, conversation_id,
            )

        # 基础模式：仅验证 API 可达，不调用 Agent
        return {
            "response_type": "error",
            "summary": "integration 模式需要 device_id（Agent 设备）才能调用 Agent API",
            "steps": [],
            "need_confirm": False,
        }

    async def execute_turn(
        self,
        *,
        device_id: str,
        turn: Dict[str, Any],
        terminal_id: str = "",
        conversation_id: str = "",
    ) -> Dict[str, Any]:
        """执行一个 integration turn，支持 intent 或 answer。"""
        if not device_id:
            return self._error_bundle(
                "integration 模式需要 device_id（Agent 设备）才能调用 Agent API"
            )

        if turn.get("answer") is not None:
            return await self.respond_to_agent(
                device_id=device_id,
                answer=str(turn.get("answer", "")),
                session_id=str(turn.get("session_id", "") or self._session_id),
                question_id=str(turn.get("question_id", "") or self._pending_question_id),
                terminal_id=terminal_id or self._terminal_id,
            )

        intent = str(turn.get("intent", "")).strip()
        if not intent:
            return self._error_bundle("integration turn 缺少 intent 或 answer")

        return await self.create_terminal_then_run(
            device_id=device_id,
            task_intent=intent,
            terminal_id=terminal_id or self._terminal_id,
            conversation_id=conversation_id or self._conversation_id,
            truncate_after_index=turn.get("truncate_after_index"),
        )

    async def create_terminal_then_run(
        self,
        *,
        device_id: str,
        task_intent: str,
        terminal_id: str = "",
        conversation_id: str = "",
        truncate_after_index: Optional[int] = None,
    ) -> Dict[str, Any]:
        """先确保 terminal 存在，再调用 terminal-bound Agent SSE API。"""
        client = await self._get_client()
        headers = await self.get_auth_headers()

        effective_terminal_id = terminal_id or self._terminal_id
        terminal_created = False

        if not effective_terminal_id:
            terminal = await self.create_terminal(device_id)
            if terminal.get("error"):
                error_bundle = self._error_bundle(str(terminal["error"]))
                error_bundle["terminal_created"] = False
                return error_bundle
            effective_terminal_id = terminal.get("terminal_id", "")
            terminal_created = True

        if not effective_terminal_id:
            error_bundle = self._error_bundle("创建终端后未返回 terminal_id")
            error_bundle["terminal_created"] = terminal_created
            return error_bundle

        self._device_id = device_id
        self._terminal_id = effective_terminal_id
        if conversation_id:
            self._conversation_id = conversation_id
        self._session_id = ""
        self._pending_question_id = ""
        self._stream_offset = 0

        result = await self._call_terminal_agent(
            client,
            headers,
            device_id,
            effective_terminal_id,
            task_intent,
            conversation_id=self._conversation_id,
            truncate_after_index=truncate_after_index,
        )
        result["terminal_created"] = terminal_created
        return result

    async def respond_to_agent(
        self,
        *,
        device_id: str,
        answer: str,
        session_id: str = "",
        question_id: str = "",
        terminal_id: str = "",
    ) -> Dict[str, Any]:
        """向 ask_user 问题提交回复，并继续 resume SSE 流。"""
        answer = answer.strip()
        if not answer:
            return self._error_bundle("answer 不能为空")

        effective_terminal_id = terminal_id or self._terminal_id
        effective_session_id = session_id or self._session_id
        effective_question_id = question_id or self._pending_question_id
        if not device_id or not effective_terminal_id or not effective_session_id or not effective_question_id:
            return self._error_bundle("回复 ask_user 需要 device_id / terminal_id / session_id / question_id")

        client = await self._get_client()
        headers = await self.get_auth_headers()
        url = (
            f"/api/runtime/devices/{device_id}/terminals/{effective_terminal_id}"
            f"/assistant/agent/{effective_session_id}/respond"
        )
        payload = {
            "answer": answer,
            "question_id": effective_question_id,
            "client_event_id": self._next_client_event_id("eval-answer"),
        }

        try:
            response = await client.post(url, json=payload, headers=headers, timeout=DEFAULT_AGENT_STREAM_TIMEOUT)
            if response.status_code != 200:
                return self._error_bundle(
                    f"Agent respond API 返回 {response.status_code}: {response.text[:500]}",
                    terminal_created=False,
                )
        except httpx.TimeoutException:
            return self._error_bundle("Agent respond API 超时（180s）", terminal_created=False)
        except httpx.ConnectError as e:
            return self._error_bundle(f"连接 Agent respond API 失败: {e}", terminal_created=False)

        resume_url = (
            f"/api/runtime/devices/{device_id}/terminals/{effective_terminal_id}"
            f"/assistant/agent/{effective_session_id}/resume"
        )
        try:
            async with client.stream(
                "GET",
                resume_url,
                params={"after_index": self._stream_offset},
                headers=headers,
                timeout=DEFAULT_AGENT_STREAM_TIMEOUT,
            ) as resume_response:
                if resume_response.status_code != 200:
                    body = await resume_response.aread()
                    return self._error_bundle(
                        f"Agent resume API 返回 {resume_response.status_code}: {body.decode()[:500]}",
                        terminal_created=False,
                    )
                return await self._parse_sse_response(
                    resume_response,
                    allow_question_break=True,
                    initial_offset=self._stream_offset,
                )
        except httpx.TimeoutException:
            return self._error_bundle("Agent resume API 超时（180s）", terminal_created=False)
        except httpx.ConnectError as e:
            return self._error_bundle(f"连接 Agent resume API 失败: {e}", terminal_created=False)

    async def _call_terminal_agent(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        device_id: str,
        terminal_id: str,
        task_intent: str,
        *,
        conversation_id: str = "",
        truncate_after_index: Optional[int] = None,
    ) -> Dict[str, Any]:
        """通过 Terminal Agent SSE run API 调用。"""
        url = (
            f"/api/runtime/devices/{device_id}/terminals/{terminal_id}"
            f"/assistant/agent/run"
        )

        payload = {
            "intent": task_intent,
            "client_event_id": self._next_client_event_id("eval-run"),
        }
        if conversation_id:
            payload["conversation_id"] = conversation_id
        if truncate_after_index is not None:
            payload["truncate_after_index"] = int(truncate_after_index)

        try:
            async with client.stream(
                "POST", url, json=payload, headers=headers, timeout=DEFAULT_AGENT_STREAM_TIMEOUT,
            ) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    return self._error_bundle(
                        f"Agent API 返回 {response.status_code}: {body.decode()[:500]}",
                        terminal_created=False,
                    )

                # 读取 SSE 流，收集最终结果
                return await self._parse_sse_response(response, allow_question_break=True, initial_offset=0)

        except httpx.TimeoutException:
            return self._error_bundle("Agent API 超时（180s）", terminal_created=False)
        except httpx.ConnectError as e:
            return self._error_bundle(f"连接 Agent API 失败: {e}", terminal_created=False)

    async def _call_assistant_plan(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        device_id: str,
        task_intent: str,
        conversation_id: str = "",
    ) -> Dict[str, Any]:
        """通过 Assistant Plan API 调用（不依赖 Terminal）。"""
        url = f"/api/runtime/devices/{device_id}/assistant/plan"

        if not conversation_id:
            conversation_id = f"eval-conv-{int(time.time())}"

        payload = {
            "intent": task_intent,
            "conversation_id": conversation_id,
            "message_id": f"eval-msg-{int(time.time())}",
            "fallback_policy": {
                "use_local_rules": True,
                "use_cli": False,
            },
        }

        try:
            response = await client.post(
                url, json=payload, headers=headers, timeout=120.0,
            )

            if response.status_code != 200:
                return {
                    "response_type": "error",
                    "summary": (
                        f"Assistant Plan API 返回 {response.status_code}: "
                        f"{response.text[:500]}"
                    ),
                    "steps": [],
                    "need_confirm": False,
                }

            body = response.json()
            cmd_seq = body.get("command_sequence", {})

            # 将 planner 结果转换为 eval agent_result 格式
            steps = cmd_seq.get("steps", [])
            return {
                "response_type": "command" if steps else "message",
                "summary": cmd_seq.get("summary", ""),
                "steps": steps,
                "need_confirm": bool(steps),
            }

        except httpx.TimeoutException:
            return {
                "response_type": "error",
                "summary": "Assistant Plan API 超时（120s）",
                "steps": [],
                "need_confirm": False,
            }
        except httpx.ConnectError as e:
            return {
                "response_type": "error",
                "summary": f"连接 Assistant Plan API 失败: {e}",
                "steps": [],
                "need_confirm": False,
            }

    async def _parse_sse_response(
        self,
        response: httpx.Response,
        *,
        allow_question_break: bool = True,
        initial_offset: int = 0,
    ) -> Dict[str, Any]:
        """解析新 SSE 协议，收集完整事件、token usage 与 streaming_text。"""
        session_id = response.headers.get("X-Agent-Session-Id", self._session_id)
        conversation_id = response.headers.get("X-Agent-Conversation-Id", self._conversation_id)
        terminal_id = self._terminal_id
        sse_events: List[Dict[str, Any]] = []
        streaming_parts: List[str] = []
        token_usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "requests": 0,
        }
        final_result: Dict[str, Any] | None = None
        pending_question: Dict[str, Any] | None = None
        current_event = "message"
        data_lines: List[str] = []
        event_count = 0
        should_stop = False

        def _convert_result_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
            response_type = payload.get("response_type", "message")
            return {
                "response_type": response_type,
                "summary": payload.get("summary", ""),
                "steps": payload.get("steps", []),
                "ai_prompt": payload.get("ai_prompt", ""),
                "need_confirm": payload.get("need_confirm", response_type != "message"),
                "provider": payload.get("provider", ""),
                "source": payload.get("source", ""),
                "aliases": payload.get("aliases", {}),
            }

        def _consume_event(event_type: str, payload: Dict[str, Any]) -> None:
            nonlocal session_id, conversation_id, terminal_id, final_result
            nonlocal pending_question, should_stop, event_count, token_usage

            sse_events.append({"event_type": event_type, "payload": payload})

            if event_type == "session_created":
                session_id = payload.get("session_id", session_id)
                conversation_id = payload.get("conversation_id", conversation_id)
                terminal_id = payload.get("terminal_id", terminal_id)
                return

            event_count += 1

            if event_type == "streaming_text":
                text_delta = payload.get("text_delta", "")
                if text_delta:
                    streaming_parts.append(text_delta)
                return

            if event_type == "question":
                pending_question = payload
                final_result = {
                    "response_type": "question",
                    "summary": payload.get("question", ""),
                    "steps": [],
                    "need_confirm": False,
                }
                if allow_question_break:
                    should_stop = True
                return

            if event_type == "result":
                token_usage = payload.get("usage", token_usage) or token_usage
                final_result = _convert_result_payload(payload)
                should_stop = True
                return

            if event_type == "error":
                token_usage = payload.get("usage", token_usage) or token_usage
                final_result = {
                    "response_type": "error",
                    "summary": f"Agent SSE 错误: {payload.get('message', 'unknown error')}",
                    "steps": [],
                    "need_confirm": False,
                    "error_code": payload.get("code", ""),
                }
                should_stop = True

        async def _flush_event() -> None:
            nonlocal current_event, data_lines
            if not data_lines:
                current_event = "message"
                return
            data_str = "\n".join(data_lines).strip()
            data_lines = []
            if not data_str or data_str == "[DONE]":
                current_event = "message"
                return
            try:
                payload = json.loads(data_str)
            except json.JSONDecodeError:
                payload = {"raw": data_str}
            _consume_event(current_event, payload)
            current_event = "message"

        async for raw_line in response.aiter_lines():
            line = raw_line.rstrip("\n")
            if line.startswith(":"):
                continue
            if line == "":
                await _flush_event()
                if should_stop:
                    break
                continue
            if line.startswith("event:"):
                current_event = line[6:].strip() or "message"
                continue
            if line.startswith("data:"):
                data_lines.append(line[5:].strip())

        if data_lines and not should_stop:
            await _flush_event()

        if final_result is None:
            final_result = {
                "response_type": "error",
                "summary": "SSE 流结束但未收到最终结果",
                "steps": [],
                "need_confirm": False,
            }

        self._terminal_id = terminal_id or self._terminal_id
        self._conversation_id = conversation_id or self._conversation_id
        self._session_id = session_id or self._session_id
        self._pending_question_id = (
            pending_question.get("question_id", "") if pending_question else ""
        )
        self._stream_offset = initial_offset + event_count

        return {
            "agent_result": final_result,
            "sse_events": sse_events,
            "token_usage": token_usage,
            "streaming_text": "".join(streaming_parts),
            "pending_question": pending_question,
            "session_id": self._session_id,
            "conversation_id": self._conversation_id,
            "terminal_id": self._terminal_id,
            "stream_offset": self._stream_offset,
        }

    async def get_or_create_device(self) -> str:
        """获取或创建测试设备（需要 Agent WS 连接）。

        Returns:
            device_id，或空字符串
        """
        client = await self._get_client()
        headers = await self.get_auth_headers()

        # 查询已有设备
        resp = await client.get("/api/runtime/devices", headers=headers)
        if resp.status_code == 200:
            devices = resp.json().get("devices", [])
            online_devices = [
                device for device in devices
                if device.get("agent_online") is True
            ]
            if online_devices:
                self._device_id = online_devices[0].get("device_id", "")
                if self._device_id:
                    logger.info(
                        "[integration] 使用在线设备: %s", self._device_id,
                    )
                    return self._device_id

        logger.warning("[integration] 无在线设备（Agent WS 未连接或仍未完成注册）")
        return ""

    async def list_terminals(self, device_id: str) -> List[Dict[str, Any]]:
        """列出设备的终端。"""
        client = await self._get_client()
        headers = await self.get_auth_headers()

        resp = await client.get(
            f"/api/runtime/devices/{device_id}/terminals",
            headers=headers,
        )
        if resp.status_code == 200:
            return resp.json().get("terminals", [])
        return []

    async def cleanup_eval_terminals(self, device_id: str) -> List[str]:
        """清理当前 eval 创建的 terminal，避免遗留状态污染后续 task/run。"""
        closed_terminal_ids: List[str] = []
        terminals = await self.list_terminals(device_id)
        for terminal in terminals:
            terminal_id = str(terminal.get("terminal_id", "")).strip()
            title = str(terminal.get("title", "")).strip()
            status = str(terminal.get("status", "")).strip()
            if status == "closed":
                continue
            if not (
                terminal_id.startswith("eval-term-")
                or title == "eval 集成测试终端"
            ):
                continue
            result = await self.close_terminal(device_id, terminal_id)
            if not result.get("error"):
                closed_terminal_ids.append(terminal_id)
        return closed_terminal_ids

    async def create_terminal(
        self, device_id: str, terminal_id: str = "",
    ) -> Dict[str, Any]:
        """创建终端。"""
        client = await self._get_client()
        headers = await self.get_auth_headers()

        generated_terminal_id = terminal_id.strip()
        for attempt in range(2):
            effective_terminal_id = (
                generated_terminal_id
                or f"eval-term-{uuid4().hex[:12]}"
            )
            payload = {
                "terminal_id": effective_terminal_id,
                "title": "eval 集成测试终端",
                "command": "/bin/bash",
                "cwd": "/tmp",
            }
            resp = await client.post(
                f"/api/runtime/devices/{device_id}/terminals",
                json=payload,
                headers=headers,
            )

            if resp.status_code in (200, 201):
                terminal = resp.json()
                self._device_id = device_id
                self._terminal_id = terminal.get("terminal_id", effective_terminal_id)
                return terminal

            if resp.status_code == 409 and attempt == 0:
                closed = await self.cleanup_eval_terminals(device_id)
                logger.warning(
                    "[integration] 创建 terminal 冲突，已清理 %d 个遗留 eval terminal 后重试: %s",
                    len(closed),
                    resp.text[:200],
                )
                generated_terminal_id = ""
                continue

            return {
                "error": f"创建终端失败: {resp.status_code} {resp.text[:500]}",
                "status": resp.status_code,
            }

        return {"error": "创建终端失败: 未知冲突", "status": 409}

    async def close_terminal(self, device_id: str, terminal_id: str) -> Dict[str, Any]:
        """关闭终端，避免 task/trial 污染后续 integration eval。"""
        client = await self._get_client()
        headers = await self.get_auth_headers()

        resp = await client.delete(
            f"/api/runtime/devices/{device_id}/terminals/{terminal_id}",
            headers=headers,
        )
        if resp.status_code == 200:
            return resp.json()
        return {"error": f"关闭终端失败: {resp.status_code} {resp.text[:500]}", "status": resp.status_code}

    async def close_current_terminal(self, device_id: str = "") -> Dict[str, Any]:
        """关闭当前 integration task 使用的 terminal，并清空 runtime 状态。"""
        effective_device_id = device_id or self._device_id
        effective_terminal_id = self._terminal_id
        if not effective_device_id or not effective_terminal_id:
            self._reset_runtime_state()
            return {"status": "noop"}
        try:
            result = await self.close_terminal(effective_device_id, effective_terminal_id)
            return result
        finally:
            self._reset_runtime_state()

    def _error_bundle(self, summary: str, *, terminal_created: bool = False) -> Dict[str, Any]:
        return {
            "agent_result": {
                "response_type": "error",
                "summary": summary,
                "steps": [],
                "need_confirm": False,
            },
            "sse_events": [],
            "token_usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "requests": 0,
            },
            "streaming_text": "",
            "pending_question": None,
            "session_id": self._session_id,
            "conversation_id": self._conversation_id,
            "terminal_id": self._terminal_id,
            "stream_offset": self._stream_offset,
            "terminal_created": terminal_created,
        }


# ── 集成测试 Harness ────────────────────────────────────────────────────


async def run_integration_task(
    task_def: Any,
    eval_client: IntegrationEvalClient,
    device_id: str = "",
    terminal_id: str = "",
) -> Dict[str, Any]:
    """执行单个 eval task 的集成测试。

    与 unit mode 的 _execute_single_trial 对齐，
    但通过真实 HTTP API 调用而非直接调 LLM。

    Args:
        task_def: EvalTaskDef 实例
        eval_client: 集成测试 HTTP 客户端
        device_id: 设备 ID
        terminal_id: 终端 ID

    Returns:
        {
            "agent_result": dict,
            "duration_ms": int,
            "transcript": list,
        }
    """
    start_time = time.monotonic()
    transcript: List[Dict[str, Any]] = []
    turns = getattr(task_def, "turns", None) or [{"intent": task_def.input.intent}]
    task_conversation_id = f"eval-{task_def.id}-{int(time.time())}"
    total_token_usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "requests": 0,
    }
    all_sse_events: List[Dict[str, Any]] = []
    streaming_text_parts: List[str] = []
    final_agent_result: Dict[str, Any] = {
        "response_type": "error",
        "summary": "integration task 未执行",
        "steps": [],
        "need_confirm": False,
    }
    runtime_snapshot: Dict[str, Any] = {}
    close_created_terminal = not terminal_id

    eval_client._reset_runtime_state(preserve_terminal=bool(terminal_id))
    if terminal_id:
        eval_client._terminal_id = terminal_id
        eval_client._device_id = device_id

    try:
        for turn_index, turn in enumerate(turns):
            if not isinstance(turn, dict):
                raise RuntimeError(f"turns[{turn_index}] 必须为 object")

            user_content = str(turn.get("answer") if turn.get("answer") is not None else turn.get("intent", "")).strip()
            transcript.append({
                "role": "user",
                "content": user_content,
                "mode": "integration",
                "turn_index": turn_index,
            })

            turn_result = await eval_client.execute_turn(
                device_id=device_id,
                turn=turn,
                terminal_id=terminal_id if turn_index == 0 else "",
                conversation_id=task_conversation_id if turn_index == 0 else "",
            )

            all_sse_events.extend(turn_result.get("sse_events", []))
            if turn_result.get("streaming_text"):
                streaming_text_parts.append(turn_result["streaming_text"])
            for key in total_token_usage:
                total_token_usage[key] += int(turn_result.get("token_usage", {}).get(key, 0) or 0)

            final_agent_result = turn_result["agent_result"]
            runtime_snapshot = eval_client.runtime_state()

            transcript.append({
                "role": "assistant",
                "agent_result": turn_result["agent_result"],
                "sse_events": turn_result.get("sse_events", []),
                "token_usage": turn_result.get("token_usage", {}),
                "streaming_text": turn_result.get("streaming_text", ""),
                "pending_question": turn_result.get("pending_question"),
                "mode": "integration",
                "turn_index": turn_index,
            })

            if (
                turn_result.get("pending_question")
                and turn_index == len(turns) - 1
            ):
                break
    finally:
        if close_created_terminal:
            await eval_client.close_current_terminal(device_id)

    duration_ms = int((time.monotonic() - start_time) * 1000)
    enriched_agent_result = dict(final_agent_result)
    enriched_agent_result["sse_events"] = all_sse_events
    enriched_agent_result["token_usage"] = total_token_usage
    enriched_agent_result["streaming_text"] = "".join(streaming_text_parts)
    enriched_agent_result["session_id"] = runtime_snapshot.get("session_id", "")
    enriched_agent_result["conversation_id"] = runtime_snapshot.get("conversation_id", "")
    enriched_agent_result["terminal_id"] = runtime_snapshot.get("terminal_id", terminal_id)
    enriched_agent_result["pending_question_id"] = runtime_snapshot.get("pending_question_id", "")

    transcript.append({
        "role": "final_result",
        "agent_result": enriched_agent_result,
        "duration_ms": duration_ms,
        "mode": "integration",
    })

    return {
        "agent_result": enriched_agent_result,
        "duration_ms": duration_ms,
        "transcript": transcript,
        "token_usage": total_token_usage,
        "sse_events": all_sse_events,
    }

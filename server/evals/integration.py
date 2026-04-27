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
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────

DEFAULT_BASE_URL = "http://localhost:8880"
DEFAULT_HEALTH_PATH = "/health"
DEFAULT_HEALTH_TIMEOUT = 90  # 秒
DEFAULT_HEALTH_INTERVAL = 2  # 秒

# eval 测试用户前缀
EVAL_TEST_USER_PREFIX = "eval_test_"
EVAL_TEST_PASSWORD = "EvalTest123!"


# ── Docker 构建/部署 ─────────────────────────────────────────────────────


class DockerBuildError(Exception):
    """Docker 构建或部署失败"""


class HealthCheckTimeout(Exception):
    """健康检查超时"""


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

        cmd = [
            "docker", "compose",
            "-f", str(self.compose_file),
        ]

        # 如果有 .env 文件
        if self.env_file.exists():
            cmd.extend(["--env-file", str(self.env_file)])

        cmd.extend(["up", "-d", "--wait-timeout", "60"])

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
        if not self._deployed:
            return

        logger.info("[integration] 停止 docker compose 服务 ...")

        cmd = [
            "docker", "compose",
            "-f", str(self.compose_file),
        ]

        if self.env_file.exists():
            cmd.extend(["--env-file", str(self.env_file)])

        cmd.append("down")

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
        client = await self._get_client()

        ts = int(time.time())
        username = f"{self.test_user_prefix}{ts}"

        # 注册
        resp = await client.post(
            "/api/register",
            json={"username": username, "password": self.test_password},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"注册测试用户失败: {resp.status_code} {resp.text}")

        body = resp.json()
        self._token = body.get("token", "")
        self._user_id = body.get("user_id", "")

        if not self._token:
            raise RuntimeError("注册响应中无 token")

        logger.info(
            "[integration] 测试用户已注册: %s (user_id=%s)",
            username, self._user_id,
        )

    async def get_auth_headers(self) -> Dict[str, str]:
        """获取认证头。"""
        return {"Authorization": f"Bearer {self._token}"}

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
            return await self._call_terminal_agent(
                client, headers, device_id, terminal_id, task_intent,
            )

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

    async def _call_terminal_agent(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        device_id: str,
        terminal_id: str,
        task_intent: str,
    ) -> Dict[str, Any]:
        """通过 Terminal Agent SSE run API 调用。"""
        url = (
            f"/api/runtime/devices/{device_id}/terminals/{terminal_id}"
            f"/assistant/agent/run"
        )

        payload = {
            "message": task_intent,
            "message_id": f"eval-msg-{int(time.time())}",
        }

        try:
            async with client.stream(
                "POST", url, json=payload, headers=headers, timeout=120.0,
            ) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    return {
                        "response_type": "error",
                        "summary": f"Agent API 返回 {response.status_code}: {body.decode()[:500]}",
                        "steps": [],
                        "need_confirm": False,
                    }

                # 读取 SSE 流，收集最终结果
                return await self._parse_sse_response(response)

        except httpx.TimeoutException:
            return {
                "response_type": "error",
                "summary": "Agent API 超时（120s）",
                "steps": [],
                "need_confirm": False,
            }
        except httpx.ConnectError as e:
            return {
                "response_type": "error",
                "summary": f"连接 Agent API 失败: {e}",
                "steps": [],
                "need_confirm": False,
            }

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
        self, response: httpx.Response,
    ) -> Dict[str, Any]:
        """解析 SSE 流式响应，提取最终结果。"""
        final_result: Dict[str, Any] | None = None

        async for line in response.aiter_lines():
            line = line.strip()
            if not line or not line.startswith("data:"):
                continue

            data_str = line[5:].strip()
            if not data_str or data_str == "[DONE]":
                continue

            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            chunk_type = chunk.get("type", "")

            if chunk_type == "result":
                # Agent 最终结果
                result_payload = chunk.get("result", {})
                # 转换为标准 agent_result 格式
                response_type = result_payload.get("response_type", "message")
                final_result = {
                    "response_type": response_type,
                    "summary": result_payload.get("summary", ""),
                    "steps": result_payload.get("steps", []),
                    "ai_prompt": result_payload.get("ai_prompt", ""),
                    "need_confirm": result_payload.get("need_confirm", response_type != "message"),
                }
                break

            elif chunk_type == "error":
                reason = chunk.get("reason", "unknown error")
                final_result = {
                    "response_type": "error",
                    "summary": f"Agent SSE 错误: {reason}",
                    "steps": [],
                    "need_confirm": False,
                }
                break

        if final_result is None:
            final_result = {
                "response_type": "error",
                "summary": "SSE 流结束但未收到最终结果",
                "steps": [],
                "need_confirm": False,
            }

        return final_result

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
            if devices:
                self._device_id = devices[0].get("device_id", "")
                if self._device_id:
                    logger.info(
                        "[integration] 使用已有设备: %s", self._device_id,
                    )
                    return self._device_id

        logger.warning("[integration] 无可用设备（Agent WS 未连接）")
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

    async def create_terminal(
        self, device_id: str, terminal_id: str = "",
    ) -> Dict[str, Any]:
        """创建终端。"""
        client = await self._get_client()
        headers = await self.get_auth_headers()

        if not terminal_id:
            terminal_id = f"eval-term-{int(time.time())}"

        resp = await client.post(
            f"/api/runtime/devices/{device_id}/terminals",
            json={
                "terminal_id": terminal_id,
                "title": "eval 集成测试终端",
                "command": "/bin/bash",
                "cwd": "/tmp",
            },
            headers=headers,
        )

        if resp.status_code in (200, 201):
            return resp.json()
        return {"error": f"创建终端失败: {resp.status_code}", "status": resp.status_code}


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

    task_intent = task_def.input.intent
    conversation_id = f"eval-{task_def.id}-{int(time.time())}"

    # 记录请求
    transcript.append({
        "role": "user",
        "content": task_intent,
        "mode": "integration",
    })

    # 调用真实 API
    agent_result = await eval_client.call_agent_api(
        task_intent=task_intent,
        device_id=device_id,
        terminal_id=terminal_id,
        conversation_id=conversation_id,
    )

    duration_ms = int((time.monotonic() - start_time) * 1000)

    # 记录响应
    transcript.append({
        "role": "final_result",
        "agent_result": agent_result,
        "duration_ms": duration_ms,
        "mode": "integration",
    })

    return {
        "agent_result": agent_result,
        "duration_ms": duration_ms,
        "transcript": transcript,
    }

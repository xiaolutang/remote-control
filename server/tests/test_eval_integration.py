"""
S127: Eval Integration Runner 测试

覆盖:
- IntegrationRunner 构建/部署流程（mock subprocess）
- IntegrationRunner 健康检查
- IntegrationRunner tear down
- IntegrationEvalClient 注册/认证
- IntegrationEvalClient Agent API 调用
- IntegrationEvalClient SSE 解析
- run_integration_task 完整流程
- CLI --mode integration 参数解析
- Docker 构建失败 graceful 报错
- 健康检查超时 graceful 报错
"""
import json
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from pathlib import Path

from evals.integration import (
    IntegrationRunner,
    IntegrationEvalClient,
    DockerBuildError,
    HealthCheckTimeout,
    run_integration_task,
    DEFAULT_BASE_URL,
    EVAL_TEST_USER_PREFIX,
)
from evals.models import (
    EvalTaskDef,
    EvalTaskInput,
    EvalTaskExpected,
)


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def sample_task():
    """创建一个示例 eval task"""
    return EvalTaskDef(
        id="test_integration_001",
        category="command_generation",
        description="测试集成 task",
        input=EvalTaskInput(
            intent="列出当前目录文件",
            context={},
        ),
        expected=EvalTaskExpected(
            response_type=["message", "command"],
            steps_contain=["ls"],
        ),
        graders=["exact_match"],
    )


@pytest.fixture
def runner(tmp_path):
    """创建 IntegrationRunner 实例（跳过构建）"""
    return IntegrationRunner(
        project_root=tmp_path,
        skip_build=True,
        base_url="http://localhost:8880",
        health_timeout=5,
        health_interval=0.1,
    )


@pytest.fixture
def mock_client():
    """创建 IntegrationEvalClient 实例"""
    return IntegrationEvalClient(
        base_url="http://localhost:8880",
    )


# ── IntegrationRunner 测试 ──────────────────────────────────────────────


class TestIntegrationRunner:
    """IntegrationRunner 单元测试"""

    def test_init_default(self, tmp_path):
        """测试默认初始化"""
        r = IntegrationRunner(project_root=tmp_path)
        assert r.base_url == "http://localhost:8880"
        assert r.skip_build is False
        assert r.health_timeout == 90

    def test_init_custom(self, tmp_path):
        """测试自定义参数初始化"""
        r = IntegrationRunner(
            project_root=tmp_path,
            base_url="http://custom:9999",
            health_timeout=30,
            skip_build=True,
        )
        assert r.base_url == "http://custom:9999"
        assert r.skip_build is True
        assert r.health_timeout == 30

    def test_context_manager(self, runner):
        """测试上下文管理器"""
        with runner as r:
            assert r is runner
        # exit 后应调用 tear_down（即使没部署也不会报错）

    def test_build_missing_script(self, tmp_path):
        """测试构建脚本缺失时 graceful 报错"""
        r = IntegrationRunner(project_root=tmp_path, skip_build=False)
        with pytest.raises(DockerBuildError, match="构建脚本不存在"):
            r.build_and_deploy()

    @patch("evals.integration.subprocess.run")
    def test_build_failure(self, mock_run, tmp_path):
        """测试 Docker 构建失败时 graceful 报错"""
        # 创建 build.sh 使其存在
        deploy_dir = tmp_path / "deploy"
        deploy_dir.mkdir()
        (deploy_dir / "build.sh").write_text("#!/bin/bash\necho build")
        (deploy_dir / "docker-compose.yml").write_text("services: {}")

        mock_run.return_value = MagicMock(
            returncode=1,
            stderr="Build failed: Dockerfile not found",
        )

        r = IntegrationRunner(project_root=tmp_path, skip_build=False)
        with pytest.raises(DockerBuildError, match="Docker 构建失败"):
            r.build_and_deploy()

    @patch("evals.integration.subprocess.run")
    def test_build_success(self, mock_run, tmp_path):
        """测试 Docker 构建成功流程"""
        deploy_dir = tmp_path / "deploy"
        deploy_dir.mkdir()
        (deploy_dir / "build.sh").write_text("#!/bin/bash\necho build")
        (deploy_dir / "docker-compose.yml").write_text("services: {}")
        (tmp_path / ".env").write_text("JWT_SECRET=test")

        mock_run.return_value = MagicMock(returncode=0, stderr="")

        r = IntegrationRunner(project_root=tmp_path, skip_build=False)
        r.build_and_deploy()
        assert r._deployed is True

    @patch("evals.integration.subprocess.run")
    def test_deploy_failure(self, mock_run, tmp_path):
        """测试 docker compose up 失败时 graceful 报错"""
        deploy_dir = tmp_path / "deploy"
        deploy_dir.mkdir()
        (deploy_dir / "build.sh").write_text("#!/bin/bash\necho build")
        (deploy_dir / "docker-compose.yml").write_text("services: {}")

        # 第一次调用（build）成功，第二次调用（deploy）失败
        mock_run.side_effect = [
            MagicMock(returncode=0, stderr=""),
            MagicMock(returncode=1, stderr="Container startup failed"),
        ]

        r = IntegrationRunner(project_root=tmp_path, skip_build=False)
        with pytest.raises(DockerBuildError, match="docker compose up 失败"):
            r.build_and_deploy()

    @patch("evals.integration.httpx.get")
    def test_wait_for_healthy_success(self, mock_get, runner):
        """测试健康检查成功"""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"status": "ok"},
        )
        assert runner.wait_for_healthy() is True

    @patch("evals.integration.time.monotonic")
    @patch("evals.integration.httpx.get")
    @patch("evals.integration.time.sleep")
    def test_wait_for_healthy_timeout(self, mock_sleep, mock_get, mock_monotonic, runner):
        """测试健康检查超时"""
        import httpx as _httpx
        mock_get.side_effect = _httpx.ConnectError("Connection refused")
        # 模拟时间流逝：start=0, 之后超时
        mock_monotonic.side_effect = [0.0, 0.0, 2.0]  # start, first check, second check > timeout
        with pytest.raises(HealthCheckTimeout, match="服务未在"):
            runner.wait_for_healthy(timeout=1)

    @patch("evals.integration.subprocess.run")
    def test_tear_down(self, mock_run, runner):
        """测试 tear down"""
        runner._deployed = True
        runner.tear_down()
        mock_run.assert_called_once()
        assert runner._deployed is False

    def test_tear_down_not_deployed(self, runner):
        """测试未部署时 tear down 不报错"""
        runner.tear_down()
        assert runner._deployed is False


# ── IntegrationEvalClient 测试 ──────────────────────────────────────────


class TestIntegrationEvalClient:

    @pytest.mark.asyncio
    async def test_setup_register(self, mock_client):
        """测试注册测试用户"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "token": "test.jwt.token",
            "user_id": "user123",
        }

        mock_http_client = AsyncMock()
        mock_http_client.post.return_value = mock_response
        mock_http_client.is_closed = False
        mock_client._http_client = mock_http_client

        await mock_client.setup()
        assert mock_client._token == "test.jwt.token"
        assert mock_client._user_id == "user123"

    @pytest.mark.asyncio
    async def test_setup_register_failure(self, mock_client):
        """测试注册失败"""
        mock_response = MagicMock()
        mock_response.status_code = 409
        mock_response.text = "User already exists"

        mock_http_client = AsyncMock()
        mock_http_client.post.return_value = mock_response
        mock_http_client.is_closed = False
        mock_client._http_client = mock_http_client

        with pytest.raises(RuntimeError, match="注册测试用户失败"):
            await mock_client.setup()

    @pytest.mark.asyncio
    async def test_call_agent_api_no_device(self, mock_client):
        """测试无设备时返回 error"""
        result = await mock_client.call_agent_api(
            task_intent="测试意图",
        )
        assert result["response_type"] == "error"
        assert "device_id" in result["summary"]

    @pytest.mark.asyncio
    async def test_get_auth_headers(self, mock_client):
        """测试获取认证头"""
        mock_client._token = "test.token"
        headers = await mock_client.get_auth_headers()
        assert headers["Authorization"] == "Bearer test.token"

    @pytest.mark.asyncio
    async def test_get_or_create_device_success(self, mock_client):
        """测试获取设备成功"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "devices": [{"device_id": "dev123", "agent_online": True}],
        }

        mock_http_client = AsyncMock()
        mock_http_client.get.return_value = mock_response
        mock_http_client.is_closed = False
        mock_client._http_client = mock_http_client
        mock_client._token = "test.token"

        device_id = await mock_client.get_or_create_device()
        assert device_id == "dev123"

    @pytest.mark.asyncio
    async def test_get_or_create_device_empty(self, mock_client):
        """测试无设备时返回空字符串"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"devices": []}

        mock_http_client = AsyncMock()
        mock_http_client.get.return_value = mock_response
        mock_http_client.is_closed = False
        mock_client._http_client = mock_http_client
        mock_client._token = "test.token"

        device_id = await mock_client.get_or_create_device()
        assert device_id == ""

    @pytest.mark.asyncio
    async def test_call_assistant_plan_success(self, mock_client):
        """测试 Assistant Plan API 调用成功"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "command_sequence": {
                "summary": "列出文件",
                "steps": [
                    {"id": "step_1", "label": "ls", "command": "ls -la"},
                ],
            },
        }

        mock_http_client = AsyncMock()
        mock_http_client.post.return_value = mock_response
        mock_http_client.is_closed = False
        mock_client._http_client = mock_http_client
        mock_client._token = "test.token"

        result = await mock_client.call_agent_api(
            task_intent="列出当前目录文件",
            device_id="dev123",
        )
        assert result["response_type"] == "command"
        assert result["summary"] == "列出文件"
        assert len(result["steps"]) == 1

    @pytest.mark.asyncio
    async def test_call_assistant_plan_timeout(self, mock_client):
        """测试 Assistant Plan API 超时"""
        import httpx

        mock_http_client = AsyncMock()
        mock_http_client.post.side_effect = httpx.TimeoutException("timeout")
        mock_http_client.is_closed = False
        mock_client._http_client = mock_http_client
        mock_client._token = "test.token"

        result = await mock_client.call_agent_api(
            task_intent="列出当前目录文件",
            device_id="dev123",
        )
        assert result["response_type"] == "error"
        assert "超时" in result["summary"]

    @pytest.mark.asyncio
    async def test_close(self, mock_client):
        """测试关闭客户端"""
        mock_http_client = AsyncMock()
        mock_http_client.is_closed = False
        mock_http_client.aclose = AsyncMock()
        mock_client._http_client = mock_http_client

        await mock_client.close()
        mock_http_client.aclose.assert_called_once()


# ── SSE 解析测试 ────────────────────────────────────────────────────────


class TestSSEParsing:
    """SSE 响应解析测试"""

    @pytest.mark.asyncio
    async def test_parse_sse_with_result(self, mock_client):
        """测试解析含 result 的 SSE 流"""
        # 模拟 SSE 流
        sse_lines = [
            'data: {"type": "thinking", "content": "思考中..."}',
            'data: {"type": "result", "result": {"response_type": "message", "summary": "完成", "steps": []}}',
        ]

        mock_response = MagicMock()

        async def aiter_lines():
            for line in sse_lines:
                yield line

        mock_response.aiter_lines = aiter_lines
        mock_response.status_code = 200

        result = await mock_client._parse_sse_response(mock_response)
        assert result["response_type"] == "message"
        assert result["summary"] == "完成"

    @pytest.mark.asyncio
    async def test_parse_sse_with_error(self, mock_client):
        """测试解析含 error 的 SSE 流"""
        sse_lines = [
            'data: {"type": "error", "reason": "device_offline"}',
        ]

        mock_response = MagicMock()

        async def aiter_lines():
            for line in sse_lines:
                yield line

        mock_response.aiter_lines = aiter_lines

        result = await mock_client._parse_sse_response(mock_response)
        assert result["response_type"] == "error"
        assert "device_offline" in result["summary"]

    @pytest.mark.asyncio
    async def test_parse_sse_no_result(self, mock_client):
        """测试 SSE 流结束但无结果"""
        sse_lines = [
            'data: {"type": "thinking", "content": "思考中..."}',
            'data: [DONE]',
        ]

        mock_response = MagicMock()

        async def aiter_lines():
            for line in sse_lines:
                yield line

        mock_response.aiter_lines = aiter_lines

        result = await mock_client._parse_sse_response(mock_response)
        assert result["response_type"] == "error"
        assert "未收到最终结果" in result["summary"]


# ── run_integration_task 测试 ────────────────────────────────────────────


class TestRunIntegrationTask:

    @pytest.mark.asyncio
    async def test_run_integration_task_success(self, sample_task):
        """测试 run_integration_task 成功执行"""
        mock_client = AsyncMock(spec=IntegrationEvalClient)
        mock_client.call_agent_api.return_value = {
            "response_type": "command",
            "summary": "列出文件",
            "steps": [{"id": "s1", "label": "ls", "command": "ls -la"}],
            "need_confirm": True,
        }

        result = await run_integration_task(
            task_def=sample_task,
            eval_client=mock_client,
            device_id="dev123",
        )

        assert result["agent_result"]["response_type"] == "command"
        assert result["duration_ms"] >= 0
        assert len(result["transcript"]) == 2  # user + final_result

    @pytest.mark.asyncio
    async def test_run_integration_task_error(self, sample_task):
        """测试 run_integration_task API 返回错误"""
        mock_client = AsyncMock(spec=IntegrationEvalClient)
        mock_client.call_agent_api.return_value = {
            "response_type": "error",
            "summary": "连接超时",
            "steps": [],
            "need_confirm": False,
        }

        result = await run_integration_task(
            task_def=sample_task,
            eval_client=mock_client,
        )

        assert result["agent_result"]["response_type"] == "error"


# ── CLI 参数解析测试 ──────────────────────────────────────────────────────


class TestCLIParsing:

    def test_run_mode_unit_default(self):
        """测试 run 默认 mode=unit"""
        from evals.__main__ import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["run", "--tasks", "/tmp/tasks"])
        assert args.mode == "unit"

    def test_run_mode_integration(self):
        """测试 run --mode integration"""
        from evals.__main__ import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["run", "--mode", "integration", "--tasks", "/tmp/tasks"])
        assert args.mode == "integration"

    def test_run_integration_base_url(self):
        """测试 run --base-url 参数"""
        from evals.__main__ import _build_parser
        parser = _build_parser()
        args = parser.parse_args([
            "run", "--mode", "integration",
            "--base-url", "http://custom:9999",
            "--tasks", "/tmp/tasks",
        ])
        assert args.base_url == "http://custom:9999"

    def test_run_integration_skip_build(self):
        """测试 run --skip-build 参数"""
        from evals.__main__ import _build_parser
        parser = _build_parser()
        args = parser.parse_args([
            "run", "--mode", "integration",
            "--skip-build",
            "--tasks", "/tmp/tasks",
        ])
        assert args.skip_build is True

    def test_run_integration_health_timeout(self):
        """测试 run --health-timeout 参数"""
        from evals.__main__ import _build_parser
        parser = _build_parser()
        args = parser.parse_args([
            "run", "--mode", "integration",
            "--health-timeout", "30",
            "--tasks", "/tmp/tasks",
        ])
        assert args.health_timeout == 30

    def test_regression_mode_unit_default(self):
        """测试 regression 默认 mode=unit"""
        from evals.__main__ import _build_parser
        parser = _build_parser()
        args = parser.parse_args([
            "regression", "--baseline", "abc123", "--tasks", "/tmp/tasks",
        ])
        assert args.mode == "unit"

    def test_regression_mode_integration(self):
        """测试 regression --mode integration"""
        from evals.__main__ import _build_parser
        parser = _build_parser()
        args = parser.parse_args([
            "regression", "--mode", "integration",
            "--baseline", "abc123", "--tasks", "/tmp/tasks",
        ])
        assert args.mode == "integration"

    def test_invalid_mode(self):
        """测试无效 mode 参数"""
        from evals.__main__ import _build_parser
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([
                "run", "--mode", "invalid", "--tasks", "/tmp/tasks",
            ])

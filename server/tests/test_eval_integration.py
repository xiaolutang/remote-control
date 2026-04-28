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
import argparse
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
    AgentStartupError,
    run_integration_task,
    DEFAULT_BASE_URL,
    EVAL_TEST_USER_PREFIX,
)
from evals.harness import load_yaml_tasks
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

    def test_start_agent_missing_credentials(self, tmp_path):
        """缺少 Agent 凭据时快速失败。"""
        deploy_dir = tmp_path / "deploy"
        deploy_dir.mkdir()
        (deploy_dir / "docker-compose.yml").write_text("services: {}")
        (tmp_path / ".env").write_text("JWT_SECRET=test\n")

        r = IntegrationRunner(project_root=tmp_path, skip_build=True)
        with pytest.raises(AgentStartupError, match="AGENT_TOKEN 或 AGENT_USERNAME, AGENT_PASSWORD"):
            r.start_agent()

    @patch("evals.integration.subprocess.Popen")
    def test_start_agent_success(self, mock_popen, tmp_path):
        """启动 Agent 时应执行 docker compose run。"""
        deploy_dir = tmp_path / "deploy"
        deploy_dir.mkdir()
        (deploy_dir / "docker-compose.yml").write_text("services: {}")
        (tmp_path / ".env").write_text("AGENT_USERNAME=test\nAGENT_PASSWORD=secret\n")

        proc = MagicMock()
        proc.poll.return_value = None
        mock_popen.return_value = proc

        r = IntegrationRunner(project_root=tmp_path, skip_build=True)
        r.start_agent()

        called_cmd = mock_popen.call_args.args[0]
        assert "docker" in called_cmd[0]
        assert "run" in called_cmd
        assert "agent" in called_cmd
        assert r._process is proc

    @patch("evals.integration.subprocess.Popen")
    def test_start_agent_accepts_explicit_agent_token(self, mock_popen, tmp_path):
        """显式提供 agent token 时不应依赖用户名密码。"""
        deploy_dir = tmp_path / "deploy"
        deploy_dir.mkdir()
        (deploy_dir / "docker-compose.yml").write_text("services: {}")
        (tmp_path / ".env").write_text("JWT_SECRET=test\n")

        proc = MagicMock()
        proc.poll.return_value = None
        mock_popen.return_value = proc

        r = IntegrationRunner(project_root=tmp_path, skip_build=True)
        r.start_agent(agent_token="agent-token-123")

        popen_kwargs = mock_popen.call_args.kwargs
        assert popen_kwargs["env"]["AGENT_TOKEN"] == "agent-token-123"

    @pytest.mark.asyncio
    async def test_wait_agent_online_success(self, runner):
        """轮询到设备后返回 device_id。"""
        runner._process = MagicMock()
        runner._process.poll.return_value = None
        mock_eval_client = AsyncMock()
        mock_eval_client.get_or_create_device = AsyncMock(side_effect=["", "dev123"])

        device_id = await runner.wait_agent_online(mock_eval_client, timeout=1)
        assert device_id == "dev123"

    @pytest.mark.asyncio
    async def test_wait_agent_online_agent_exit(self, runner):
        """Agent 提前退出时应快速报错。"""
        runner._process = MagicMock()
        runner._process.poll.return_value = 1
        runner._process.communicate.return_value = ("", "auth failed")
        mock_eval_client = AsyncMock()

        with pytest.raises(AgentStartupError, match="异常退出"):
            await runner.wait_agent_online(mock_eval_client, timeout=1)

    def test_stop_agent(self, runner):
        """stop_agent 应终止 docker compose run 进程。"""
        proc = MagicMock()
        proc.poll.return_value = None
        runner._process = proc

        runner.stop_agent()

        proc.terminate.assert_called_once()
        proc.wait.assert_called_once_with(timeout=20)
        assert runner._process is None


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
    async def test_provision_agent_access_token(self, mock_client):
        """应为 integration Agent 注册独立用户并返回 token。"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"access_token": "agent.jwt.token"}

        mock_http_client = AsyncMock()
        mock_http_client.post.return_value = mock_response
        mock_http_client.is_closed = False
        mock_client._http_client = mock_http_client

        token = await mock_client.provision_agent_access_token()
        assert token == "agent.jwt.token"

    def test_use_access_token_sets_runtime_auth(self, mock_client):
        """可直接注入运行时 access token。"""
        mock_client.use_access_token("agent.jwt.token", "user-1")
        assert mock_client._token == "agent.jwt.token"
        assert mock_client._user_id == "user-1"

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
    async def test_get_or_create_device_skips_offline_devices(self, mock_client):
        """应优先选择 agent_online=true 的设备，而不是列表中的第一个离线设备。"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "devices": [
                {"device_id": "offline-1", "agent_online": False},
                {"device_id": "online-1", "agent_online": True},
            ],
        }

        mock_http_client = AsyncMock()
        mock_http_client.get.return_value = mock_response
        mock_http_client.is_closed = False
        mock_client._http_client = mock_http_client
        mock_client._token = "test.token"

        device_id = await mock_client.get_or_create_device()
        assert device_id == "online-1"

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

    @pytest.mark.asyncio
    @patch("evals.integration.uuid4")
    async def test_create_terminal_uses_uuid_suffix(self, mock_uuid4, mock_client):
        """未指定 terminal_id 时应生成高唯一性的 eval terminal id。"""
        mock_client._token = "test.token"
        mock_uuid4.return_value = MagicMock(hex="abc123def4567890")

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"terminal_id": "eval-term-abc123def456"}

        mock_http_client = AsyncMock()
        mock_http_client.post.return_value = mock_response
        mock_http_client.is_closed = False
        mock_client._http_client = mock_http_client

        result = await mock_client.create_terminal("dev123")

        assert result["terminal_id"] == "eval-term-abc123def456"
        post_kwargs = mock_http_client.post.call_args.kwargs
        assert post_kwargs["json"]["terminal_id"] == "eval-term-abc123def456"

    @pytest.mark.asyncio
    async def test_create_terminal_retries_once_after_conflict_cleanup(self, mock_client):
        """409 冲突时应清理遗留 eval terminal 并重试一次。"""
        mock_client._token = "test.token"
        mock_client.cleanup_eval_terminals = AsyncMock(return_value=["eval-term-old"])

        conflict_response = MagicMock()
        conflict_response.status_code = 409
        conflict_response.text = "terminal 数量已达上限"

        success_response = MagicMock()
        success_response.status_code = 201
        success_response.json.return_value = {"terminal_id": "eval-term-new"}

        mock_http_client = AsyncMock()
        mock_http_client.post.side_effect = [conflict_response, success_response]
        mock_http_client.is_closed = False
        mock_client._http_client = mock_http_client

        result = await mock_client.create_terminal("dev123")

        assert result["terminal_id"] == "eval-term-new"
        mock_client.cleanup_eval_terminals.assert_awaited_once_with("dev123")
        assert mock_http_client.post.await_count == 2

    @pytest.mark.asyncio
    async def test_create_terminal_then_run_creates_terminal_first(self, mock_client):
        """无 terminal 时应先创建终端，再调用 terminal-bound agent run。"""
        mock_client._token = "test.token"
        mock_client.create_terminal = AsyncMock(return_value={"terminal_id": "term-1"})

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}

        async def aiter_lines():
            yield 'event: session_created'
            yield 'data: {"session_id":"sess-1","conversation_id":"conv-1","terminal_id":"term-1"}'
            yield ''
            yield 'event: result'
            yield 'data: {"response_type":"message","summary":"ok","steps":[],"need_confirm":false,"usage":{"input_tokens":1,"output_tokens":2,"total_tokens":3,"requests":1}}'
            yield ''

        mock_response.aiter_lines = aiter_lines

        stream_cm = AsyncMock()
        stream_cm.__aenter__.return_value = mock_response
        stream_cm.__aexit__.return_value = False

        mock_http_client = MagicMock()
        mock_http_client.stream.return_value = stream_cm
        mock_http_client.is_closed = False
        mock_client._http_client = mock_http_client

        result = await mock_client.create_terminal_then_run(
            device_id="dev123",
            task_intent="你好",
        )

        mock_client.create_terminal.assert_awaited_once_with("dev123")
        stream_kwargs = mock_http_client.stream.call_args.kwargs
        assert stream_kwargs["json"]["intent"] == "你好"
        assert "client_event_id" in stream_kwargs["json"]
        assert result["terminal_created"] is True
        assert result["agent_result"]["summary"] == "ok"

    @pytest.mark.asyncio
    async def test_respond_to_agent_posts_answer_and_resumes_stream(self, mock_client):
        """回复 question 后应 POST respond，再 GET resume 获取后续 SSE。"""
        mock_client._token = "test.token"
        mock_client._device_id = "dev123"
        mock_client._terminal_id = "term-1"
        mock_client._session_id = "sess-1"
        mock_client._pending_question_id = "q-1"
        mock_client._stream_offset = 2

        post_response = MagicMock()
        post_response.status_code = 200

        resume_response = MagicMock()
        resume_response.status_code = 200
        resume_response.headers = {}

        async def aiter_lines():
            yield 'event: result'
            yield 'data: {"response_type":"message","summary":"已收到答案","steps":[],"need_confirm":false,"usage":{"input_tokens":4,"output_tokens":3,"total_tokens":7,"requests":1}}'
            yield ''

        resume_response.aiter_lines = aiter_lines

        stream_cm = AsyncMock()
        stream_cm.__aenter__.return_value = resume_response
        stream_cm.__aexit__.return_value = False

        mock_http_client = MagicMock()
        mock_http_client.post = AsyncMock(return_value=post_response)
        mock_http_client.stream.return_value = stream_cm
        mock_http_client.is_closed = False
        mock_client._http_client = mock_http_client

        result = await mock_client.respond_to_agent(
            device_id="dev123",
            answer="remote-control",
        )

        post_kwargs = mock_http_client.post.call_args.kwargs
        assert post_kwargs["json"]["question_id"] == "q-1"
        stream_kwargs = mock_http_client.stream.call_args.kwargs
        assert stream_kwargs["params"]["after_index"] == 2
        assert result["agent_result"]["summary"] == "已收到答案"


# ── SSE 解析测试 ────────────────────────────────────────────────────────


class TestSSEParsing:
    """SSE 响应解析测试"""

    @pytest.mark.asyncio
    async def test_parse_sse_with_result(self, mock_client):
        """测试解析含 result 的 SSE 流"""
        sse_lines = [
            'event: session_created',
            'data: {"session_id":"sess-1","conversation_id":"conv-1","terminal_id":"term-1"}',
            '',
            'event: streaming_text',
            'data: {"text_delta":"你好"}',
            '',
            'event: result',
            'data: {"response_type":"message","summary":"完成","steps":[],"need_confirm":false,"usage":{"input_tokens":10,"output_tokens":5,"total_tokens":15,"requests":1}}',
            '',
        ]

        mock_response = MagicMock()
        mock_response.headers = {}

        async def aiter_lines():
            for line in sse_lines:
                yield line

        mock_response.aiter_lines = aiter_lines
        mock_response.status_code = 200

        result = await mock_client._parse_sse_response(mock_response)
        assert result["agent_result"]["response_type"] == "message"
        assert result["agent_result"]["summary"] == "完成"
        assert result["token_usage"]["total_tokens"] == 15
        assert result["streaming_text"] == "你好"
        assert result["session_id"] == "sess-1"
        assert result["conversation_id"] == "conv-1"
        assert result["terminal_id"] == "term-1"
        assert len(result["sse_events"]) == 3

    @pytest.mark.asyncio
    async def test_parse_sse_with_error(self, mock_client):
        """测试解析含 error 的 SSE 流"""
        sse_lines = [
            'event: error',
            'data: {"code":"device_offline","message":"device offline"}',
            '',
        ]

        mock_response = MagicMock()
        mock_response.headers = {}

        async def aiter_lines():
            for line in sse_lines:
                yield line

        mock_response.aiter_lines = aiter_lines

        result = await mock_client._parse_sse_response(mock_response)
        assert result["agent_result"]["response_type"] == "error"
        assert "device offline" in result["agent_result"]["summary"]

    @pytest.mark.asyncio
    async def test_parse_sse_no_result(self, mock_client):
        """测试 SSE 流结束但无结果"""
        sse_lines = [
            'event: phase_change',
            'data: {"phase":"THINKING","description":"思考中"}',
            '',
            'data: [DONE]',
        ]

        mock_response = MagicMock()
        mock_response.headers = {}

        async def aiter_lines():
            for line in sse_lines:
                yield line

        mock_response.aiter_lines = aiter_lines

        result = await mock_client._parse_sse_response(mock_response)
        assert result["agent_result"]["response_type"] == "error"
        assert "未收到最终结果" in result["agent_result"]["summary"]

    @pytest.mark.asyncio
    async def test_parse_sse_question_breaks_for_follow_up(self, mock_client):
        """question 事件应提前返回，供后续 respond/resume 使用。"""
        sse_lines = [
            'event: session_created',
            'data: {"session_id":"sess-q","conversation_id":"conv-q","terminal_id":"term-q"}',
            '',
            'event: question',
            'data: {"question_id":"q-1","question":"请选择项目","options":["remote-control"],"multi_select":false}',
            '',
        ]

        mock_response = MagicMock()
        mock_response.headers = {}

        async def aiter_lines():
            for line in sse_lines:
                yield line

        mock_response.aiter_lines = aiter_lines

        result = await mock_client._parse_sse_response(mock_response)
        assert result["agent_result"]["response_type"] == "question"
        assert result["pending_question"]["question_id"] == "q-1"
        assert result["stream_offset"] == 1


# ── run_integration_task 测试 ────────────────────────────────────────────


class TestRunIntegrationTask:

    @pytest.mark.asyncio
    async def test_run_integration_task_success(self, sample_task):
        """测试 run_integration_task 成功执行"""
        mock_client = AsyncMock(spec=IntegrationEvalClient)
        mock_client.execute_turn.side_effect = [{
            "agent_result": {
                "response_type": "command",
                "summary": "列出文件",
                "steps": [{"id": "s1", "label": "ls", "command": "ls -la"}],
                "need_confirm": True,
            },
            "sse_events": [{"event_type": "result", "payload": {"summary": "列出文件"}}],
            "token_usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15, "requests": 1},
            "streaming_text": "",
            "pending_question": None,
        }]
        mock_client.runtime_state.return_value = {
            "device_id": "dev123",
            "terminal_id": "term-1",
            "conversation_id": "conv-1",
            "session_id": "sess-1",
            "pending_question_id": "",
            "stream_offset": 1,
        }
        mock_client.close_current_terminal = AsyncMock()
        mock_client._reset_runtime_state = MagicMock()

        result = await run_integration_task(
            task_def=sample_task,
            eval_client=mock_client,
            device_id="dev123",
        )

        assert result["agent_result"]["response_type"] == "command"
        assert result["agent_result"]["token_usage"]["total_tokens"] == 15
        assert result["agent_result"]["terminal_id"] == "term-1"
        assert result["duration_ms"] >= 0
        assert len(result["transcript"]) == 3  # user + assistant + final_result
        mock_client.close_current_terminal.assert_awaited_once_with("dev123")

    @pytest.mark.asyncio
    async def test_run_integration_task_multi_turn_aggregates_usage(self, sample_task):
        """多轮任务应复用同一 task runtime，并聚合 token_usage / SSE 事件。"""
        sample_task.turns = [
            {"intent": "先分析项目"},
            {"intent": "继续追问上轮发现"},
        ]
        mock_client = AsyncMock(spec=IntegrationEvalClient)
        mock_client.execute_turn.side_effect = [
            {
                "agent_result": {"response_type": "message", "summary": "发现 remote-control", "steps": [], "need_confirm": False},
                "sse_events": [{"event_type": "result", "payload": {"summary": "发现 remote-control"}}],
                "token_usage": {"input_tokens": 10, "output_tokens": 8, "total_tokens": 18, "requests": 1},
                "streaming_text": "发现 remote-control",
                "pending_question": None,
            },
            {
                "agent_result": {"response_type": "message", "summary": "第二轮继续引用 remote-control", "steps": [], "need_confirm": False},
                "sse_events": [{"event_type": "result", "payload": {"summary": "第二轮继续引用 remote-control"}}],
                "token_usage": {"input_tokens": 12, "output_tokens": 6, "total_tokens": 18, "requests": 1},
                "streaming_text": "第二轮继续引用 remote-control",
                "pending_question": None,
            },
        ]
        mock_client.runtime_state.return_value = {
            "device_id": "dev123",
            "terminal_id": "term-2",
            "conversation_id": "conv-2",
            "session_id": "sess-2",
            "pending_question_id": "",
            "stream_offset": 2,
        }
        mock_client.close_current_terminal = AsyncMock()
        mock_client._reset_runtime_state = MagicMock()

        result = await run_integration_task(
            task_def=sample_task,
            eval_client=mock_client,
            device_id="dev123",
        )

        assert result["agent_result"]["response_type"] == "message"
        assert result["agent_result"]["token_usage"]["total_tokens"] == 36
        assert len(result["agent_result"]["sse_events"]) == 2
        assert result["agent_result"]["streaming_text"] == "发现 remote-control第二轮继续引用 remote-control"
        assert len(result["transcript"]) == 5

    @pytest.mark.asyncio
    async def test_run_integration_task_error(self, sample_task):
        """测试 run_integration_task API 返回错误"""
        mock_client = AsyncMock(spec=IntegrationEvalClient)
        mock_client.execute_turn.side_effect = [{
            "agent_result": {
                "response_type": "error",
                "summary": "连接超时",
                "steps": [],
                "need_confirm": False,
            },
            "sse_events": [],
            "token_usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "requests": 0},
            "streaming_text": "",
            "pending_question": None,
        }]
        mock_client.runtime_state.return_value = {
            "device_id": "",
            "terminal_id": "",
            "conversation_id": "",
            "session_id": "",
            "pending_question_id": "",
            "stream_offset": 0,
        }
        mock_client.close_current_terminal = AsyncMock()
        mock_client._reset_runtime_state = MagicMock()

        result = await run_integration_task(
            task_def=sample_task,
            eval_client=mock_client,
        )

        assert result["agent_result"]["response_type"] == "error"


class TestIntegrationTaskLoading:
    def test_load_real_integration_tasks_directory(self):
        """integration/ 目录下的真实 task 应可加载，且 turns[] 保持可访问。"""
        tasks_dir = Path(__file__).resolve().parents[1] / "evals" / "tasks" / "integration"
        tasks = load_yaml_tasks(tasks_dir)

        assert len(tasks) >= 4
        task_ids = {task.id for task in tasks}
        assert "it_001_workspace_probe" in task_ids
        assert "it_002_pwd_command" in task_ids
        assert "it_003_agent_identity" in task_ids
        assert "it_004_multi_turn_memory" in task_ids

        multi_turn = next(task for task in tasks if task.id == "it_004_multi_turn_memory")
        turns = getattr(multi_turn, "turns", [])
        assert len(turns) == 2
        assert turns[1]["intent"] == "我刚才让你记住的短语是什么？请原样回答。"


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


@pytest.mark.asyncio
async def test_cmd_run_integration_starts_and_stops_agent(sample_task, monkeypatch):
    """integration CLI 应显式启动 Agent、等待上线并在结束后停止。"""
    from evals import __main__ as main_mod
    import evals.harness as harness_mod
    import evals.integration as integration_mod

    class FakeDB:
        async def init_db(self):
            return None

        async def save_run(self, run_record):
            self.run_record = run_record

        async def save_task_def(self, task):
            return None

        async def save_trial(self, trial):
            return None

        async def update_run_completion(self, run_id, completed_at, total_tasks, passed_tasks):
            return None

    class FakeHarness:
        def __init__(self, db, num_trials=1):
            self.db = db
            self.num_trials = num_trials

        def _evaluate_trial(self, task, agent_result):
            return True

    fake_db = FakeDB()
    runner = MagicMock()
    runner.wait_agent_online = AsyncMock(return_value="dev123")
    client = MagicMock()
    client.provision_agent_identity = AsyncMock(return_value={
        "access_token": "agent-token-123",
        "user_id": "user-1",
    })
    client.use_access_token = MagicMock()
    client.cleanup_eval_terminals = AsyncMock(return_value=[])
    client.close = AsyncMock()

    monkeypatch.setattr(main_mod, "load_yaml_tasks", lambda _: [sample_task])
    monkeypatch.setattr(main_mod, "EvalDatabase", lambda _: fake_db)
    monkeypatch.setattr(harness_mod, "EvalHarness", FakeHarness)
    monkeypatch.setattr(integration_mod, "IntegrationRunner", lambda **kwargs: runner)
    monkeypatch.setattr(integration_mod, "IntegrationEvalClient", lambda **kwargs: client)
    monkeypatch.setattr(
        integration_mod,
        "run_integration_task",
        AsyncMock(return_value={
            "agent_result": {
                "response_type": "message",
                "summary": "ok",
                "steps": [],
                "need_confirm": False,
            },
            "duration_ms": 12,
            "transcript": [],
        }),
    )

    args = argparse.Namespace(
        tasks="/tmp/tasks",
        trials=1,
        db="/tmp/evals.db",
        base_url="http://localhost:8880",
        skip_build=True,
        health_timeout=5,
    )

    exit_code = await main_mod._cmd_run_integration(args)

    assert exit_code == 0
    runner.build_and_deploy.assert_called_once()
    runner.wait_for_healthy.assert_called_once()
    runner.start_agent.assert_called_once_with(agent_token="agent-token-123")
    runner.wait_agent_online.assert_awaited_once_with(client, timeout=60)
    runner.stop_agent.assert_called()
    runner.tear_down.assert_called_once()
    client.use_access_token.assert_called_once_with("agent-token-123", "user-1")
    client.close.assert_awaited_once()

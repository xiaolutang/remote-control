"""
B101: quality_monitor 测试 — 验证 5 类质量指标计算正确。

使用 mock 数据库（内存 evals.db），构造已知 session 验证指标计算。
不依赖真实 app.db。
"""
import asyncio
import json
import os
import sqlite3
import tempfile

import pytest
import pytest_asyncio

from evals.db import EvalDatabase
from evals.models import QualityMetric
from evals.quality_monitor import (
    ALL_METRIC_NAMES,
    METRIC_ASK_USER_FREQUENCY,
    METRIC_COMMAND_SAFETY_RATE,
    METRIC_RESPONSE_TYPE_ACCURACY,
    METRIC_TOKEN_EFFICIENCY,
    METRIC_TOOL_USAGE_EFFICIENCY,
    SessionEventData,
    batch_extract_metrics,
    compute_all_metrics,
    compute_ask_user_frequency,
    compute_command_safety_rate,
    compute_response_type_accuracy,
    compute_token_efficiency,
    compute_tool_usage_efficiency,
    extract_and_store_metrics,
    extract_session_data,
)


# ── 辅助：构造测试 events ──────────────────────────────────────────────────


def _make_trace_event(tool: str, **extra_payload) -> dict:
    """构造 trace 事件。"""
    payload = {"tool": tool, "input_summary": "test", "output_summary": "ok"}
    payload.update(extra_payload)
    return {"event_type": "trace", "payload": payload}


def _make_question_event(question_id: str = "q_001") -> dict:
    """构造 question 事件。"""
    return {
        "event_type": "question",
        "payload": {
            "question_id": question_id,
            "question": "请确认是否继续？",
            "options": ["是", "否"],
            "multi_select": False,
        },
    }


def _make_answer_event() -> dict:
    """构造 answer 事件。"""
    return {"event_type": "answer", "payload": {"answer": "是"}}


def _make_result_event(
    response_type: str = "command_sequence",
    total_tokens: int = 500,
    **extra_payload,
) -> dict:
    """构造 result 事件。"""
    payload = {
        "response_type": response_type,
        "summary": "test summary",
        "usage": {"total_tokens": total_tokens},
    }
    payload.update(extra_payload)
    return {"event_type": "result", "payload": payload}


def _make_error_event(code: str = "AGENT_ERROR") -> dict:
    """构造 error 事件。"""
    return {"event_type": "error", "payload": {"code": code, "message": "test error"}}


# ── 测试 extract_session_data ───────────────────────────────────────────────


class TestExtractSessionData:
    """测试从 conversation_events 提取聚合数据。"""

    def test_empty_events(self):
        """空事件列表返回默认聚合数据。"""
        data = extract_session_data(
            [],
            session_id="s1",
            user_id="u1",
            device_id="d1",
            intent="install nginx",
        )
        assert data.session_id == "s1"
        assert data.user_id == "u1"
        assert data.device_id == "d1"
        assert data.total_events == 0
        assert data.trace_events == 0
        assert data.has_result is False
        assert data.total_tokens == 0

    def test_basic_session(self):
        """基础 session：1 个 execute_command + 1 个 result。"""
        events = [
            _make_trace_event("execute_command"),
            _make_result_event(response_type="command_sequence", total_tokens=300),
        ]
        data = extract_session_data(events, session_id="s1", intent="install nginx")

        assert data.total_events == 2
        assert data.trace_events == 1
        assert data.execute_command_count == 1
        assert data.has_result is True
        assert data.response_type == "command_sequence"
        assert data.total_tokens == 300

    def test_multi_tool_session(self):
        """多工具 session：execute_command + lookup_knowledge + dynamic_tool。"""
        events = [
            _make_trace_event("execute_command"),
            _make_trace_event("lookup_knowledge"),
            _make_trace_event("call_dynamic_tool:custom_tool"),
            _make_result_event(total_tokens=1000),
        ]
        data = extract_session_data(events, session_id="s2")

        assert data.execute_command_count == 1
        assert data.lookup_knowledge_count == 1
        assert data.dynamic_tool_calls == 1
        assert data.total_events == 4

    def test_ask_user_via_question_event(self):
        """ask_user 通过 question 事件计数。"""
        events = [
            _make_trace_event("execute_command"),
            _make_question_event(),
            _make_answer_event(),
            _make_result_event(),
        ]
        data = extract_session_data(events, session_id="s3")

        assert data.question_events == 1
        assert data.answer_events == 1
        assert data.ask_user_count == 1  # question 事件计为 ask_user

    def test_ask_user_via_trace_event(self):
        """ask_user 通过 trace tool='ask_user' 计数。"""
        events = [
            _make_trace_event("ask_user"),
            _make_result_event(),
        ]
        data = extract_session_data(events, session_id="s4")

        assert data.ask_user_count == 1

    def test_safety_check_detection(self):
        """检测安全检查标记。"""
        events = [
            _make_trace_event(
                "execute_command",
                output_summary="SAFETY_CHECK: rm -rf / -> BLOCKED",
            ),
            _make_trace_event(
                "execute_command",
                output_summary="SAFETY_CHECK: ls -la -> PASSED",
            ),
            _make_result_event(),
        ]
        data = extract_session_data(events, session_id="s5")

        assert data.safety_checked_commands == 2
        assert data.safety_passed_commands == 1  # 一个 BLOCKED，一个 PASSED

    def test_payload_json_string(self):
        """payload 作为 JSON 字符串传入时也能正确解析。"""
        payload = json.dumps({"tool": "execute_command", "input_summary": "ls", "output_summary": "ok"})
        events = [{"event_type": "trace", "payload": payload}]
        data = extract_session_data(events, session_id="s6")

        assert data.execute_command_count == 1

    def test_malformed_payload(self):
        """payload 解析失败时降级为空 dict。"""
        events = [{"event_type": "trace", "payload": "not-json"}]
        data = extract_session_data(events, session_id="s7")

        assert data.total_events == 1
        assert data.execute_command_count == 0


# ── 测试 compute_response_type_accuracy ──────────────────────────────────────


class TestComputeResponseTypeAccuracy:
    """测试 response_type_accuracy 指标计算。"""

    def test_no_result(self):
        """无结果 → 0.0。"""
        data = SessionEventData(session_id="s1", intent="install nginx")
        assert compute_response_type_accuracy(data) == 0.0

    def test_no_response_type(self):
        """有结果但无 response_type → 0.0。"""
        data = SessionEventData(session_id="s1", has_result=True, response_type="", intent="install nginx")
        assert compute_response_type_accuracy(data) == 0.0

    def test_no_intent(self):
        """无意图 → 1.0（无法判定）。"""
        data = SessionEventData(session_id="s1", has_result=True, response_type="command_sequence")
        assert compute_response_type_accuracy(data) == 1.0

    def test_match(self):
        """意图与实际响应类型匹配 → 1.0。"""
        data = SessionEventData(
            session_id="s1",
            has_result=True,
            response_type="command_sequence",
            intent="install nginx",
        )
        assert compute_response_type_accuracy(data) == 1.0

    def test_mismatch(self):
        """意图与实际响应类型不匹配 → 0.0。"""
        data = SessionEventData(
            session_id="s1",
            has_result=True,
            response_type="explanation",
            intent="install nginx",
        )
        assert compute_response_type_accuracy(data) == 0.0

    def test_unknown_intent(self):
        """无法推断预期类型 → 0.8。"""
        data = SessionEventData(
            session_id="s1",
            has_result=True,
            response_type="command_sequence",
            intent="do something weird",
        )
        assert compute_response_type_accuracy(data) == 0.8

    def test_explanation_intent(self):
        """解释类意图匹配。"""
        data = SessionEventData(
            session_id="s1",
            has_result=True,
            response_type="explanation",
            intent="explain what is docker",
        )
        assert compute_response_type_accuracy(data) == 1.0


# ── 测试 compute_tool_usage_efficiency ───────────────────────────────────────


class TestComputeToolUsageEfficiency:
    """测试 tool_usage_efficiency 指标计算。"""

    def test_no_tools_with_result(self):
        """无工具调用但有结果 → 1.0。"""
        data = SessionEventData(session_id="s1", has_result=True)
        assert compute_tool_usage_efficiency(data) == 1.0

    def test_no_tools_no_result(self):
        """无工具调用且无结果 → 0.0。"""
        data = SessionEventData(session_id="s1", has_result=False)
        assert compute_tool_usage_efficiency(data) == 0.0

    def test_one_tool_call(self):
        """1 次工具调用 → 1.0。"""
        data = SessionEventData(session_id="s1", execute_command_count=1, has_result=True)
        assert compute_tool_usage_efficiency(data) == 1.0

    def test_two_tool_calls(self):
        """2 次工具调用 → 0.5。"""
        data = SessionEventData(session_id="s1", execute_command_count=2, has_result=True)
        assert compute_tool_usage_efficiency(data) == 0.5

    def test_dynamic_tool_calls_counted(self):
        """动态工具调用也参与计算。"""
        data = SessionEventData(
            session_id="s1",
            execute_command_count=1,
            dynamic_tool_calls=1,
            has_result=True,
        )
        # 2 次总调用 → 1/2 = 0.5
        assert compute_tool_usage_efficiency(data) == 0.5

    def test_many_tool_calls(self):
        """很多次工具调用 → 很低的效率。"""
        data = SessionEventData(session_id="s1", execute_command_count=10, has_result=True)
        assert compute_tool_usage_efficiency(data) == 0.1


# ── 测试 compute_command_safety_rate ────────────────────────────────────────


class TestComputeCommandSafetyRate:
    """测试 command_safety_rate 指标计算。"""

    def test_no_safety_checks(self):
        """无安全检查记录 → 1.0。"""
        data = SessionEventData(session_id="s1")
        assert compute_command_safety_rate(data) == 1.0

    def test_all_passed(self):
        """全部通过 → 1.0。"""
        data = SessionEventData(
            session_id="s1",
            safety_checked_commands=3,
            safety_passed_commands=3,
        )
        assert compute_command_safety_rate(data) == 1.0

    def test_half_blocked(self):
        """一半被阻止 → 0.5。"""
        data = SessionEventData(
            session_id="s1",
            safety_checked_commands=4,
            safety_passed_commands=2,
        )
        assert compute_command_safety_rate(data) == 0.5

    def test_all_blocked(self):
        """全部被阻止 → 0.0。"""
        data = SessionEventData(
            session_id="s1",
            safety_checked_commands=3,
            safety_passed_commands=0,
        )
        assert compute_command_safety_rate(data) == 0.0


# ── 测试 compute_ask_user_frequency ─────────────────────────────────────────


class TestComputeAskUserFrequency:
    """测试 ask_user_frequency 指标计算。"""

    def test_no_events(self):
        """无事件 → 0.0。"""
        data = SessionEventData(session_id="s1")
        assert compute_ask_user_frequency(data) == 0.0

    def test_no_ask_user(self):
        """无 ask_user → 0.0。"""
        data = SessionEventData(session_id="s1", total_events=5, ask_user_count=0)
        assert compute_ask_user_frequency(data) == 0.0

    def test_one_ask_in_five_events(self):
        """5 个事件中 1 次 ask_user → 0.2。"""
        data = SessionEventData(session_id="s1", total_events=5, ask_user_count=1)
        assert compute_ask_user_frequency(data) == 0.2

    def test_all_ask_user(self):
        """全部都是 ask_user → 1.0。"""
        data = SessionEventData(session_id="s1", total_events=3, ask_user_count=3)
        assert compute_ask_user_frequency(data) == 1.0


# ── 测试 compute_token_efficiency ──────────────────────────────────────────


class TestComputeTokenEfficiency:
    """测试 token_efficiency 指标计算。"""

    def test_no_tokens(self):
        """无 token 数据 → 0.0。"""
        data = SessionEventData(session_id="s1")
        assert compute_token_efficiency(data) == 0.0

    def test_easy_task_efficient(self):
        """简单任务（1 轮），300 tokens → 500/300 = 1.0 (capped)。"""
        data = SessionEventData(
            session_id="s1",
            total_tokens=300,
            trace_events=1,
        )
        result = compute_token_efficiency(data)
        assert result == 1.0  # capped at 1.0

    def test_medium_task_efficient(self):
        """中等任务（5 轮），1000 tokens → 1500/1000 = 1.0 (capped)。"""
        data = SessionEventData(
            session_id="s1",
            total_tokens=1000,
            trace_events=5,
        )
        result = compute_token_efficiency(data)
        assert result == 1.0

    def test_easy_task_inefficient(self):
        """简单任务（1 轮），1000 tokens → 500/1000 = 0.5。"""
        data = SessionEventData(
            session_id="s1",
            total_tokens=1000,
            trace_events=1,
        )
        result = compute_token_efficiency(data)
        assert result == 0.5

    def test_hard_task(self):
        """困难任务（10 轮），4000 tokens → 3000/4000 = 0.75。"""
        data = SessionEventData(
            session_id="s1",
            total_tokens=4000,
            trace_events=10,
        )
        result = compute_token_efficiency(data)
        assert result == 0.75


# ── 测试 compute_all_metrics ───────────────────────────────────────────────


class TestComputeAllMetrics:
    """测试完整 5 类指标计算。"""

    def test_five_metrics_returned(self):
        """始终返回 5 个指标。"""
        data = SessionEventData(session_id="s1", intent="install nginx")
        metrics = compute_all_metrics(data)
        assert len(metrics) == 5

        metric_names = {m.metric_name for m in metrics}
        assert metric_names == set(ALL_METRIC_NAMES)

    def test_session_id_propagated(self):
        """每个指标的 session_id 正确传播。"""
        data = SessionEventData(session_id="test-session-123")
        metrics = compute_all_metrics(data)
        for m in metrics:
            assert m.session_id == "test-session-123"

    def test_user_device_propagated(self):
        """user_id / device_id 正确传播。"""
        data = SessionEventData(
            session_id="s1",
            user_id="user-1",
            device_id="device-1",
        )
        metrics = compute_all_metrics(data)
        for m in metrics:
            assert m.user_id == "user-1"
            assert m.device_id == "device-1"

    def test_values_are_rounded(self):
        """指标值保留 4 位小数。"""
        data = SessionEventData(
            session_id="s1",
            total_events=3,
            ask_user_count=1,
        )
        metrics = compute_all_metrics(data)
        for m in metrics:
            # 验证小数位不超过 4 位
            assert m.value == round(m.value, 4)


# ── 测试 extract_and_store_metrics ─────────────────────────────────────────


class TestExtractAndStoreMetrics:
    """测试完整的提取 + 持久化流程。"""

    @pytest_asyncio.fixture
    async def eval_db(self, tmp_path):
        """创建临时 evals.db。"""
        db_path = str(tmp_path / "test_evals.db")
        db = EvalDatabase(db_path)
        await db.init_db()
        return db

    @pytest.mark.asyncio
    async def test_store_and_query(self, eval_db):
        """存储后可查询。"""
        events = [
            _make_trace_event("execute_command"),
            _make_result_event(response_type="command_sequence", total_tokens=400),
        ]
        metrics = await extract_and_store_metrics(
            eval_db,
            events,
            session_id="s-store-1",
            user_id="u1",
            device_id="d1",
            intent="install nginx",
        )
        assert len(metrics) == 5

        # 验证持久化
        stored = await eval_db.get_quality_metrics_by_session("s-store-1")
        assert len(stored) == 5

        names = {m.metric_name for m in stored}
        assert names == set(ALL_METRIC_NAMES)

    @pytest.mark.asyncio
    async def test_correct_accuracy(self, eval_db):
        """验证 response_type_accuracy 计算正确并持久化。"""
        events = [
            _make_trace_event("execute_command"),
            _make_result_event(response_type="command_sequence", total_tokens=500),
        ]
        metrics = await extract_and_store_metrics(
            eval_db,
            events,
            session_id="s-acc-1",
            intent="install nginx",
        )
        accuracy = next(m for m in metrics if m.metric_name == METRIC_RESPONSE_TYPE_ACCURACY)
        assert accuracy.value == 1.0

    @pytest.mark.asyncio
    async def test_ask_user_frequency_calculation(self, eval_db):
        """验证 ask_user_frequency 正确计算。"""
        events = [
            _make_trace_event("execute_command"),
            _make_question_event(),
            _make_answer_event(),
            _make_trace_event("execute_command"),
            _make_result_event(total_tokens=800),
        ]
        metrics = await extract_and_store_metrics(
            eval_db,
            events,
            session_id="s-ask-1",
        )
        freq = next(m for m in metrics if m.metric_name == METRIC_ASK_USER_FREQUENCY)
        # 1 ask_user / 5 events = 0.2
        assert freq.value == 0.2


# ── 测试 batch_extract_metrics ──────────────────────────────────────────────


class TestBatchExtractMetrics:
    """测试批量提取指标。"""

    @pytest_asyncio.fixture
    async def eval_db(self, tmp_path):
        """创建临时 evals.db。"""
        db_path = str(tmp_path / "test_evals.db")
        db = EvalDatabase(db_path)
        await db.init_db()
        return db

    @pytest.fixture
    def app_db(self, tmp_path):
        """创建临时 app.db 并填充测试数据。"""
        db_path = str(tmp_path / "test_app.db")
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT UNIQUE NOT NULL,
                user_id TEXT NOT NULL,
                device_id TEXT NOT NULL,
                terminal_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                tombstone_until TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, device_id, terminal_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_conversation_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                event_index INTEGER NOT NULL,
                event_id TEXT UNIQUE NOT NULL,
                event_type TEXT NOT NULL,
                role TEXT NOT NULL,
                session_id TEXT,
                question_id TEXT,
                client_event_id TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                UNIQUE(conversation_id, event_index)
            )
        """)

        now = "2025-01-01T00:00:00+00:00"

        # 插入 conversation
        conn.execute(
            "INSERT INTO agent_conversations (conversation_id, user_id, device_id, terminal_id, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("conv-1", "user-1", "device-1", "term-1", "active", now, now),
        )

        # 插入 events for session batch-1
        events_data = [
            ("conv-1", 0, "evt_001", "trace", "assistant", "batch-1", None, None,
             json.dumps({"tool": "execute_command", "input_summary": "ls", "output_summary": "ok"})),
            ("conv-1", 1, "evt_002", "result", "assistant", "batch-1", None, None,
             json.dumps({"response_type": "command_sequence", "usage": {"total_tokens": 500}})),
        ]
        conn.executemany(
            "INSERT INTO agent_conversation_events (conversation_id, event_index, event_id, event_type, role, session_id, question_id, client_event_id, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(*e, now) for e in events_data],
        )
        conn.commit()
        conn.close()
        return db_path

    @pytest.mark.asyncio
    async def test_batch_extract_specific_session(self, eval_db, app_db):
        """批量提取指定 session_id 的指标。"""
        results = await batch_extract_metrics(
            eval_db,
            app_db,
            session_ids=["batch-1"],
        )
        assert "batch-1" in results
        assert len(results["batch-1"]) == 5

    @pytest.mark.asyncio
    async def test_batch_extract_all(self, eval_db, app_db):
        """批量提取所有已完成 session。"""
        results = await batch_extract_metrics(eval_db, app_db)
        assert len(results) >= 1
        assert "batch-1" in results

    @pytest.mark.asyncio
    async def test_batch_nonexistent_session(self, eval_db, app_db):
        """指定不存在的 session_id → 空结果。"""
        results = await batch_extract_metrics(
            eval_db,
            app_db,
            session_ids=["nonexistent"],
        )
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_batch_persisted_to_eval_db(self, eval_db, app_db):
        """批量提取后指标持久化到 evals.db。"""
        await batch_extract_metrics(
            eval_db,
            app_db,
            session_ids=["batch-1"],
        )
        stored = await eval_db.get_quality_metrics_by_session("batch-1")
        assert len(stored) == 5

    @pytest.mark.asyncio
    async def test_batch_user_device_propagated(self, eval_db, app_db):
        """批量提取时 user_id / device_id 正确传播。"""
        results = await batch_extract_metrics(
            eval_db,
            app_db,
            session_ids=["batch-1"],
        )
        for metric in results["batch-1"]:
            assert metric.user_id == "user-1"
            assert metric.device_id == "device-1"


# ── 端到端集成测试 ──────────────────────────────────────────────────────────


class TestEndToEnd:
    """端到端：构造完整的 session 事件流，验证所有指标。"""

    @pytest_asyncio.fixture
    async def eval_db(self, tmp_path):
        db_path = str(tmp_path / "test_evals.db")
        db = EvalDatabase(db_path)
        await db.init_db()
        return db

    @pytest.mark.asyncio
    async def test_full_session_flow(self, eval_db):
        """模拟完整的 Agent session：
        1. execute_command (ls)
        2. execute_command (cat file)
        3. ask_user (确认)
        4. answer (是)
        5. execute_command (rm)
        6. result (command_sequence, 1500 tokens)
        """
        events = [
            _make_trace_event("execute_command"),
            _make_trace_event("execute_command"),
            _make_question_event(),
            _make_answer_event(),
            _make_trace_event("execute_command"),
            _make_result_event(response_type="command_sequence", total_tokens=1500),
        ]
        metrics = await extract_and_store_metrics(
            eval_db,
            events,
            session_id="s-e2e-1",
            user_id="user-e2e",
            device_id="device-e2e",
            intent="remove old log files",
        )

        # 验证 5 个指标
        by_name = {m.metric_name: m.value for m in metrics}

        # response_type_accuracy: intent "remove" -> command_sequence 匹配
        assert by_name[METRIC_RESPONSE_TYPE_ACCURACY] == 1.0

        # tool_usage_efficiency: 3 execute_command -> 1/3 ≈ 0.3333
        assert abs(by_name[METRIC_TOOL_USAGE_EFFICIENCY] - 0.3333) < 0.01

        # command_safety_rate: 无安全检查 -> 1.0
        assert by_name[METRIC_COMMAND_SAFETY_RATE] == 1.0

        # ask_user_frequency: 1 ask_user / 6 events ≈ 0.1667
        assert abs(by_name[METRIC_ASK_USER_FREQUENCY] - 0.1667) < 0.01

        # token_efficiency: 3 trace + 1 question + 1 answer = 5 轮 (medium)
        # baseline = 1500, tokens = 1500 → 1500/1500 = 1.0
        assert by_name[METRIC_TOKEN_EFFICIENCY] == 1.0

    @pytest.mark.asyncio
    async def test_session_with_errors(self, eval_db):
        """包含 error 事件的 session。"""
        events = [
            _make_trace_event("execute_command"),
            _make_error_event(),
        ]
        metrics = await extract_and_store_metrics(
            eval_db,
            events,
            session_id="s-err-1",
            intent="check disk usage",
        )

        by_name = {m.metric_name: m.value for m in metrics}

        # 无 result → accuracy = 0.0
        assert by_name[METRIC_RESPONSE_TYPE_ACCURACY] == 0.0

        # 1 tool call, no result → efficiency = 0.0
        assert by_name[METRIC_TOOL_USAGE_EFFICIENCY] == 0.0

    @pytest.mark.asyncio
    async def test_query_by_metric_name(self, eval_db):
        """按 metric_name 查询。"""
        for i in range(3):
            events = [_make_result_event(total_tokens=100 * (i + 1))]
            await extract_and_store_metrics(
                eval_db,
                events,
                session_id=f"s-query-{i}",
            )

        accuracy_metrics = await eval_db.get_quality_metrics_by_name(
            METRIC_RESPONSE_TYPE_ACCURACY
        )
        assert len(accuracy_metrics) == 3
        for m in accuracy_metrics:
            assert m.metric_name == METRIC_RESPONSE_TYPE_ACCURACY

"""
B101: quality_monitor 测试 — 验证 5 类质量指标 + B055 效率指标计算正确。

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
    # B055: 效率指标
    METRIC_N_TURNS,
    METRIC_N_TOOLCALLS,
    METRIC_TIME_TO_FIRST_TOKEN,
    METRIC_OUTPUT_TOKENS_PER_SEC,
    METRIC_TIME_TO_LAST_TOKEN,
    SessionEventData,
    batch_extract_metrics,
    compute_all_metrics,
    compute_ask_user_frequency,
    compute_command_safety_rate,
    compute_response_type_accuracy,
    compute_token_efficiency,
    compute_tool_usage_efficiency,
    # B055: 效率指标计算函数
    compute_n_turns,
    compute_n_toolcalls,
    compute_time_to_first_token,
    compute_output_tokens_per_sec,
    compute_time_to_last_token,
    extract_and_store_metrics,
    extract_session_data,
)


# ── 辅助：构造测试 events ──────────────────────────────────────────────────


def _make_trace_event(tool: str, **extra_payload) -> dict:
    """构造 trace 事件（旧事件类型，向后兼容测试）。"""
    payload = {"tool": tool, "input_summary": "test", "output_summary": "ok"}
    payload.update(extra_payload)
    return {"event_type": "trace", "payload": payload}


def _make_tool_step_event(tool_name: str, **extra_payload) -> dict:
    """构造 tool_step 事件（B106 新事件类型）。"""
    payload = {"tool_name": tool_name, "description": "test", "status": "done", "result_summary": "ok"}
    payload.update(extra_payload)
    return {"event_type": "tool_step", "payload": payload}


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
        assert data.tool_step_events == 0
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
        assert data.tool_step_events == 1
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

    def test_tool_step_event_recognized(self):
        """S111: tool_step 事件（B106 新类型）能被正确识别，替代旧 trace。"""
        events = [
            _make_tool_step_event("execute_command"),
            _make_tool_step_event("lookup_knowledge"),
            _make_result_event(response_type="command", total_tokens=500),
        ]
        data = extract_session_data(events, session_id="s-toolstep-1", intent="list files")

        assert data.tool_step_events == 2
        assert data.execute_command_count == 1
        assert data.lookup_knowledge_count == 1
        assert data.has_result is True

    def test_phase_change_event_counted(self):
        """S111: phase_change 事件被正确计数。"""
        events = [
            {"event_type": "phase_change", "payload": {"phase": "THINKING", "description": "Analyzing..."}},
            {"event_type": "phase_change", "payload": {"phase": "EXPLORING", "description": "Exploring..."}},
            _make_tool_step_event("execute_command"),
            _make_result_event(total_tokens=300),
        ]
        data = extract_session_data(events, session_id="s-phase-1")

        assert data.phase_change_events == 2
        assert data.tool_step_events == 1

    def test_streaming_text_event_counted(self):
        """S111: streaming_text 事件被正确计数。"""
        events = [
            {"event_type": "streaming_text", "payload": {"text_delta": "Hello"}},
            {"event_type": "streaming_text", "payload": {"text_delta": " world"}},
            _make_tool_step_event("execute_command"),
            _make_result_event(total_tokens=400),
        ]
        data = extract_session_data(events, session_id="s-stream-1")

        assert data.streaming_text_events == 2

    def test_mixed_old_and_new_event_types(self):
        """S111: 混合旧 trace 和新 tool_step 事件都能被正确识别（向后兼容）。"""
        events = [
            _make_trace_event("execute_command"),
            _make_tool_step_event("execute_command"),
            _make_tool_step_event("lookup_knowledge"),
            _make_result_event(total_tokens=600),
        ]
        data = extract_session_data(events, session_id="s-mixed-1")

        assert data.tool_step_events == 3  # 1 trace + 2 tool_step
        assert data.execute_command_count == 2

    def test_tool_step_safety_check_via_result_summary(self):
        """S111: tool_step 的 safety check 从 result_summary 字段提取（替代旧 output_summary）。"""
        events = [
            _make_tool_step_event(
                "execute_command",
                result_summary="SAFETY_CHECK: rm -rf / -> BLOCKED",
            ),
            _make_tool_step_event(
                "execute_command",
                result_summary="SAFETY_CHECK: ls -la -> PASSED",
            ),
            _make_result_event(),
        ]
        data = extract_session_data(events, session_id="s-safety-1")

        assert data.safety_checked_commands == 2
        assert data.safety_passed_commands == 1


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
            tool_step_events=1,
        )
        result = compute_token_efficiency(data)
        assert result == 1.0  # capped at 1.0

    def test_medium_task_efficient(self):
        """中等任务（5 轮），1000 tokens → 1500/1000 = 1.0 (capped)。"""
        data = SessionEventData(
            session_id="s1",
            total_tokens=1000,
            tool_step_events=5,
        )
        result = compute_token_efficiency(data)
        assert result == 1.0

    def test_easy_task_inefficient(self):
        """简单任务（1 轮），1000 tokens → 500/1000 = 0.5。"""
        data = SessionEventData(
            session_id="s1",
            total_tokens=1000,
            tool_step_events=1,
        )
        result = compute_token_efficiency(data)
        assert result == 0.5

    def test_hard_task(self):
        """困难任务（10 轮），4000 tokens → 3000/4000 = 0.75。"""
        data = SessionEventData(
            session_id="s1",
            total_tokens=4000,
            tool_step_events=10,
        )
        result = compute_token_efficiency(data)
        assert result == 0.75


# ── 测试 compute_all_metrics ───────────────────────────────────────────────


class TestComputeAllMetrics:
    """测试完整 5 类指标计算。"""

    def test_five_metrics_returned(self):
        """始终返回 10 个指标（5 原有 + 5 效率 B055）。"""
        data = SessionEventData(session_id="s1", intent="install nginx")
        metrics = compute_all_metrics(data)
        assert len(metrics) == 10

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
        assert len(metrics) == 10

        # 验证持久化
        stored = await eval_db.get_quality_metrics_by_session("s-store-1")
        assert len(stored) == 10

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
        assert len(results["batch-1"]) == 10

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
        assert len(stored) == 10

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

        # token_efficiency: 3 tool_step + 1 question + 1 answer = 5 轮 (medium)
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


# ── B052 新增测试: 新字段 source / result_event_id / terminal_id ─────────────


class TestQualityMetricNewFields:
    """B052: QualityMetric 新字段测试"""

    @pytest_asyncio.fixture
    async def eval_db(self, tmp_path):
        db_path = str(tmp_path / "test_evals.db")
        db = EvalDatabase(db_path)
        await db.init_db()
        return db

    @pytest.mark.asyncio
    async def test_source_field_persisted(self, eval_db):
        """source 字段正确持久化"""
        events = [
            _make_tool_step_event("execute_command"),
            _make_result_event(response_type="command_sequence", total_tokens=300),
        ]
        metrics = await extract_and_store_metrics(
            eval_db,
            events,
            session_id="s-source-1",
            source="production",
        )
        for m in metrics:
            assert m.source == "production"

        # 从数据库读取验证
        stored = await eval_db.get_quality_metrics_by_session("s-source-1")
        for m in stored:
            assert m.source == "production"

    @pytest.mark.asyncio
    async def test_terminal_id_field_persisted(self, eval_db):
        """terminal_id 字段正确持久化"""
        events = [
            _make_tool_step_event("execute_command"),
            _make_result_event(total_tokens=500),
        ]
        metrics = await extract_and_store_metrics(
            eval_db,
            events,
            session_id="s-term-1",
            terminal_id="term-abc123",
        )
        for m in metrics:
            assert m.terminal_id == "term-abc123"

        stored = await eval_db.get_quality_metrics_by_session("s-term-1")
        for m in stored:
            assert m.terminal_id == "term-abc123"

    @pytest.mark.asyncio
    async def test_result_event_id_field_persisted(self, eval_db):
        """result_event_id 字段正确持久化"""
        events = [
            _make_result_event(total_tokens=200),
        ]
        metrics = await extract_and_store_metrics(
            eval_db,
            events,
            session_id="s-revid-1",
            result_event_id="evt-xyz789",
        )
        for m in metrics:
            assert m.result_event_id == "evt-xyz789"

        stored = await eval_db.get_quality_metrics_by_session("s-revid-1")
        for m in stored:
            assert m.result_event_id == "evt-xyz789"

    @pytest.mark.asyncio
    async def test_default_values(self, eval_db):
        """不传新字段时使用默认值"""
        events = [_make_result_event(total_tokens=100)]
        metrics = await extract_and_store_metrics(
            eval_db,
            events,
            session_id="s-default-1",
        )
        for m in metrics:
            assert m.source == "production"
            assert m.result_event_id == ""
            assert m.terminal_id == ""

    @pytest.mark.asyncio
    async def test_integration_source(self, eval_db):
        """source='integration' 场景"""
        events = [_make_result_event(total_tokens=100)]
        metrics = await extract_and_store_metrics(
            eval_db,
            events,
            session_id="s-integ-1",
            source="integration",
        )
        for m in metrics:
            assert m.source == "integration"


class TestQualityMonitorAutoTrigger:
    """B052: quality_monitor 自动触发测试"""

    def test_trigger_function_exists(self):
        """_trigger_quality_monitor 函数存在"""
        from app.services.agent_session_runner import _trigger_quality_monitor
        assert callable(_trigger_quality_monitor)

    def test_trigger_handles_empty_events(self):
        """传入空 result_event_data 仍能安全处理（不抛异常）"""
        from datetime import datetime, timezone
        from app.services.agent_session_runner import _trigger_quality_monitor
        from app.services.agent_session_manager import AgentSessionManager
        from app.services.agent_session import AgentSession
        from app.services.agent_session_types import AgentSessionState

        manager = AgentSessionManager()
        now = datetime.now(timezone.utc)
        session = AgentSession(
            id="test-session",
            intent="test",
            device_id="device-1",
            user_id="user-1",
            state=AgentSessionState.COMPLETED,
            created_at=now,
            last_active_at=now,
            terminal_id="term-1",
        )
        # 新接口直接从 result_event_data 构造 events
        _trigger_quality_monitor(
            manager, session,
            result_event_data={"response_type": "command_sequence", "usage": {"total_tokens": 0}},
        )
        # 无异常即通过

    def test_trigger_handles_events(self):
        """有事件时触发异步提取（不抛异常）"""
        from datetime import datetime, timezone
        from app.services.agent_session_runner import _trigger_quality_monitor
        from app.services.agent_session_manager import AgentSessionManager
        from app.services.agent_session import AgentSession
        from app.services.agent_session_types import AgentSessionState

        manager = AgentSessionManager()
        now = datetime.now(timezone.utc)
        session = AgentSession(
            id="test-session-2",
            intent="test intent",
            device_id="device-1",
            user_id="user-1",
            state=AgentSessionState.COMPLETED,
            created_at=now,
            last_active_at=now,
            terminal_id="term-2",
        )
        # 新接口直接传入 result_event_data（不再依赖 _last_events）
        _trigger_quality_monitor(
            manager, session,
            result_event_data={
                "response_type": "command_sequence",
                "summary": "test result",
                "usage": {"total_tokens": 500},
            },
            result_event_id="evt_test123",
        )
        # 无异常即通过（实际写入可能因目录不存在而失败，但不应抛出）


# ── B055: 效率指标测试 ─────────────────────────────────────────────────────


def _make_phase_change_event(phase: str, created_at: str = "", **extra) -> dict:
    """构造 phase_change 事件。"""
    payload = {"phase": phase, "description": "test"}
    payload.update(extra)
    event = {"event_type": "phase_change", "payload": payload}
    if created_at:
        event["created_at"] = created_at
    return event


def _make_streaming_text_event(text: str = "hello", created_at: str = "", **extra) -> dict:
    """构造 streaming_text 事件。"""
    payload = {"text_delta": text}
    payload.update(extra)
    event = {"event_type": "streaming_text", "payload": payload}
    if created_at:
        event["created_at"] = created_at
    return event


def _make_result_event_with_time(
    response_type: str = "command_sequence",
    total_tokens: int = 500,
    output_tokens: int = 200,
    created_at: str = "",
    **extra_payload,
) -> dict:
    """构造带时间戳的 result 事件。"""
    payload = {
        "response_type": response_type,
        "summary": "test summary",
        "usage": {
            "total_tokens": total_tokens,
            "completion_tokens": output_tokens,
            "output_tokens": output_tokens,
        },
    }
    payload.update(extra_payload)
    event = {"event_type": "result", "payload": payload}
    if created_at:
        event["created_at"] = created_at
    return event


def _make_error_event_with_time(created_at: str = "", **extra) -> dict:
    """构造带时间戳的 error 事件。"""
    payload = {"code": "AGENT_ERROR", "message": "test error"}
    payload.update(extra)
    event = {"event_type": "error", "payload": payload}
    if created_at:
        event["created_at"] = created_at
    return event


# ── compute_n_turns ────────────────────────────────────────────────────────


class TestComputeNTurns:
    """B055: n_turns 指标测试"""

    def test_no_phase_changes(self):
        """无 phase_change 事件 → 0.0"""
        data = SessionEventData(session_id="s1")
        assert compute_n_turns(data) == 0.0

    def test_one_phase_change(self):
        """1 个 phase_change → 1.0"""
        data = SessionEventData(session_id="s1", phase_change_events=1)
        assert compute_n_turns(data) == 1.0

    def test_many_phase_changes(self):
        """多个 phase_change"""
        data = SessionEventData(session_id="s1", phase_change_events=5)
        assert compute_n_turns(data) == 5.0

    def test_from_events(self):
        """从事件流中正确提取 phase_change 计数"""
        events = [
            _make_phase_change_event("THINKING"),
            _make_phase_change_event("ACTING"),
            _make_tool_step_event("execute_command"),
            _make_phase_change_event("THINKING"),
            _make_result_event(),
        ]
        data = extract_session_data(events, session_id="s1")
        assert compute_n_turns(data) == 3.0


# ── compute_n_toolcalls ────────────────────────────────────────────────────


class TestComputeNToolcalls:
    """B055: n_toolcalls 指标测试"""

    def test_no_toolcalls(self):
        """无工具调用 → 0.0"""
        data = SessionEventData(session_id="s1")
        assert compute_n_toolcalls(data) == 0.0

    def test_one_toolcall(self):
        """1 次工具调用 → 1.0"""
        data = SessionEventData(session_id="s1", tool_step_events=1)
        assert compute_n_toolcalls(data) == 1.0

    def test_from_events(self):
        """从事件流中正确提取 tool_step 计数"""
        events = [
            _make_tool_step_event("execute_command"),
            _make_tool_step_event("lookup_knowledge"),
            _make_result_event(),
        ]
        data = extract_session_data(events, session_id="s1")
        assert compute_n_toolcalls(data) == 2.0


# ── compute_time_to_first_token ────────────────────────────────────────────


class TestComputeTimeToFirstToken:
    """B055: time_to_first_token 指标测试"""

    def test_no_timestamps(self):
        """无时间戳 → -1.0"""
        data = SessionEventData(session_id="s1")
        assert compute_time_to_first_token(data) == -1.0

    def test_only_thinking_time(self):
        """只有 thinking 时间，无 streaming → -1.0"""
        data = SessionEventData(
            session_id="s1",
            thinking_phase_time="2025-01-01T00:00:00+00:00",
        )
        assert compute_time_to_first_token(data) == -1.0

    def test_valid_calculation(self):
        """正常计算：thinking 10:00:00, first_stream 10:00:02 → 2.0 秒"""
        data = SessionEventData(
            session_id="s1",
            thinking_phase_time="2025-01-01T10:00:00+00:00",
            first_streaming_text_time="2025-01-01T10:00:02+00:00",
        )
        result = compute_time_to_first_token(data)
        assert abs(result - 2.0) < 0.01

    def test_from_events(self):
        """从事件流中正确计算首 token 延迟"""
        events = [
            _make_phase_change_event("THINKING", created_at="2025-01-01T10:00:00+00:00"),
            _make_streaming_text_event("hello", created_at="2025-01-01T10:00:01.500+00:00"),
            _make_result_event_with_time(created_at="2025-01-01T10:00:03+00:00"),
        ]
        data = extract_session_data(events, session_id="s1")
        result = compute_time_to_first_token(data)
        assert abs(result - 1.5) < 0.01


# ── compute_output_tokens_per_sec ──────────────────────────────────────────


class TestComputeOutputTokensPerSec:
    """B055: output_tokens_per_sec 指标测试"""

    def test_no_output_tokens(self):
        """无 output_tokens → -1.0"""
        data = SessionEventData(session_id="s1")
        assert compute_output_tokens_per_sec(data) == -1.0

    def test_no_streaming_duration(self):
        """有 output_tokens 但无 streaming 时间 → -1.0"""
        data = SessionEventData(
            session_id="s1",
            output_tokens=100,
            first_streaming_text_time="2025-01-01T10:00:00+00:00",
            # 缺少 last_streaming_text_time
        )
        assert compute_output_tokens_per_sec(data) == -1.0

    def test_valid_calculation(self):
        """100 tokens / 2 秒 = 50.0 tokens/sec"""
        data = SessionEventData(
            session_id="s1",
            output_tokens=100,
            first_streaming_text_time="2025-01-01T10:00:00+00:00",
            last_streaming_text_time="2025-01-01T10:00:02+00:00",
        )
        result = compute_output_tokens_per_sec(data)
        assert abs(result - 50.0) < 0.01

    def test_from_events(self):
        """从事件流中正确计算输出速率"""
        events = [
            _make_streaming_text_event("hello", created_at="2025-01-01T10:00:00+00:00"),
            _make_streaming_text_event("world", created_at="2025-01-01T10:00:05+00:00"),
            _make_result_event_with_time(output_tokens=500, created_at="2025-01-01T10:00:06+00:00"),
        ]
        data = extract_session_data(events, session_id="s1")
        result = compute_output_tokens_per_sec(data)
        assert abs(result - 100.0) < 0.01  # 500 / 5 = 100


# ── compute_time_to_last_token ─────────────────────────────────────────────


class TestComputeTimeToLastToken:
    """B055: time_to_last_token 指标测试"""

    def test_no_timestamps(self):
        """无时间戳 → -1.0"""
        data = SessionEventData(session_id="s1")
        assert compute_time_to_last_token(data) == -1.0

    def test_only_first_event(self):
        """只有第一个事件时间 → -1.0"""
        data = SessionEventData(
            session_id="s1",
            first_event_time="2025-01-01T10:00:00+00:00",
        )
        assert compute_time_to_last_token(data) == -1.0

    def test_valid_calculation(self):
        """开始 10:00:00, 结束 10:00:05 → 5.0 秒"""
        data = SessionEventData(
            session_id="s1",
            first_event_time="2025-01-01T10:00:00+00:00",
            result_or_error_time="2025-01-01T10:00:05+00:00",
        )
        result = compute_time_to_last_token(data)
        assert abs(result - 5.0) < 0.01

    def test_from_events_with_result(self):
        """从事件流中正确计算总延迟（result 事件）"""
        events = [
            _make_tool_step_event("execute_command"),
            _make_phase_change_event("THINKING", created_at="2025-01-01T10:00:00+00:00"),
            _make_result_event_with_time(created_at="2025-01-01T10:00:03+00:00"),
        ]
        data = extract_session_data(events, session_id="s1")
        result = compute_time_to_last_token(data)
        assert abs(result - 3.0) < 0.01

    def test_from_events_with_error(self):
        """从事件流中正确计算总延迟（error 事件）"""
        events = [
            {
                "event_type": "tool_step",
                "created_at": "2025-01-01T10:00:00+00:00",
                "payload": {"tool_name": "execute_command", "status": "done"},
            },
            _make_error_event_with_time(created_at="2025-01-01T10:00:02+00:00"),
        ]
        data = extract_session_data(events, session_id="s1")
        result = compute_time_to_last_token(data)
        assert abs(result - 2.0) < 0.01


# ── B055: compute_all_metrics 包含 10 个指标 ──────────────────────────────


class TestComputeAllMetricsB055:
    """B055: compute_all_metrics 返回 10 个指标"""

    def test_ten_metrics_returned(self):
        """compute_all_metrics 现在返回 10 个指标（5 原有 + 5 效率）"""
        data = SessionEventData(session_id="s1")
        metrics = compute_all_metrics(data)
        assert len(metrics) == 10

        metric_names = {m.metric_name for m in metrics}
        expected = {
            METRIC_RESPONSE_TYPE_ACCURACY,
            METRIC_TOOL_USAGE_EFFICIENCY,
            METRIC_COMMAND_SAFETY_RATE,
            METRIC_ASK_USER_FREQUENCY,
            METRIC_TOKEN_EFFICIENCY,
            METRIC_N_TURNS,
            METRIC_N_TOOLCALLS,
            METRIC_TIME_TO_FIRST_TOKEN,
            METRIC_OUTPUT_TOKENS_PER_SEC,
            METRIC_TIME_TO_LAST_TOKEN,
        }
        assert metric_names == expected

    def test_all_metric_names_constant(self):
        """ALL_METRIC_NAMES 常量包含 10 个指标"""
        assert len(ALL_METRIC_NAMES) == 10

    def test_efficiency_metrics_from_events(self):
        """完整事件流中效率指标计算正确"""
        events = [
            _make_phase_change_event("THINKING", created_at="2025-01-01T10:00:00+00:00"),
            _make_streaming_text_event("hello", created_at="2025-01-01T10:00:01+00:00"),
            _make_streaming_text_event("world", created_at="2025-01-01T10:00:03+00:00"),
            _make_tool_step_event("execute_command"),
            _make_result_event_with_time(
                total_tokens=1000, output_tokens=400,
                created_at="2025-01-01T10:00:05+00:00",
            ),
        ]
        data = extract_session_data(events, session_id="s1")
        metrics = compute_all_metrics(data)
        by_name = {m.metric_name: m.value for m in metrics}

        # n_turns: 1 phase_change
        assert by_name[METRIC_N_TURNS] == 1.0

        # n_toolcalls: 1 tool_step
        assert by_name[METRIC_N_TOOLCALLS] == 1.0

        # time_to_first_token: 1.0 秒（10:00:01 - 10:00:00）
        assert abs(by_name[METRIC_TIME_TO_FIRST_TOKEN] - 1.0) < 0.01

        # output_tokens_per_sec: 400 / 2.0 = 200.0
        assert abs(by_name[METRIC_OUTPUT_TOKENS_PER_SEC] - 200.0) < 0.01

        # time_to_last_token: 5.0 秒（10:00:05 - 10:00:00）
        assert abs(by_name[METRIC_TIME_TO_LAST_TOKEN] - 5.0) < 0.01


# ── B055: integration source 过滤测试 ─────────────────────────────────────


class TestSourceFilter:
    """B055: source 过滤功能测试"""

    @pytest_asyncio.fixture
    async def eval_db(self, tmp_path):
        db_path = str(tmp_path / "test_evals.db")
        db = EvalDatabase(db_path)
        await db.init_db()
        return db

    @pytest.mark.asyncio
    async def test_source_filter_in_query(self, eval_db):
        """query_quality_metrics 支持 source 过滤"""
        # 写入 production 指标
        events_prod = [
            _make_tool_step_event("execute_command"),
            _make_result_event_with_time(created_at="2025-01-01T10:00:00+00:00"),
        ]
        await extract_and_store_metrics(
            eval_db, events_prod, session_id="s-prod-1", source="production",
        )

        # 写入 integration 指标
        events_integ = [
            _make_tool_step_event("execute_command"),
            _make_result_event_with_time(created_at="2025-01-01T11:00:00+00:00"),
        ]
        await extract_and_store_metrics(
            eval_db, events_integ, session_id="s-integ-1", source="integration",
        )

        # 不带 source 过滤 → 返回全部
        all_metrics = await eval_db.query_quality_metrics()
        assert len(all_metrics) == 20  # 2 sessions * 10 metrics

        # 过滤 production
        prod_metrics = await eval_db.query_quality_metrics(source="production")
        assert len(prod_metrics) == 10
        assert all(m.source == "production" for m in prod_metrics)

        # 过滤 integration
        integ_metrics = await eval_db.query_quality_metrics(source="integration")
        assert len(integ_metrics) == 10
        assert all(m.source == "integration" for m in integ_metrics)

    @pytest.mark.asyncio
    async def test_integration_source_in_compute_all(self, eval_db):
        """compute_all_metrics 正确设置 source=integration"""
        events = [
            _make_result_event_with_time(created_at="2025-01-01T10:00:00+00:00"),
        ]
        metrics = await extract_and_store_metrics(
            eval_db, events, session_id="s-integ-2", source="integration",
        )
        assert len(metrics) == 10
        for m in metrics:
            assert m.source == "integration"

    @pytest.mark.asyncio
    async def test_production_and_integration_isolated(self, eval_db):
        """production 和 integration 数据互不干扰"""
        # 写入 production
        await extract_and_store_metrics(
            eval_db, [_make_result_event()], session_id="s-prod-2", source="production",
        )

        # 写入 integration
        await extract_and_store_metrics(
            eval_db, [_make_result_event()], session_id="s-integ-3", source="integration",
        )

        # production 看板只看 production
        prod = await eval_db.query_quality_metrics(source="production")
        for m in prod:
            assert m.source == "production"
            assert "prod" in m.session_id

        # integration 查询只看 integration
        integ = await eval_db.query_quality_metrics(source="integration")
        for m in integ:
            assert m.source == "integration"
            assert "integ" in m.session_id

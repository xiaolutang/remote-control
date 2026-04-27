"""
database.py 单元测试 — SQLite 用户持久化层
"""
import os
from contextlib import asynccontextmanager
import pytest
import pytest_asyncio
import aiosqlite

# 测试用临时数据库路径
TEST_DB = "/tmp/test_rc_users.db"


@pytest.fixture(autouse=True)
def _clean_db():
    """每个测试配置独立数据库并清理"""
    from app.store.database import configure_database

    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    configure_database(TEST_DB)
    yield
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)


@pytest_asyncio.fixture
async def db_with_tables():
    """初始化表结构"""
    from app.store.database import init_db
    await init_db()
    return TEST_DB


@pytest.mark.asyncio
async def test_init_db_creates_tables(db_with_tables):
    """init_db 创建核心表结构。"""
    async with aiosqlite.connect(TEST_DB) as db:
        for table_name in (
            "users",
            "user_devices",
            "project_source_pinned_projects",
            "project_source_scan_roots",
            "project_source_planner_configs",
            "assistant_planner_runs",
            "assistant_planner_memory_entries",
            "agent_usage_records",
            "agent_conversations",
            "agent_conversation_events",
        ):
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            )
            assert await cursor.fetchone() is not None


@pytest.mark.asyncio
async def test_init_db_creates_index(db_with_tables):
    """init_db 创建索引。"""
    async with aiosqlite.connect(TEST_DB) as db:
        for index_name in (
            "idx_user_devices_username",
            "idx_pinned_projects_scope",
            "idx_scan_roots_scope",
            "idx_planner_configs_scope",
            "idx_assistant_runs_scope",
            "idx_assistant_memory_scope",
            "idx_agent_usage_records_user_device",
            "idx_agent_usage_records_user_created_at",
            "idx_agent_conversations_scope",
            "idx_agent_conversation_events_conversation",
            "idx_agent_conversation_events_client_event",
            "idx_agent_conversation_events_answer_question",
        ):
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                (index_name,),
            )
            assert await cursor.fetchone() is not None


@pytest.mark.asyncio
async def test_save_and_get_user(db_with_tables):
    """save_user 写入，get_user 读取"""
    from app.store.database import save_user, get_user

    await save_user("alice", "hash123")
    user = await get_user("alice")

    assert user is not None
    assert user["username"] == "alice"
    assert user["password_hash"] == "hash123"
    assert "created_at" in user


@pytest.mark.asyncio
async def test_get_user_not_found(db_with_tables):
    """get_user 查不存在的用户返回 None"""
    from app.store.database import get_user

    result = await get_user("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_save_duplicate_user_raises(db_with_tables):
    """重复 username 抛出 IntegrityError"""
    from app.store.database import save_user

    await save_user("bob", "hash1")
    with pytest.raises(aiosqlite.IntegrityError):
        await save_user("bob", "hash2")


@pytest.mark.asyncio
async def test_add_and_get_user_devices(db_with_tables):
    """add_user_device 写入，get_user_devices 读取"""
    from app.store.database import save_user, add_user_device, get_user_devices

    await save_user("charlie", "hash")
    await add_user_device("charlie", {
        "device_name": "iPhone 15",
        "device_type": "mobile",
        "bound_at": "2026-04-13T00:00:00+00:00",
    })
    await add_user_device("charlie", {
        "device_name": "MacBook",
        "device_type": "desktop",
        "bound_at": "2026-04-13T01:00:00+00:00",
    })

    devices = await get_user_devices("charlie")
    assert len(devices) == 2
    names = [d["device_name"] for d in devices]
    assert "iPhone 15" in names
    assert "MacBook" in names


@pytest.mark.asyncio
async def test_get_user_devices_empty(db_with_tables):
    """无设备时返回空列表"""
    from app.store.database import save_user, get_user_devices

    await save_user("dave", "hash")
    devices = await get_user_devices("dave")
    assert devices == []


@pytest.mark.asyncio
async def test_fk_prevents_device_without_user(db_with_tables):
    """外键约束：绑定设备到不存在的用户时抛出 IntegrityError"""
    from app.store.database import add_user_device

    with pytest.raises(aiosqlite.IntegrityError):
        await add_user_device("nonexistent_user", {
            "device_name": "Ghost Phone",
            "device_type": "mobile",
            "bound_at": "2026-04-13T00:00:00+00:00",
        })


@pytest.mark.asyncio
async def test_init_db_idempotent():
    """init_db 多次调用不报错"""
    from app.store.database import init_db

    await init_db()
    await init_db()  # 第二次不应抛异常


@pytest.mark.asyncio
async def test_init_db_creates_directory(tmp_path):
    """init_db 自动创建数据目录"""
    from app.store.database import configure_database, init_db

    db_path = os.path.join(str(tmp_path), "subdir", "test.db")
    configure_database(db_path)
    await init_db()
    assert os.path.exists(db_path)


@pytest.mark.asyncio
async def test_save_agent_usage_and_get_user_summary(db_with_tables):
    """usage 记录可写入并按用户聚合。"""
    from app.store.database import get_usage_summary, save_agent_usage

    assert await save_agent_usage(
        "sess-1",
        "user-1",
        "device-a",
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        requests=2,
        model_name="model-a",
    ) is True
    assert await save_agent_usage(
        "sess-2",
        "user-1",
        "device-b",
        input_tokens=20,
        output_tokens=8,
        total_tokens=28,
        requests=3,
        model_name="model-b",
    ) is True

    summary = await get_usage_summary("user-1")
    assert summary == {
        "total_sessions": 2,
        "total_input_tokens": 30,
        "total_output_tokens": 13,
        "total_tokens": 43,
        "total_requests": 5,
        "latest_model_name": "model-b",
    }


@pytest.mark.asyncio
async def test_get_usage_summary_can_filter_by_device(db_with_tables):
    """device scope 只汇总指定设备。"""
    from app.store.database import get_usage_summary, save_agent_usage

    await save_agent_usage("sess-1", "user-1", "device-a", total_tokens=15, model_name="model-a")
    await save_agent_usage("sess-2", "user-1", "device-a", total_tokens=5, requests=1, model_name="model-b")
    await save_agent_usage("sess-3", "user-1", "device-b", total_tokens=99, requests=9, model_name="model-c")

    summary = await get_usage_summary("user-1", "device-a")
    assert summary == {
        "total_sessions": 2,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_tokens": 20,
        "total_requests": 1,
        "latest_model_name": "model-b",
    }


@pytest.mark.asyncio
async def test_get_usage_summary_returns_zero_defaults_without_records(db_with_tables):
    """无 usage 记录时返回零值汇总。"""
    from app.store.database import get_usage_summary

    summary = await get_usage_summary("user-404", "device-x")
    assert summary == {
        "total_sessions": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_tokens": 0,
        "total_requests": 0,
        "latest_model_name": "",
    }


@pytest.mark.asyncio
async def test_save_agent_usage_failure_returns_false(db_with_tables, monkeypatch):
    """写入失败时返回 False，不向上抛异常。"""
    from app.store.database import _get_db, save_agent_usage

    db = _get_db()

    @asynccontextmanager
    async def _boom():
        raise RuntimeError("db unavailable")
        yield  # pragma: no cover

    monkeypatch.setattr(db, "_connect", _boom)

    ok = await save_agent_usage("sess-fail", "user-1", "device-a", total_tokens=1)
    assert ok is False


@pytest.mark.asyncio
async def test_get_or_create_agent_conversation_is_terminal_scoped(db_with_tables):
    """同一 user/device/terminal 复用同一个 conversation，不同 terminal 隔离。"""
    from app.store.database import get_or_create_agent_conversation

    first = await get_or_create_agent_conversation("user-1", "device-a", "term-1")
    again = await get_or_create_agent_conversation("user-1", "device-a", "term-1")
    other_terminal = await get_or_create_agent_conversation("user-1", "device-a", "term-2")

    assert first["conversation_id"] == again["conversation_id"]
    assert first["status"] == "active"
    assert first["conversation_id"] != other_terminal["conversation_id"]


@pytest.mark.asyncio
async def test_append_agent_conversation_event_assigns_sequential_indexes(db_with_tables):
    """事件 append 在同一 conversation 内分配连续 event_index。"""
    from app.store.database import append_agent_conversation_event, list_agent_conversation_events

    first = await append_agent_conversation_event(
        "user-1",
        "device-a",
        "term-1",
        event_type="user_intent",
        role="user",
        payload={"text": "进入项目"},
        client_event_id="client-1",
    )
    second = await append_agent_conversation_event(
        "user-1",
        "device-a",
        "term-1",
        event_type="question",
        role="assistant",
        payload={"text": "请选择项目"},
        session_id="sess-1",
        question_id="q-1",
    )

    assert first["event_index"] == 0
    assert second["event_index"] == 1

    events = await list_agent_conversation_events("user-1", "device-a", "term-1")
    assert [event["event_index"] for event in events] == [0, 1]
    assert events[0]["payload"] == {"text": "进入项目"}


@pytest.mark.asyncio
async def test_append_agent_conversation_event_supports_after_index(db_with_tables):
    """事件列表支持 after_index 增量读取。"""
    from app.store.database import append_agent_conversation_event, list_agent_conversation_events

    for index in range(3):
        await append_agent_conversation_event(
            "user-1",
            "device-a",
            "term-1",
            event_type="trace",
            role="assistant",
            payload={"index": index},
        )

    events = await list_agent_conversation_events(
        "user-1",
        "device-a",
        "term-1",
        after_index=0,
    )

    assert [event["event_index"] for event in events] == [1, 2]


@pytest.mark.asyncio
async def test_append_agent_conversation_event_is_idempotent_by_client_event_id(db_with_tables):
    """弱网重复提交同一 client_event_id 不新增事件。"""
    from app.store.database import append_agent_conversation_event, list_agent_conversation_events

    first = await append_agent_conversation_event(
        "user-1",
        "device-a",
        "term-1",
        event_type="answer",
        role="user",
        question_id="q-1",
        client_event_id="client-1",
        payload={"text": "remote-control"},
    )
    replay = await append_agent_conversation_event(
        "user-1",
        "device-a",
        "term-1",
        event_type="answer",
        role="user",
        question_id="q-1",
        client_event_id="client-1",
        payload={"text": "remote-control"},
    )

    events = await list_agent_conversation_events("user-1", "device-a", "term-1")
    assert replay["event_id"] == first["event_id"]
    assert len(events) == 1


@pytest.mark.asyncio
async def test_append_agent_conversation_event_rejects_second_answer_for_question(db_with_tables):
    """同一 question_id 只能有一个有效 answer。"""
    from app.store.database import (
        AgentConversationConflict,
        append_agent_conversation_event,
        list_agent_conversation_events,
    )

    await append_agent_conversation_event(
        "user-1",
        "device-a",
        "term-1",
        event_type="answer",
        role="user",
        question_id="q-1",
        client_event_id="client-1",
        payload={"text": "remote-control"},
    )

    with pytest.raises(AgentConversationConflict) as exc_info:
        await append_agent_conversation_event(
            "user-1",
            "device-a",
            "term-1",
            event_type="answer",
            role="user",
            question_id="q-1",
            client_event_id="client-2",
            payload={"text": "other"},
        )

    assert exc_info.value.code == "question_already_answered"
    events = await list_agent_conversation_events("user-1", "device-a", "term-1")
    assert len(events) == 1


@pytest.mark.asyncio
async def test_agent_conversation_close_tombstone_hides_history_then_cleanup(db_with_tables):
    """close 后进入 tombstone，不返回历史；过期清理后物理删除。"""
    from app.store.database import (
        append_agent_conversation_event,
        cleanup_agent_conversation_tombstones,
        close_agent_conversation,
        get_agent_conversation,
        list_agent_conversation_events,
    )

    await append_agent_conversation_event(
        "user-1",
        "device-a",
        "term-1",
        event_type="user_intent",
        role="user",
        payload={"text": "hello"},
    )
    await close_agent_conversation(
        "user-1",
        "device-a",
        "term-1",
        payload={"reason": "terminal_closed"},
        tombstone_seconds=-1,
    )

    conversation = await get_agent_conversation("user-1", "device-a", "term-1")
    assert conversation is not None
    assert conversation["status"] == "closed"
    assert await list_agent_conversation_events("user-1", "device-a", "term-1") == []

    deleted = await cleanup_agent_conversation_tombstones()
    assert deleted == 1
    assert await get_agent_conversation("user-1", "device-a", "term-1") is None


@pytest.mark.asyncio
async def test_delete_agent_conversation_removes_events(db_with_tables):
    """物理删除 conversation 会级联删除 events。"""
    from app.store.database import (
        append_agent_conversation_event,
        delete_agent_conversation,
        get_or_create_agent_conversation,
    )

    conversation = await get_or_create_agent_conversation("user-1", "device-a", "term-1")
    await append_agent_conversation_event(
        "user-1",
        "device-a",
        "term-1",
        event_type="user_intent",
        role="user",
        payload={"text": "hello"},
    )

    assert await delete_agent_conversation("user-1", "device-a", "term-1") is True

    async with aiosqlite.connect(TEST_DB) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM agent_conversation_events WHERE conversation_id = ?",
            (conversation["conversation_id"],),
        )
        row = await cursor.fetchone()
    assert row[0] == 0


@pytest.mark.asyncio
async def test_agent_conversation_scope_prevents_cross_user_reads(db_with_tables):
    """按 user/device/terminal 查询，其他用户不能读到 conversation/events。"""
    from app.store.database import (
        append_agent_conversation_event,
        get_agent_conversation,
        list_agent_conversation_events,
    )

    await append_agent_conversation_event(
        "user-1",
        "device-a",
        "term-1",
        event_type="user_intent",
        role="user",
        payload={"text": "secret"},
    )

    assert await get_agent_conversation("user-2", "device-a", "term-1") is None
    assert await list_agent_conversation_events("user-2", "device-a", "term-1") == []


@pytest.mark.asyncio
async def test_configure_database_creates_instance():
    """configure_database 返回 Database 实例"""
    from app.store.database import configure_database, Database

    db = configure_database("/tmp/test_configure.db")
    assert isinstance(db, Database)
    assert db.db_path == "/tmp/test_configure.db"


@pytest.mark.asyncio
async def test_replace_and_get_pinned_projects_are_device_scoped(db_with_tables):
    """固定项目只按 user + device 生效。"""
    from app.store.database import (
        get_pinned_projects,
        replace_pinned_projects,
        save_user,
    )

    await save_user("erin", "hash")
    await replace_pinned_projects(
        "erin",
        "device-a",
        [
            {"label": "remote-control", "cwd": "/Users/demo/project/remote-control"},
            {"label": "ai-rules", "cwd": "/Users/demo/project/ai_rules"},
        ],
    )
    await replace_pinned_projects(
        "erin",
        "device-b",
        [{"label": "other", "cwd": "/Users/demo/project/other"}],
    )

    device_a_projects = await get_pinned_projects("erin", "device-a")
    device_b_projects = await get_pinned_projects("erin", "device-b")

    assert sorted(project["cwd"] for project in device_a_projects) == [
        "/Users/demo/project/ai_rules",
        "/Users/demo/project/remote-control",
    ]
    assert [project["cwd"] for project in device_b_projects] == [
        "/Users/demo/project/other",
    ]


@pytest.mark.asyncio
async def test_replace_and_get_scan_roots_persists_enabled_and_depth(db_with_tables):
    """扫描根目录配置支持 depth/enabled 持久化。"""
    from app.store.database import (
        get_approved_scan_roots,
        replace_approved_scan_roots,
        save_user,
    )

    await save_user("frank", "hash")
    await replace_approved_scan_roots(
        "frank",
        "device-a",
        [
            {"root_path": "/Users/demo/project", "scan_depth": 3, "enabled": True},
            {"root_path": "/Volumes/workspace", "scan_depth": 1, "enabled": False},
        ],
    )

    roots = await get_approved_scan_roots("frank", "device-a")

    assert [(root["root_path"], root["scan_depth"], root["enabled"]) for root in roots] == [
        ("/Users/demo/project", 3, 1),
        ("/Volumes/workspace", 1, 0),
    ]


@pytest.mark.asyncio
async def test_save_and_get_planner_config(db_with_tables):
    """planner 配置可按 user + device 持久化。"""
    from app.store.database import (
        get_planner_config,
        save_planner_config,
        save_user,
    )

    await save_user("gina", "hash")
    await save_planner_config(
        "gina",
        "device-a",
        {
            "provider": "llm",
            "llm_enabled": True,
            "endpoint_profile": "openai_compatible",
            "credentials_mode": "client_secure_storage",
            "requires_explicit_opt_in": True,
        },
    )

    config = await get_planner_config("gina", "device-a")

    assert config is not None
    assert config["provider"] == "llm"
    assert config["llm_enabled"] == 1
    assert config["credentials_mode"] == "client_secure_storage"


@pytest.mark.asyncio
async def test_save_and_get_assistant_planner_run(db_with_tables):
    """智能规划记录可按 user + device + conversation/message 持久化。"""
    from app.store.database import (
        get_assistant_planner_run,
        save_assistant_planner_run,
        save_user,
    )

    await save_user("harry", "hash")
    await save_assistant_planner_run(
        "harry",
        "device-a",
        {
            "conversation_id": "conv-1",
            "message_id": "msg-1",
            "intent": "进入 remote-control",
            "provider": "service_llm",
            "fallback_used": False,
            "fallback_reason": None,
            "assistant_messages": [{"type": "assistant", "text": "准备生成命令"}],
            "trace": [{"stage": "planner", "title": "规划", "status": "completed", "summary": "已完成"}],
            "command_sequence": {
                "summary": "进入项目并启动 Claude",
                "provider": "service_llm",
                "source": "intent",
                "need_confirm": True,
                "steps": [
                    {"id": "step_1", "label": "进入目录", "command": "cd /tmp/demo"},
                    {"id": "step_2", "label": "启动 Claude", "command": "claude"},
                ],
            },
            "evaluation_context": {
                "matched_candidate_id": "cand-1",
                "matched_cwd": "/tmp/demo",
                "matched_label": "demo",
            },
            "execution_status": "planned",
        },
    )

    row = await get_assistant_planner_run("harry", "device-a", "conv-1", "msg-1")

    assert row is not None
    assert row["intent"] == "进入 remote-control"
    assert row["provider"] == "service_llm"
    assert row["execution_status"] == "planned"
    assert "step_1" in row["command_sequence_json"]
    assert "cand-1" in row["evaluation_context_json"]


@pytest.mark.asyncio
async def test_report_assistant_execution_updates_memory_only_after_report(db_with_tables):
    """planner memory 只在收到执行结果回写后更新。"""
    from app.store.database import (
        list_assistant_planner_memory,
        report_assistant_execution,
        save_assistant_planner_run,
        save_user,
    )

    await save_user("ivy", "hash")
    await save_assistant_planner_run(
        "ivy",
        "device-a",
        {
            "conversation_id": "conv-1",
            "message_id": "msg-1",
            "intent": "进入 remote-control",
            "provider": "service_llm",
            "assistant_messages": [],
            "trace": [],
            "command_sequence": {
                "summary": "进入项目并启动 Claude",
                "provider": "service_llm",
                "source": "intent",
                "need_confirm": True,
                "steps": [
                    {"id": "step_1", "label": "进入目录", "command": "cd /Users/demo/project/remote-control"},
                    {"id": "step_2", "label": "启动 Claude", "command": "claude"},
                ],
            },
            "evaluation_context": {
                "matched_candidate_id": "cand-remote-control",
                "matched_cwd": "/Users/demo/project/remote-control",
                "matched_label": "remote-control",
            },
            "execution_status": "planned",
        },
    )

    assert await list_assistant_planner_memory("ivy", "device-a", "recent_project") == []
    assert await list_assistant_planner_memory("ivy", "device-a", "successful_sequence") == []

    await report_assistant_execution(
        "ivy",
        "device-a",
        "conv-1",
        "msg-1",
        execution_status="succeeded",
        terminal_id="term-1",
        failed_step_id=None,
        output_summary="已进入项目并启动 Claude",
        command_sequence={
            "summary": "进入项目并启动 Claude",
            "provider": "service_llm",
            "source": "intent",
            "need_confirm": True,
            "steps": [
                {"id": "step_1", "label": "进入目录", "command": "cd /Users/demo/project/remote-control"},
                {"id": "step_2", "label": "启动 Claude", "command": "claude"},
            ],
        },
    )

    recent_projects = await list_assistant_planner_memory("ivy", "device-a", "recent_project")
    successful_sequences = await list_assistant_planner_memory("ivy", "device-a", "successful_sequence")

    assert len(recent_projects) == 1
    assert recent_projects[0]["cwd"] == "/Users/demo/project/remote-control"
    assert recent_projects[0]["success_count"] == 1
    assert len(successful_sequences) == 1
    assert successful_sequences[0]["last_status"] == "succeeded"


@pytest.mark.asyncio
async def test_report_assistant_execution_is_device_scoped_and_idempotent(db_with_tables):
    """重复回写不会重复写 memory，且不同 device 不会串用。"""
    from app.store.database import (
        list_assistant_planner_memory,
        report_assistant_execution,
        save_assistant_planner_run,
        save_user,
    )

    await save_user("jane", "hash")
    await save_assistant_planner_run(
        "jane",
        "device-a",
        {
            "conversation_id": "conv-1",
            "message_id": "msg-1",
            "intent": "进入 ai_rules",
            "provider": "service_llm",
            "assistant_messages": [],
            "trace": [],
            "command_sequence": {
                "summary": "进入 ai_rules",
                "provider": "service_llm",
                "source": "intent",
                "need_confirm": True,
                "steps": [
                    {"id": "step_1", "label": "进入目录", "command": "cd /Users/demo/project/ai_rules"},
                ],
            },
            "evaluation_context": {
                "matched_candidate_id": "cand-ai-rules",
                "matched_cwd": "/Users/demo/project/ai_rules",
                "matched_label": "ai_rules",
            },
            "execution_status": "planned",
        },
    )

    first = await report_assistant_execution(
        "jane",
        "device-a",
        "conv-1",
        "msg-1",
        execution_status="failed",
        terminal_id="term-1",
        failed_step_id="step_1",
        output_summary="目录不存在",
        command_sequence={
            "summary": "进入 ai_rules",
            "provider": "service_llm",
            "source": "intent",
            "need_confirm": True,
            "steps": [
                {"id": "step_1", "label": "进入目录", "command": "cd /Users/demo/project/ai_rules"},
            ],
        },
    )
    second = await report_assistant_execution(
        "jane",
        "device-a",
        "conv-1",
        "msg-1",
        execution_status="failed",
        terminal_id="term-1",
        failed_step_id="step_1",
        output_summary="目录不存在",
        command_sequence={
            "summary": "进入 ai_rules",
            "provider": "service_llm",
            "source": "intent",
            "need_confirm": True,
            "steps": [
                {"id": "step_1", "label": "进入目录", "command": "cd /Users/demo/project/ai_rules"},
            ],
        },
    )

    failures_a = await list_assistant_planner_memory("jane", "device-a", "recent_failure")
    failures_b = await list_assistant_planner_memory("jane", "device-b", "recent_failure")

    assert first is not None
    assert second is not None
    assert len(failures_a) == 1
    assert failures_a[0]["failure_count"] == 1
    assert failures_b == []

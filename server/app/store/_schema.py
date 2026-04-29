"""数据库表结构定义（DDL）。

所有 CREATE TABLE / CREATE INDEX / ALTER 语句集中在此，
由 Database.init_db() 统一执行。
"""


SCHEMA_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS user_devices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL REFERENCES users(username),
        device_name TEXT,
        device_type TEXT DEFAULT 'mobile',
        bound_at TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_user_devices_username ON user_devices(username)",
    """CREATE TABLE IF NOT EXISTS project_source_pinned_projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL REFERENCES users(username),
        device_id TEXT NOT NULL,
        label TEXT NOT NULL,
        cwd TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(username, device_id, cwd)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_pinned_projects_scope ON project_source_pinned_projects(username, device_id)",
    """CREATE TABLE IF NOT EXISTS project_source_scan_roots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL REFERENCES users(username),
        device_id TEXT NOT NULL,
        root_path TEXT NOT NULL,
        scan_depth INTEGER NOT NULL DEFAULT 2,
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(username, device_id, root_path)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_scan_roots_scope ON project_source_scan_roots(username, device_id)",
    """CREATE TABLE IF NOT EXISTS project_source_planner_configs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL REFERENCES users(username),
        device_id TEXT NOT NULL,
        provider TEXT NOT NULL DEFAULT 'claude_cli',
        llm_enabled INTEGER NOT NULL DEFAULT 1,
        endpoint_profile TEXT NOT NULL DEFAULT 'openai_compatible',
        credentials_mode TEXT NOT NULL DEFAULT 'client_secure_storage',
        requires_explicit_opt_in INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(username, device_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_planner_configs_scope ON project_source_planner_configs(username, device_id)",
    """CREATE TABLE IF NOT EXISTS assistant_planner_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL REFERENCES users(username),
        device_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        message_id TEXT NOT NULL,
        intent TEXT NOT NULL,
        provider TEXT NOT NULL,
        fallback_used INTEGER NOT NULL DEFAULT 0,
        fallback_reason TEXT,
        matched_candidate_id TEXT,
        matched_cwd TEXT,
        matched_label TEXT,
        assistant_messages_json TEXT NOT NULL DEFAULT '[]',
        trace_json TEXT NOT NULL DEFAULT '[]',
        command_sequence_json TEXT,
        evaluation_context_json TEXT NOT NULL DEFAULT '{}',
        execution_status TEXT NOT NULL DEFAULT 'planned',
        terminal_id TEXT,
        failed_step_id TEXT,
        output_summary TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(username, device_id, conversation_id, message_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_assistant_runs_scope ON assistant_planner_runs(username, device_id, created_at DESC)",
    """CREATE TABLE IF NOT EXISTS assistant_planner_memory_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL REFERENCES users(username),
        device_id TEXT NOT NULL,
        memory_type TEXT NOT NULL,
        memory_key TEXT NOT NULL,
        label TEXT,
        cwd TEXT,
        summary TEXT,
        command_sequence_json TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        success_count INTEGER NOT NULL DEFAULT 0,
        failure_count INTEGER NOT NULL DEFAULT 0,
        last_status TEXT NOT NULL DEFAULT 'unknown',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(username, device_id, memory_type, memory_key)
    )""",
    """CREATE INDEX IF NOT EXISTS idx_assistant_memory_scope
       ON assistant_planner_memory_entries(username, device_id, memory_type, updated_at DESC)""",
    """CREATE TABLE IF NOT EXISTS project_aliases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        device_id TEXT NOT NULL,
        alias TEXT NOT NULL,
        path TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(user_id, device_id, alias)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_project_aliases_user_device ON project_aliases(user_id, device_id)",
    """CREATE TABLE IF NOT EXISTS agent_execution_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        device_id TEXT NOT NULL,
        success INTEGER NOT NULL,
        executed_command TEXT,
        failure_step TEXT,
        aliases_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        UNIQUE(session_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_agent_execution_reports_user_device ON agent_execution_reports(user_id, device_id, created_at DESC)",
    """CREATE TABLE IF NOT EXISTS agent_usage_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL UNIQUE,
        user_id TEXT NOT NULL,
        device_id TEXT NOT NULL,
        input_tokens INTEGER NOT NULL DEFAULT 0,
        output_tokens INTEGER NOT NULL DEFAULT 0,
        total_tokens INTEGER NOT NULL DEFAULT 0,
        requests INTEGER NOT NULL DEFAULT 0,
        model_name TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_agent_usage_records_user_device ON agent_usage_records(user_id, device_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_agent_usage_records_user_created_at ON agent_usage_records(user_id, created_at DESC, id DESC)",
    """CREATE TABLE IF NOT EXISTS agent_conversations (
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
    )""",
    "CREATE INDEX IF NOT EXISTS idx_agent_conversations_scope ON agent_conversations(user_id, device_id, terminal_id)",
    """CREATE TABLE IF NOT EXISTS agent_conversation_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT NOT NULL REFERENCES agent_conversations(conversation_id) ON DELETE CASCADE,
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
    )""",
    "CREATE INDEX IF NOT EXISTS idx_agent_conversation_events_conversation ON agent_conversation_events(conversation_id, event_index)",
    """CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_conversation_events_client_event
       ON agent_conversation_events(conversation_id, client_event_id)
       WHERE client_event_id IS NOT NULL""",
    """CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_conversation_events_answer_question
       ON agent_conversation_events(conversation_id, question_id)
       WHERE event_type = 'answer' AND question_id IS NOT NULL""",
]

# 增量迁移语句
MIGRATION_STATEMENTS = [
    "ALTER TABLE agent_conversations ADD COLUMN truncation_epoch INTEGER DEFAULT 0",
    "ALTER TABLE agent_usage_records ADD COLUMN terminal_id TEXT DEFAULT ''",
]

"""
API 路由定义
"""
from fastapi import APIRouter, WebSocket, Query

from app.ws_agent import agent_websocket_handler
from app.ws_client import client_websocket_handler
from app.history_api import router as history_router
from app.user_api import router as user_router
from app.log_api import router as log_router
from app.runtime_api import router as runtime_router
from app.feedback_api import router as feedback_router

router = APIRouter()

# WebSocket 路由
@router.websocket("/ws/agent")
async def agent_ws_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
):
    """Agent WebSocket 端点"""
    await agent_websocket_handler(websocket, token)


@router.websocket("/ws/client")
async def client_ws_endpoint(
    websocket: WebSocket,
    session_id: str | None = Query(None),
    token: str = Query(...),
    view: str = Query("mobile"),
    device_id: str | None = Query(None),
    terminal_id: str | None = Query(None),
):
    """Client WebSocket 端点"""
    if (not session_id and not device_id) or not token:
        await websocket.close(code=4001, reason="session_id/device_id and token required")
        return

    await client_websocket_handler(
        websocket,
        session_id,
        token,
        view,
        device_id=device_id,
        terminal_id=terminal_id,
    )

# REST API 路由
router.include_router(history_router, prefix="/api")
router.include_router(user_router, prefix="/api")
router.include_router(log_router, prefix="/api")
router.include_router(runtime_router, prefix="/api")
router.include_router(feedback_router, prefix="/api")

"""
共享 httpx 异步客户端单例

供 log_api、feedback_api 等需要代理转发的模块复用。
"""
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)

_http_client: Optional[Any] = None


def get_shared_http_client():
    """获取或创建 httpx.AsyncClient 单例"""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        import httpx
        _http_client = httpx.AsyncClient(timeout=3.0)
    return _http_client


async def close_shared_http_client() -> None:
    """关闭 httpx.AsyncClient 单例（供 lifespan shutdown 调用）。"""
    global _http_client
    if _http_client and not _http_client.is_closed:
        try:
            await _http_client.aclose()
        except Exception:
            pass
        _http_client = None

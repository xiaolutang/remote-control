import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ws_client import ClientConnection, active_clients, client_websocket_handler


async def _cancelled_iter_text():
    if False:
        yield ""
    raise asyncio.CancelledError


@pytest.mark.asyncio
async def test_same_view_different_terminals_do_not_kick_each_other():
    active_clients.clear()

    mock_ws_existing = AsyncMock()
    existing_client = ClientConnection(
        "session-1",
        mock_ws_existing,
        view_type="desktop",
        terminal_id="term-1",
    )
    active_clients["session-1:term-1"] = [existing_client]

    mock_ws_new = AsyncMock()
    mock_ws_new.receive_text = AsyncMock(
        return_value=json.dumps({"type": "auth", "token": "desktop-token"})
    )
    mock_ws_new.iter_text = MagicMock(return_value=_cancelled_iter_text())
    mock_ws_new.headers = {"x-forwarded-proto": "https"}

    terminal_state = {
        "terminal_id": "term-2",
        "status": "live",
        "views": {"mobile": 0, "desktop": 1},
        "geometry_owner_view": "desktop",
        "attach_epoch": 1,
        "recovery_epoch": 1,
        "pty": {"rows": 24, "cols": 80},
    }

    with patch("app.ws_client.wait_for_ws_auth", new=AsyncMock(return_value=(
        {"session_id": "session-1", "sub": "user1"},
        {"type": "auth", "token": "desktop-token"},
    ))):
        with patch("app.ws_client.get_session", return_value={
            "session_id": "session-1",
            "owner": "user1",
            "device": {"device_id": "mbp-01"},
        }):
            with patch("app.ws_client.get_session_terminal", new=AsyncMock(return_value={
                "terminal_id": "term-2",
                "status": "live",
                "pty": {"rows": 24, "cols": 80},
            })):
                with patch("app.ws_client.is_agent_connected", return_value=True):
                    with patch(
                        "app.ws_client.update_session_view_count",
                        new_callable=AsyncMock,
                    ):
                        with patch(
                            "app.ws_client.update_session_terminal_views",
                            new=AsyncMock(return_value=terminal_state),
                        ):
                            with patch(
                                "app.ws_client.request_agent_terminal_snapshot",
                                new=AsyncMock(return_value=None),
                            ):
                                with patch(
                                    "app.ws_client.get_terminal_output_history",
                                    new=AsyncMock(return_value=[]),
                                ):
                                    with patch(
                                        "app.ws_client._broadcast_presence",
                                        new_callable=AsyncMock,
                                    ):
                                        try:
                                            await client_websocket_handler(
                                                mock_ws_new,
                                                "session-1",
                                                view="desktop",
                                                terminal_id="term-2",
                                            )
                                        except asyncio.CancelledError:
                                            pass

    mock_ws_existing.send_json.assert_not_called()
    mock_ws_existing.close.assert_not_called()

    first_msg = mock_ws_new.send_json.call_args_list[0][0][0]
    assert first_msg["type"] == "connected"
    assert first_msg["terminal_id"] == "term-2"

    active_clients.clear()


@pytest.mark.asyncio
async def test_same_view_same_terminal_still_kicks_old_client():
    active_clients.clear()

    mock_ws_existing = AsyncMock()
    existing_client = ClientConnection(
        "session-1",
        mock_ws_existing,
        view_type="desktop",
        terminal_id="term-1",
    )
    active_clients["session-1:term-1"] = [existing_client]

    mock_ws_new = AsyncMock()
    mock_ws_new.receive_text = AsyncMock(
        return_value=json.dumps({"type": "auth", "token": "desktop-token"})
    )
    mock_ws_new.iter_text = MagicMock(return_value=_cancelled_iter_text())
    mock_ws_new.headers = {"x-forwarded-proto": "https"}

    terminal_state = {
        "terminal_id": "term-1",
        "status": "live",
        "views": {"mobile": 0, "desktop": 1},
        "geometry_owner_view": "desktop",
        "attach_epoch": 2,
        "recovery_epoch": 2,
        "pty": {"rows": 24, "cols": 80},
    }

    with patch("app.ws_client.wait_for_ws_auth", new=AsyncMock(return_value=(
        {"session_id": "session-1", "sub": "user1"},
        {"type": "auth", "token": "desktop-token"},
    ))):
        with patch("app.ws_client.get_session", return_value={
            "session_id": "session-1",
            "owner": "user1",
            "device": {"device_id": "mbp-01"},
        }):
            with patch("app.ws_client.get_session_terminal", new=AsyncMock(return_value={
                "terminal_id": "term-1",
                "status": "live",
                "pty": {"rows": 24, "cols": 80},
            })):
                with patch("app.ws_client.is_agent_connected", return_value=True):
                    with patch(
                        "app.ws_client.update_session_view_count",
                        new_callable=AsyncMock,
                    ):
                        with patch(
                            "app.ws_client.update_session_terminal_views",
                            new=AsyncMock(return_value=terminal_state),
                        ):
                            with patch(
                                "app.ws_client.request_agent_terminal_snapshot",
                                new=AsyncMock(return_value=None),
                            ):
                                with patch(
                                    "app.ws_client.get_terminal_output_history",
                                    new=AsyncMock(return_value=[]),
                                ):
                                    with patch(
                                        "app.ws_client._broadcast_presence",
                                        new_callable=AsyncMock,
                                    ):
                                        try:
                                            await client_websocket_handler(
                                                mock_ws_new,
                                                "session-1",
                                                view="desktop",
                                                terminal_id="term-1",
                                            )
                                        except asyncio.CancelledError:
                                            pass

    mock_ws_existing.send_json.assert_called()
    kicked_msg = mock_ws_existing.send_json.call_args[0][0]
    assert kicked_msg["type"] == "device_kicked"
    assert kicked_msg["reason"] == "replaced_by_new_device"
    mock_ws_existing.close.assert_called_once()

    first_msg = mock_ws_new.send_json.call_args_list[0][0][0]
    assert first_msg["type"] == "connected"
    assert first_msg["terminal_id"] == "term-1"

    active_clients.clear()

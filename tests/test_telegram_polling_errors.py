import asyncio
import socket
import ssl
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

from engine.server.telegram_bot import (
    TelegramBot,
    is_network_offline_error,
    is_transient_polling_timeout,
)


def _http(code: int) -> HTTPError:
    return HTTPError("https://api.telegram.org/x", code, "msg", {}, None)


def test_server_side_http_errors_are_transient():
    for code in (429, 500, 502, 503, 504):
        assert is_transient_polling_timeout(_http(code)), code


def test_client_http_errors_are_not_transient():
    for code in (400, 401, 404, 409):
        assert not is_transient_polling_timeout(_http(code)), code


def test_connection_errors_still_transient():
    assert is_transient_polling_timeout(TimeoutError())
    assert is_transient_polling_timeout(URLError(ConnectionResetError()))
    assert not is_transient_polling_timeout(ValueError())


def test_network_offline_errors_detected():
    assert is_network_offline_error(socket.gaierror(11001, "getaddrinfo failed"))
    assert is_network_offline_error(URLError(socket.gaierror(11001, "getaddrinfo failed")))
    assert is_network_offline_error(URLError(OSError(10051, "Network is unreachable")))
    assert is_network_offline_error(URLError(ssl.SSLError("certificate verify failed")))
    assert not is_network_offline_error(ValueError("Invalid format"))
    assert not is_network_offline_error(KeyError("missing_key"))


@pytest.mark.asyncio
async def test_telegram_bot_offline_handling_reconnects_when_restored():
    bot = TelegramBot("dummy_token", {12345}, None)
    call_count = 0

    def mock_check():
        nonlocal call_count
        call_count += 1
        return call_count >= 2

    bot._check_connectivity = mock_check

    async def mock_wait_for(coro, timeout):
        coro.close()
        raise TimeoutError()

    with patch("asyncio.wait_for", side_effect=mock_wait_for):
        await bot._handle_network_offline(socket.gaierror(11001, "getaddrinfo failed"))

    assert bot._is_offline is False
    assert call_count >= 2


@pytest.mark.asyncio
async def test_telegram_bot_offline_handling_respects_stop_event():
    bot = TelegramBot("dummy_token", {12345}, None)
    bot._stop_event.set()
    bot._check_connectivity = lambda: False

    await bot._handle_network_offline(socket.gaierror(11001, "getaddrinfo failed"))
    assert bot._stop_event.is_set()

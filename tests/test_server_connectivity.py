import pytest
from unittest.mock import patch
from engine.server.llm_server import (
    check_llm_server,
    check_embed_server,
    get_embed_client,
    call_llm,
)


@pytest.mark.asyncio
async def test_llm_server_offline_reports_waiting_status():
    """Khi máy chủ LLM (cổng 8080) chưa mở, báo trạng thái chờ kết nối rõ ràng."""
    with patch("engine.server.llm_server.is_port_open", return_value=False):
        online, msg, port = check_llm_server(force=True)
        assert online is False
        assert port == 8080
        assert "chưa hoạt động" in msg
        assert "chờ kết nối" in msg
        assert "8080" in msg


@pytest.mark.asyncio
async def test_embed_server_offline_reports_waiting_status():
    """Khi máy chủ Embed (cổng 8081) chưa mở, báo trạng thái chờ kết nối rõ ràng."""
    with patch("engine.server.llm_server.is_port_open", return_value=False):
        online, msg, port = check_embed_server(force=True)
        assert online is False
        assert port == 8081
        assert "chưa hoạt động" in msg
        assert "chờ kết nối" in msg
        assert "8081" in msg


@pytest.mark.asyncio
async def test_get_embed_client_returns_none_when_server_offline():
    """Không spam khởi tạo embed client khi cổng 8081 chưa hoạt động."""
    with patch("engine.server.llm_server.is_port_open", return_value=False):
        client = get_embed_client()
        assert client is None


@pytest.mark.asyncio
async def test_call_llm_stops_spam_when_server_offline():
    """Ngừng spam connect khi máy chủ LLM chưa hoạt động, ném lỗi rõ ràng."""
    with patch("engine.server.llm_server.is_port_open", return_value=False):
        with pytest.raises(ConnectionError) as exc_info:
            await call_llm([{"role": "user", "content": "hello"}])
        assert "Máy chủ LLM cổng 8080 chưa hoạt động" in str(exc_info.value)
        assert "chờ kết nối" in str(exc_info.value)


@pytest.mark.asyncio
async def test_server_online_normal_operation():
    """Khi máy chủ đã kết nối thành công, báo trạng thái hoạt động bình thường."""
    with patch("engine.server.llm_server.is_port_open", return_value=True):
        llm_online, llm_msg, llm_port = check_llm_server(force=True)
        assert llm_online is True
        assert "đang hoạt động bình thường" in llm_msg

        embed_online, embed_msg, embed_port = check_embed_server(force=True)
        assert embed_online is True
        assert "đang hoạt động bình thường" in embed_msg


@pytest.mark.asyncio
async def test_ui_health_detailed_shows_waiting_connection():
    """API health_detailed hiển thị 'chờ kết nối' khi máy chủ chưa mở."""
    from engine.UIUX.ui_engine import health_detailed
    with patch("engine.server.llm_server.is_port_open", return_value=False):
        res = await health_detailed()
        assert "llm" in res
        assert res["llm"]["status"] == "chờ kết nối"
        assert res["llm"]["port"] == 8080
        assert "chưa hoạt động" in res["llm"]["message"]

        assert "embed" in res
        assert res["embed"]["status"] == "chờ kết nối"
        assert res["embed"]["port"] == 8081
        assert "chưa hoạt động" in res["embed"]["message"]

        assert "stream_tts" in res
        assert res["stream_tts"]["status"] == "chờ kết nối"
        assert res["stream_tts"]["port"] == 8082
        assert "chưa hoạt động" in res["stream_tts"]["message"]


@pytest.mark.asyncio
async def test_stream_tts_server_offline_reports_waiting_status():
    """Khi máy chủ stream_TTS (cổng 8082) chưa mở, báo trạng thái chờ kết nối rõ ràng."""
    from engine.server.llm_server import check_stream_tts_server
    with patch("engine.server.llm_server.is_port_open", return_value=False):
        online, msg, port = check_stream_tts_server(force=True)
        assert online is False
        assert port == 8082
        assert "chưa hoạt động" in msg
        assert "chờ kết nối" in msg
        assert "8082" in msg


@pytest.mark.asyncio
async def test_ui_tts_voices_returns_waiting_status_when_offline():
    """Endpoint api_tts_voices trả về trạng thái chờ kết nối không bị treo timeout khi 8082 chưa mở."""
    from engine.UIUX.ui_engine import _tts_voices_call
    with patch("engine.server.tts_manager._resolve_tts_engine", return_value="vieneu"), \
         patch("engine.server.llm_server.is_port_open", return_value=False):
        res = await _tts_voices_call("GET")
        assert res["status"] == "chờ kết nối"
        assert "8082" in res["message"]


@pytest.mark.asyncio
async def test_synthesize_speech_skips_spam_when_stream_tts_offline():
    """synthesize_speech với vieneu dừng ngay khi cổng 8082 chưa mở, không spam connect."""
    from engine.server.tts_manager import synthesize_speech
    with patch("engine.server.tts_manager._resolve_tts_engine", return_value="vieneu"), \
         patch("engine.server.llm_server.is_port_open", return_value=False):
        audio = await synthesize_speech("Xin chào người dùng")
        assert audio is None


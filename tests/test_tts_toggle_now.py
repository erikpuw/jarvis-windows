"""Nút TTS (và trình phát media) phải có tác dụng NGAY, kể cả khi đang giữa một lượt trả lời.

Trước đây toggle_tts / media_state chỉ được xếp vào message_queue, mà vòng lặp chính đang await generate_response_stream nên không đọc queue
cho tới khi lượt cũ xong: bấm tắt TTS mà luồng TTS vẫn chạy tiếp hết lượt. Giờ ws_reader (task chạy song song, như "cancel") đặt cờ ngay:
`_apply_tts_gate_now(ws, msg)` cập nhật user_tts_disabled / media_active và ws.tts_disabled (voice_streamer, tts_manager đều poll cờ này).
Nó KHÔNG đặt cancel_requested: tắt tiếng không được giết luôn phần chữ đang stream. Vòng lặp chính vẫn xử lý tin như cũ khi rảnh.

Run: python -m pytest tests/test_tts_toggle_now.py
"""
import re
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _ws(**kw):
    return types.SimpleNamespace(user_tts_disabled=False, media_active=False, tts_disabled=False, cancel_requested=False, **kw)


def test_turning_tts_off_blocks_tts_at_once_without_cancelling_the_text():
    import server
    ws = _ws()
    server._apply_tts_gate_now(ws, {"type": "toggle_tts", "enabled": False})
    assert ws.user_tts_disabled is True and ws.tts_disabled is True
    assert ws.cancel_requested is False  # the answer keeps streaming as text


def test_turning_tts_on_again_reopens_the_gate():
    import server
    ws = _ws()
    server._apply_tts_gate_now(ws, {"type": "toggle_tts", "enabled": False})
    server._apply_tts_gate_now(ws, {"type": "toggle_tts", "enabled": True})
    assert ws.user_tts_disabled is False and ws.tts_disabled is False


def test_media_blocks_tts_at_once_and_a_disabled_button_stays_disabled_after_media():
    import server
    ws = _ws()
    server._apply_tts_gate_now(ws, {"type": "media_state", "active": True})
    assert ws.media_active is True and ws.tts_disabled is True and ws.cancel_requested is False
    server._apply_tts_gate_now(ws, {"type": "media_state", "active": False})
    assert ws.tts_disabled is False
    ws2 = _ws()
    server._apply_tts_gate_now(ws2, {"type": "toggle_tts", "enabled": False})
    server._apply_tts_gate_now(ws2, {"type": "media_state", "active": True})
    server._apply_tts_gate_now(ws2, {"type": "media_state", "active": False})
    assert ws2.tts_disabled is True  # the button is still off


def test_other_messages_are_ignored():
    import server
    ws = _ws()
    server._apply_tts_gate_now(ws, {"type": "text", "text": "xin chào"})
    server._apply_tts_gate_now(ws, {"type": "cancel"})
    assert ws.tts_disabled is False and ws.user_tts_disabled is False and ws.media_active is False


def test_ws_reader_applies_it_before_queueing_the_message():
    src = (Path(__file__).parent.parent / "server.py").read_text(encoding="utf-8")
    reader = src[src.index("async def ws_reader():"):src.index("reader_task = asyncio.create_task(ws_reader())")]
    call = reader.index("_apply_tts_gate_now(ws, msg)")
    put = reader.index("await message_queue.put(msg)")
    assert call < put, "the gate must be set in the reader task, not only when the busy main loop reaches the queued message"
    assert re.search(r"toggle_tts|media_state", src[src.index("def _apply_tts_gate_now"):src.index("async def _watch_vieneu_warmup")])

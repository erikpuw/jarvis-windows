"""output_file: tool tạo tệp phải đưa được về frontend Telegram (xem + tải về).

Run: python -m pytest tests/test_output_delivery.py -q
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.core import output_delivery as od
from engine.server.telegram_bot import (
    TELEGRAM_DOCUMENT_MAX_BYTES,
    TELEGRAM_PHOTO_MAX_BYTES,
    TelegramBot,
    TelegramSession,
)


class FakeWs:
    def __init__(self):
        self.sent = []

    async def send_json(self, data):
        self.sent.append(data)


class BrokenWs:
    async def send_json(self, data):
        raise RuntimeError("socket closed")


def test_image_path_is_sent_as_kind_image():
    ws = FakeWs()
    ok = asyncio.run(od.deliver_output_file(ws, r"C:\tmp\anh_upscaled.png", caption="x"))
    assert ok is True
    payload = ws.sent[-1]
    assert payload["type"] == "output_file"
    assert payload["kind"] == "image"
    assert payload["name"] == "anh_upscaled.png"
    assert payload["caption"] == "x"


def test_office_document_is_kind_document_not_image():
    ws = FakeWs()
    for name in ("bao_cao.docx", "so_lieu.xlsx", "slide.pptx"):
        asyncio.run(od.deliver_output_file(ws, rf"C:\out\{name}"))
        assert ws.sent[-1]["kind"] == "document", name
        assert ws.sent[-1]["name"] == name


def test_missing_ws_or_path_returns_false_without_raising():
    assert asyncio.run(od.deliver_output_file(None, r"C:\a.png")) is False
    assert asyncio.run(od.deliver_output_file(FakeWs(), "")) is False
    assert asyncio.run(od.deliver_output_file(FakeWs(), None)) is False


def test_ws_without_send_json_is_reported_not_raised():
    assert asyncio.run(od.deliver_output_file(object(), r"C:\a.png")) is False


def test_send_failure_is_swallowed_so_tool_result_survives():
    assert asyncio.run(od.deliver_output_file(BrokenWs(), r"C:\a.png")) is False


def test_kind_can_be_forced_to_document():
    ws = FakeWs()
    asyncio.run(od.deliver_output_file(ws, r"C:\a.png", kind="document"))
    assert ws.sent[-1]["kind"] == "document"


# --- URL tải xuống + bí danh token --------------------------------------


def test_payload_carries_view_and_download_urls():
    ws = FakeWs()
    asyncio.run(od.deliver_output_file(ws, r"C:\out\ba_cao.docx"))
    payload = ws.sent[-1]
    assert payload["url"].startswith("/api/outputs/")
    assert payload["download_url"] == payload["url"] + "?download=1"
    assert payload["ext"] == "docx"
    assert payload["label"] == "Word"
    # Token là bí danh ngẫu nhiên: không được để lộ đường dẫn hay tên tệp.
    assert "ba_cao" not in payload["url"] and "C:" not in payload["url"]


def test_office_labels_word_excel_powerpoint_pdf():
    expected = {
        "so_lieu.xlsx": "Excel",
        "slide.pptx": "PowerPoint",
        "phan_tich.pdf": "PDF",
        "anh.png": "",
    }
    for name, label in expected.items():
        assert od.file_label(rf"C:\out\{name}") == label, name


def test_lookup_token_resolves_path_and_unknown_token_is_none():
    ws = FakeWs()
    asyncio.run(od.deliver_output_file(ws, r"C:\out\so_lieu.xlsx"))
    token = ws.sent[-1]["url"].rsplit("/", 1)[1]
    assert od.lookup_output_file(token) == Path(r"C:\out\so_lieu.xlsx")
    assert od.lookup_output_file("khong-ton-tai") is None
    assert od.lookup_output_file("") is None


def test_output_route_serves_file_and_404_for_unknown_token(tmp_path):
    """GET /api/outputs/{token}: download=1 buộc attachment, token lạ trả 404."""
    from engine.UIUX.ui_engine import api_output_file

    target = tmp_path / "anh_da_upscale.png"
    target.write_bytes(b"png")
    token = od._register(target)

    served = asyncio.run(api_output_file(token, download=1))
    assert served.status_code == 200
    assert served.path == str(target)
    assert "attachment" in served.headers.get("content-disposition", "")
    assert "anh_da_upscale.png" in served.headers["content-disposition"]

    inline = asyncio.run(api_output_file(token))
    assert inline.status_code == 200
    assert "attachment" not in inline.headers.get("content-disposition", "")

    missing = asyncio.run(api_output_file("khong-ton-tai"))
    assert missing.status_code == 404


def test_upscale_action_pushes_the_result_image_to_the_frontend(tmp_path, monkeypatch):
    """catalog.files.upscale_image: ảnh vừa upscale phải được bắn về ws, không chỉ trả đường dẫn."""
    from types import SimpleNamespace
    from engine.tools import registry, image_engine

    out = tmp_path / "anh_upscaled.png"
    out.write_bytes(b"png")

    async def fake_upscale(**kwargs):
        return str(out)

    monkeypatch.setattr(image_engine, "upscale_image", fake_upscale)
    ws = FakeWs()
    att = SimpleNamespace(resolved_path=tmp_path / "goc.jpg", filename="goc.jpg", extension=".jpg")
    ctx = registry.ToolContext(ws=ws, send_json=ws.send_json, attachment_context=att)
    res = asyncio.run(registry.run("upscale_image", {}, ctx))
    result = res.text
    assert out.name in result
    assert str(tmp_path) not in result
    files = [m for m in ws.sent if m.get("type") == "output_file"]
    assert files and files[0]["kind"] == "image"
    assert files[0]["path"] == str(out)
    assert files[0]["url"].startswith("/api/outputs/")
    assert files[0]["download_url"].endswith("?download=1")


def test_upscale_error_does_not_emit_output_file(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from engine.tools import registry, image_engine

    async def fake_upscale(**kwargs):
        return "Lỗi: Không tìm thấy upscayl-bin.exe"

    monkeypatch.setattr(image_engine, "upscale_image", fake_upscale)
    ws = FakeWs()
    att = SimpleNamespace(resolved_path=tmp_path / "x.jpg", filename="x.jpg", extension=".jpg")
    ctx = registry.ToolContext(ws=ws, send_json=ws.send_json, attachment_context=att)
    res = asyncio.run(registry.run("upscale_image", {}, ctx))
    result = res.text
    assert result.startswith("Lỗi")
    assert [m for m in ws.sent if m.get("type") == "output_file"] == []


def test_upscale_without_ws_still_answers_with_name_only(monkeypatch, tmp_path):
    """Web/agent chạy nền không có ws: không lỗi vì thiếu kênh gửi, câu trả lời
    vẫn chỉ nêu tên tệp — không in đường dẫn máy chủ ra chat."""
    from types import SimpleNamespace
    from engine.tools import registry, image_engine

    out = tmp_path / "a.png"
    out.write_bytes(b"png")

    async def fake_upscale(**kwargs):
        return str(out)

    monkeypatch.setattr(image_engine, "upscale_image", fake_upscale)
    att = SimpleNamespace(resolved_path=tmp_path / "x.jpg", filename="x.jpg", extension=".jpg")
    ctx = registry.ToolContext(ws=None, attachment_context=att)
    res = asyncio.run(registry.run("upscale_image", {}, ctx))
    result = res.text
    assert out.name in result
    assert str(tmp_path) not in result
    assert not result.startswith("Lỗi")


# --- Telegram side -------------------------------------------------------


def _bot() -> TelegramBot:
    return TelegramBot("token", {1}, SimpleNamespace())


def test_session_routes_output_file_to_bot():
    seen = {}

    async def fake_send(chat_id, payload):
        seen["chat_id"] = chat_id
        seen["payload"] = payload

    bot = _bot()
    bot._send_output_file = fake_send
    session = TelegramSession(bot, 7)
    payload = {"type": "output_file", "path": r"C:\a.png", "kind": "image"}
    asyncio.run(session.send_json(payload))
    assert seen["chat_id"] == 7
    assert seen["payload"]["kind"] == "image"


def test_upscale_preview_is_pure_and_download_waits_for_final_reply(tmp_path, monkeypatch):
    """Khung xem trước thuần túy (photo không caption, không tin rời); lượt
    tải chờ gắn nút ⬇ vào tin phản hồi cuối, không gửi thêm gì khác."""
    image = tmp_path / "anh.png"
    image.write_bytes(b"png-bytes")

    bot = _bot()
    posts = []
    monkeypatch.setattr(
        bot,
        "_post_file",
        lambda chat_id, path, **kw: posts.append((kw["method"], kw.get("caption"))),
    )
    requests = []

    async def fake_request(method, payload):
        requests.append((method, payload))
        return {"ok": True}

    monkeypatch.setattr(bot, "_request", fake_request)
    token = od._register(image)
    asyncio.run(
        bot._send_output_file(
            1, {"path": str(image), "kind": "image", "url": f"/api/outputs/{token}"}
        )
    )
    assert posts == [("sendPhoto", None)]
    assert requests == []
    assert bot._take_pending_download(1) == ("anh.png", token)
    assert bot._take_pending_download(1) is None


def test_final_reply_carries_the_lone_download_button(monkeypatch):
    """Tin phản hồi cuối gắn đúng một nút icon ⬇ (không thêm chữ nào)."""
    bot = _bot()
    requests = []

    async def fake_request(method, payload):
        requests.append((method, payload))
        return {"ok": True}

    monkeypatch.setattr(bot, "_request", fake_request)
    asyncio.run(
        bot._send_text(
            1, "câu trả lời", reply_markup=TelegramBot._download_keyboard("tok123")
        )
    )
    assert len(requests) == 1
    method, payload = requests[0]
    assert method == "sendMessage"
    assert payload["text"] == "câu trả lời"
    assert payload["reply_markup"]["inline_keyboard"] == [
        [{"text": "⬇", "callback_data": "jarvis:dl:tok123"}]
    ]
    assert TelegramBot._download_keyboard("") is None


def test_office_file_is_sent_only_as_document(tmp_path, monkeypatch):
    doc = tmp_path / "don_xin_viec.docx"
    doc.write_bytes(b"docx-bytes")

    bot = _bot()
    posts = []
    monkeypatch.setattr(
        bot,
        "_post_file",
        lambda chat_id, path, **kw: posts.append((kw["method"], kw["field"])),
    )
    asyncio.run(bot._send_output_file(1, {"path": str(doc), "kind": "document"}))
    assert posts == [("sendDocument", "document")]


def test_oversized_image_is_sent_as_photo_preview_not_document(tmp_path, monkeypatch):
    """Ảnh vượt trần photo (upscale 4x PNG hầu như luôn >10MB): chat vẫn hiện
    ảnh qua bản xem JPEG nhẹ, không rớt xuống mục tên tệp document."""
    preview = tmp_path / "xem_truoc.jpg"
    preview.write_bytes(b"jpeg-bytes")
    image = tmp_path / "anh_upscaled.png"
    image.write_bytes(b"png-bytes")

    bot = _bot()
    import engine.server.telegram_bot as tb

    # Ép vượt trần photo để đi nhánh bản xem (tệp test chỉ vài byte).
    monkeypatch.setattr(tb, "TELEGRAM_PHOTO_MAX_BYTES", 4)
    monkeypatch.setattr(bot, "_build_photo_preview", lambda path: preview)
    posts = []
    monkeypatch.setattr(
        bot,
        "_post_file",
        lambda chat_id, path, **kw: posts.append((kw["method"], Path(path))),
    )
    requests = []

    async def fake_request(method, payload):
        requests.append((method, payload))
        return {"ok": True}

    monkeypatch.setattr(bot, "_request", fake_request)
    token = od._register(image)
    asyncio.run(
        bot._send_output_file(
            1, {"path": str(image), "kind": "image", "url": f"/api/outputs/{token}"}
        )
    )
    assert [(m, p.name) for m, p in posts] == [("sendPhoto", preview.name)]
    # Tệp tạm dọn sau khi gửi, file gốc còn nguyên.
    assert not preview.exists()
    assert image.is_file()
    # Không tin rời: lượt tải chờ gắn nút vào tin phản hồi cuối.
    assert requests == []
    assert bot._take_pending_download(1) == ("anh_upscaled.png", token)


def test_download_button_callback_delivers_the_original(tmp_path, monkeypatch):
    """Bấm nút ⬇ trên hàng phản hồi: bot gửi bản gốc dạng document."""
    target = tmp_path / "anh_upscaled.png"
    target.write_bytes(b"png")
    token = od._register(target)

    bot = _bot()
    posts = []
    monkeypatch.setattr(
        bot,
        "_post_file",
        lambda chat_id, path, **kw: posts.append((kw["method"], Path(path).name)),
    )
    answers = []

    async def fake_request(method, payload):
        if method == "answerCallbackQuery":
            answers.append(payload["text"])
        return {"ok": True}

    monkeypatch.setattr(bot, "_request", fake_request)
    asyncio.run(
        bot._handle_callback(
            {"id": "cb1", "message": {"chat": {"id": 1}}, "data": f"jarvis:dl:{token}"}
        )
    )
    assert posts == [("sendDocument", "anh_upscaled.png")]
    assert answers == ["Đang gửi tệp"]


def test_expired_download_token_answers_without_upload(monkeypatch):
    """Token lạ/hết hạn: chỉ báo, không upload gì."""
    bot = _bot()
    posts = []
    monkeypatch.setattr(bot, "_post_file", lambda *a, **kw: posts.append(a))
    answers = []

    async def fake_request(method, payload):
        answers.append((method, payload.get("text")))
        return {"ok": True}

    monkeypatch.setattr(bot, "_request", fake_request)
    asyncio.run(
        bot._handle_callback(
            {"id": "cb9", "message": {"chat": {"id": 1}}, "data": "jarvis:dl:het-han"}
        )
    )
    assert posts == []
    assert answers == [("answerCallbackQuery", "Tệp đã hết hiệu lực")]


def test_photo_preview_is_built_under_the_limit(tmp_path):
    """Builder thật (PIL): PNG nhiễu 3200x2400 phải ra JPEG vừa khung photo."""
    pytest.importorskip("PIL")
    from PIL import Image

    big = tmp_path / "lon.png"
    Image.effect_noise((3200, 2400), 128).convert("RGB").save(big, "PNG")
    assert big.stat().st_size > TELEGRAM_PHOTO_MAX_BYTES

    bot = _bot()
    out = bot._build_photo_preview(big)
    assert out is not None and out.suffix == ".jpg"
    try:
        assert out.stat().st_size <= TELEGRAM_PHOTO_MAX_BYTES - 512 * 1024
    finally:
        out.unlink(missing_ok=True)


def test_undecodable_image_falls_back_to_document(tmp_path, monkeypatch):
    """Không dựng được bản xem (tệp hỏng): rớt xuống document như cũ."""
    broken = tmp_path / "hong.png"
    broken.write_bytes(b"khong-phai-anh")

    bot = _bot()
    import engine.server.telegram_bot as tb

    # Ép vượt trần photo để đi nhánh bản xem rồi rớt xuống document.
    monkeypatch.setattr(tb, "TELEGRAM_PHOTO_MAX_BYTES", 4)
    assert bot._build_photo_preview(broken) is None
    posts = []
    monkeypatch.setattr(
        bot, "_post_file", lambda chat_id, path, **kw: posts.append(kw["method"])
    )
    asyncio.run(bot._send_output_file(1, {"path": str(broken), "kind": "image"}))
    assert posts == ["sendDocument"]


def test_oversized_file_reports_path_instead_of_uploading(tmp_path, monkeypatch):
    big = tmp_path / "qua_lon.docx"
    big.write_bytes(b"x" * (TELEGRAM_DOCUMENT_MAX_BYTES + 1))

    bot = _bot()
    posts = []
    texts = []
    monkeypatch.setattr(
        bot, "_post_file", lambda *a, **kw: posts.append(a)
    )

    async def fake_text(chat_id, text):
        texts.append(text)

    monkeypatch.setattr(bot, "_send_text", fake_text)
    asyncio.run(bot._send_output_file(1, {"path": str(big), "kind": "document"}))
    assert posts == []
    assert texts and str(tmp_path) in texts[0]


def test_missing_output_file_tells_the_user(tmp_path, monkeypatch):
    bot = _bot()
    texts = []
    monkeypatch.setattr(
        bot, "_post_file", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("no upload"))
    )

    async def fake_text(chat_id, text):
        texts.append(text)

    monkeypatch.setattr(bot, "_send_text", fake_text)
    asyncio.run(bot._send_output_file(1, {"path": str(tmp_path / "khong_ton_tai.png")}))
    assert texts and "khong_ton_tai.png" in texts[0]


def test_post_file_builds_multipart_with_caption_and_mime(tmp_path, monkeypatch):
    target = tmp_path / "ket_qua.png"
    target.write_bytes(b"DATA")

    bot = _bot()
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = request.data
        captured["headers"] = request.headers
        captured["method"] = request.get_method()

        class Resp:
            def read(self):
                return b'{"ok": true}'

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return Resp()

    import engine.server.telegram_bot as tb

    monkeypatch.setattr(tb, "urlopen", fake_urlopen)
    bot._post_file(5, target, method="sendDocument", field="document", caption="Báo cáo")

    assert captured["url"].endswith("/sendDocument")
    assert captured["method"] == "POST"
    body = captured["body"]
    assert b'name="chat_id"' in body and b"\r\n\r\n5\r\n" in body
    assert b'name="caption"' in body and b"B\xc3\xa1o c\xc3\xa1o" in body  # utf-8
    assert b'name="document"' in body and b"filename=\"ket_qua.png\"" in body
    assert b"Content-Type: image/png" in body
    assert body.endswith(b"--\r\n") or b"--\r\n" in body[-40:]
    assert "multipart/form-data" in captured["headers"]["Content-type"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn() if "monkeypatch" not in fn.__code__.co_varnames else None
    print("OK: output_delivery tests passed (run via pytest for fixtures)")

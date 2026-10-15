"""Văn bản gửi cho TTS phải đúng: TTS đọc đúng những gì nó nhận (một nơi chuẩn bị: prepare_tts_text)."""
import asyncio
import re

import pytest

from engine.server.tts_engine import prepare_tts_text

# (đầu vào, kết quả mong đợi) — giống nhau cho edge và vieneu
BOTH = [
    # đơn vị
    ("Thể tích 5 m3 nước, 120 kWh mỗi tháng.",
     "Thể tích năm mét khối nước, một trăm hai mươi ki lô oát giờ mỗi tháng."),
    ("Tốc độ 60 km/h, 3,5 kWh/ngày.",
     "Tốc độ sáu mươi ki lô mét trên giờ, ba phẩy năm ki lô oát giờ trên ngày."),
    ("Diện tích 25 m², thể tích 10m³, 512 GB, 100Mbps, 2.5h.",
     "Diện tích hai mươi lăm mét vuông, thể tích mười mét khối, năm trăm mười hai gi ga bai, "
     "một trăm mê ga bít trên giây, hai phẩy năm giờ."),
    # ngày, giờ, điện thoại
    ("Ngày 21/09/2026, lúc 08:30, họp 9h30 và 14:00.",
     "Ngày hai mươi mốt tháng chín năm hai nghìn không trăm hai mươi sáu, lúc tám giờ ba mươi phút, "
     "họp chín giờ ba mươi phút và mười bốn giờ."),
    ("Ngày 2026-09-21 và 21/09 và 3/4 và tháng 09/2026.",
     "Ngày hai mươi mốt tháng chín năm hai nghìn không trăm hai mươi sáu và ngày hai mươi mốt tháng chín "
     "và ba phần bốn và tháng chín năm hai nghìn không trăm hai mươi sáu."),
    ("Gọi 0909 123 456 hoặc +84 909 123 456.",
     "Gọi không chín không chín, một hai ba, bốn năm sáu hoặc cộng tám bốn, "
     "không chín không chín, một hai ba, bốn năm sáu."),
    # số âm, phần trăm, phiên bản, số thập phân
    ("Nhiệt độ -3°C, +26°C, tăng 3.5% so với 2,5%, bản v3.7.1.",
     "Nhiệt độ âm ba độ xê, hai mươi sáu độ xê, tăng ba phẩy năm phần trăm so với hai phẩy năm phần trăm, "
     "bản vê ba chấm bảy chấm một."),
    ("Mã 0.125, số 007, 1.234 điểm.",
     "Mã không phẩy một hai năm, số không không bảy, một nghìn hai trăm ba mươi bốn điểm."),
    # tiền
    ("Giá $12.5 tỷ và 3,5 triệu USD; vàng 78.500.000 VNĐ/lượng, 1.500.000đ.",
     "Giá mười hai phẩy năm tỷ đô la và ba phẩy năm triệu đô la Mỹ, vàng bảy mươi tám triệu năm trăm nghìn "
     "đồng trên lượng, một triệu năm trăm nghìn đồng."),
    # đơn vị đứng sau "VNĐ/": đọc "trên" + đơn vị, không đánh vần "m ba" / "k W h"
    ("Nước 6.700 VNĐ/m³, điện 1.984 VNĐ/kWh.",
     "Nước sáu nghìn bảy trăm đồng trên mét khối, điện một nghìn chín trăm tám mươi bốn đồng trên ki lô oát giờ."),
    ("Gạo 25.000 VNĐ/kg, xăng 23.500đ/lít, gas 400.000 VND/bình.",
     "Gạo hai mươi lăm nghìn đồng trên ki lô gam, xăng hai mươi ba nghìn năm trăm đồng trên lít, "
     "gas bốn trăm nghìn đồng trên bình."),
    # 24/7 là "cả ngày cả tuần", không phải 24 tháng 7 (trừ khi có chữ "ngày" đứng trước)
    ("Làm việc 24/7, hỗ trợ 24/7.", "Làm việc hai mươi bốn trên bảy, hỗ trợ hai mươi bốn trên bảy."),
    ("Sự kiện ngày 24/7 và lễ 30/4.",
     "Sự kiện ngày hai mươi bốn tháng bảy và lễ ngày ba mươi tháng bốn."),
    # phép tính, khoảng
    ("5 + 3 = 8, 8 - 3 = 5, 4 x 6 = 24, 10 / 2 = 5, 2^3 = 8, 7 > 5, 3 <= 4, 1/2 cốc, tỷ lệ 16:9.",
     "năm cộng ba bằng tám, tám trừ ba bằng năm, bốn nhân sáu bằng hai mươi bốn, mười chia hai bằng năm, "
     "hai mũ ba bằng tám, bảy lớn hơn năm, ba nhỏ hơn hoặc bằng bốn, một phần hai cốc, tỷ lệ mười sáu trên chín."),
    ("Từ 10-20 tuổi, sáng 8:00-9:30.",
     "Từ mười đến hai mươi tuổi, sáng tám giờ đến chín giờ ba mươi phút."),
    ("Lập trình C++ và C#, email a@b.com.",
     "Lập trình C cộng cộng và C thăng, email a còng b chấm com."),
    # markdown, URL, emoji, mã: không bao giờ được gửi cho TTS
    ("🎤✨\n\nNgài muốn tôi đọc gì?", "Ngài muốn tôi đọc gì?"),
    ("Xem file `context_manager.py` và [liên kết](https://x.com/a), hoặc https://example.com/abc?x=1.",
     "Xem file context manager chấm py và liên kết, hoặc xem chi tiết."),
    ("1. **Mục một:** nội dung\n2. **Mục hai**\n   - con A\n   - con B\n\n## Tiêu đề\nĐoạn cuối.",
     "Mục một, nội dung. Mục hai. con A. con B. Tiêu đề. Đoạn cuối."),
    ("| Tên | Giá |\n|---|---|\n| A | 5 kg |\n```python\nprint(1)\n```\nXong.",
     "Tên, Giá. A, năm ki lô gam. Xong."),
    ("├── engine/\n│   └── core/\n▶ Xong", "engine. core. Xong"),
    ("\"Ê, làm sao?\". Anh kia nói: 'nghỉ ngơi' nha; đúng không...",
     "Ê, làm sao? Anh kia nói, nghỉ ngơi nha, đúng không."),
    ("Jarvis đã sẵn sàng.", "Gia vích đã sẵn sàng."),
    ("Mục RESOURCES và CPU qua HTTPS.", "Mục resources và CPU qua HTTPS."),
]


@pytest.mark.parametrize("engine", ["edge", "vieneu"])
@pytest.mark.parametrize("raw,expected", BOTH)
def test_prepared_text_is_exactly_what_should_be_spoken(engine, raw, expected):
    assert prepare_tts_text(raw, engine) == expected


@pytest.mark.parametrize("engine", ["edge", "vieneu"])
@pytest.mark.parametrize("raw,_", BOTH)
def test_no_digits_or_markup_left_for_tts(engine, raw, _):
    out = prepare_tts_text(raw, engine)
    assert not re.search(r"[\d*`#|<>\[\]_\\~=+^@]", out), out
    assert "://" not in out and "www." not in out and not re.search(r"[\U0001F300-\U0001FAFF]", out)


def test_ask_user_markers_are_not_read_aloud():
    assert prepare_tts_text("Chào ngài. <ask_user>Mở Notepad không?</ask_user>") == prepare_tts_text("Chào ngài. Mở Notepad không?")


def test_action_run_blocks_are_not_read_aloud():
    """<action_run>...</action_run> blocks completely removed from TTS text."""
    assert prepare_tts_text("Mở Notepad không? <action_run>open_app</action_run>") == prepare_tts_text("Mở Notepad không?")
    # Unclosed tag also stripped
    assert prepare_tts_text("Mở Notepad không? <action_run>open_app") == prepare_tts_text("Mở Notepad không?")


def test_cues_are_kept_only_for_vieneu():
    raw = "[cười] Nghe hay quá đi [thở dài]. Để mình nói tiếp."
    assert prepare_tts_text(raw, "vieneu") == "[cười] Nghe hay quá đi [thở dài]. Để mình nói tiếp."
    assert prepare_tts_text(raw, "edge") == "Nghe hay quá đi. Để mình nói tiếp."
    # cue đứng sau emoji + ngoặc mồ côi: dọn sạch, cue vẫn còn
    assert prepare_tts_text('[cười] 😉"\n\nNgài thấy sao?', "vieneu") == "[cười] Ngài thấy sao?"


def test_prepare_is_idempotent_and_drops_unspeakable_text():
    for raw, _ in BOTH:
        for engine in ("edge", "vieneu"):
            once = prepare_tts_text(raw, engine)
            assert prepare_tts_text(once, engine) == once
    for junk in ("", "😊", "**", "---", "```python\nprint(1)\n```", ". ...", "   "):
        assert prepare_tts_text(junk, "vieneu") == "" and prepare_tts_text(junk, "edge") == ""


def test_tts_manager_sends_prepared_text_to_the_tts_server(monkeypatch):
    """Điểm gọi duy nhất: mọi yêu cầu TTS đều đi qua tts_manager và mang văn bản đã chuẩn bị."""
    import json

    import httpx

    import engine.server.tts_manager as tm

    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, content=b"RIFF" + b"\x00" * 40 + b"\x01\x00")

    async def fake_client():
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(tm, "get_tts_client", fake_client)
    monkeypatch.setenv("VIENEU_TTS_ENABLED", "true")
    monkeypatch.setenv("EDGE_TTS_ENABLED", "false")

    async def run():
        return [x async for x in tm.stream_synthesize_pcm("🎤 Thể tích **5 m3** nước, xem https://x.com/a.")]

    asyncio.run(run())
    assert bodies and bodies[0]["text"] == "Thể tích năm mét khối nước, xem chi tiết."

    bodies.clear()
    assert asyncio.run(_collect(tm.stream_synthesize_pcm("😊 **"))) == [] and bodies == []  # không có gì để đọc → không gọi TTS


async def _collect(agen):
    return [x async for x in agen]


def test_voice_streamer_put_splits_lines_and_drops_code_fences():
    from engine.server import voice_streamer as vs

    class WS:
        tts_disabled = cancel_requested = tts_active = media_active = False

    blob = (
        "* Bao gồm module quản lý ngữ cảnh context_manager.py trong thư mục engine\n"
        "* Cung cấp các công cụ mà Agent có thể sử dụng để hoàn thành nhiệm vụ của ngài\n"
        "```python\nprint('không đọc')\n```\n"
        "Kết thúc phần mô tả này ở đây."
    )
    assert len(blob) > vs._PUT_SPLIT_THRESHOLD

    async def scenario():
        s = vs.VoiceStreamer(WS(), send_fn=lambda *_: None)
        await s.put(blob)
        items = []
        while not s.text_queue.empty():
            items.append(s.text_queue.get_nowait())
        return items

    items = asyncio.run(scenario())
    assert len(items) == 3 and "context_manager.py" in items[0] and "print" not in " ".join(items)

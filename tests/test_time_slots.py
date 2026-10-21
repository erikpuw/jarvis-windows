"""8 khung giờ của ngài nằm một chỗ ở backend (2026-10-18): lúc 03:10 chat nói "sáng sớm", ngài sửa "khuya";
lớp chào và <thoi_gian> cùng đọc bảng này, frontend chỉ hiện câu server gửi."""
import asyncio
from datetime import datetime

import pytest

from engine.core import clock
from engine.main import welcome as w
from engine.turn import prompt


@pytest.mark.parametrize("hour,part,greeting", [
    (0, "đêm khuya", "Đêm khuya rồi"), (4, "đêm khuya", "Đêm khuya rồi"),
    (5, "sáng sớm", "Chào buổi sáng sớm"), (6, "sáng sớm", "Chào buổi sáng sớm"),
    (7, "buổi sáng", "Chào buổi sáng"), (10, "buổi sáng", "Chào buổi sáng"),
    (11, "buổi trưa", "Chào buổi trưa"), (12, "buổi trưa", "Chào buổi trưa"),
    (13, "buổi chiều", "Chào buổi chiều"), (16, "buổi chiều", "Chào buổi chiều"),
    (17, "xế chiều", "Chào buổi xế chiều"), (18, "xế chiều", "Chào buổi xế chiều"),
    (19, "buổi tối", "Chào buổi tối"), (21, "buổi tối", "Chào buổi tối"),
    (22, "khuya", "Khuya rồi"), (23, "khuya", "Khuya rồi"),
])
def test_eight_slots(hour, part, greeting):
    assert clock.time_slot(hour) == (part, greeting)


def test_prompt_time_names_the_slot():
    text = prompt._now(datetime(2026, 10, 18, 3, 10))
    assert "Bây giờ là 03:10, đêm khuya." in text and "Chủ Nhật" in text


def test_welcome_sends_greeting_from_server_clock(monkeypatch):
    monkeypatch.setattr(w, "_hour", lambda: 3)

    async def snap():
        return None
    monkeypatch.setattr(w, "fetch_weather_snapshot", snap)
    sent = []

    async def send(ws, data):
        sent.append(data)
    asyncio.run(w.send_welcome(object(), send))
    assert sent[0]["greeting"] == "Đêm khuya rồi" and sent[0]["tools"]

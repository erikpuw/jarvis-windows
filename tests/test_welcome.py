import asyncio

from engine.main import welcome as w


def _run(coro):
    return asyncio.run(coro)


def test_tool_labels_hide_screen_mail_and_odd_ones():
    labels = w.tool_labels()
    for hidden in ("Đọc màn hình", "Chụp màn hình", "Gmail", "Gym", "Webcam", "Điều khiển Windows", "Mở ứng dụng", "Đóng ứng dụng"):
        assert hidden not in labels
    assert "Thời tiết" in labels and "Tin tức" in labels


def test_weather_payload():
    assert w.weather_payload(None) is None
    assert w.weather_payload({"desc": ""}) is None
    p = w.weather_payload({"desc": "nhiều mây", "temp": 25.4, "kind": "cloudy"})
    assert p == {"desc": "nhiều mây", "temp": 25.4, "kind": "cloudy", "place": w._LOCATION_NAME}


def _capture():
    sent = []

    async def send(ws, data):
        sent.append(data)
        return True
    return sent, send


def test_send_welcome_tools_first_then_weather(monkeypatch):
    async def snap():
        return {"desc": "nắng nhẹ", "temp": 31.0, "kind": "clear"}
    monkeypatch.setattr(w, "fetch_weather_snapshot", snap)
    sent, send = _capture()
    _run(w.send_welcome(object(), send))
    assert [s["type"] for s in sent] == ["welcome", "welcome"]
    assert "tools" in sent[0] and "weather" not in sent[0]
    assert sent[1] == {"type": "welcome", "weather": {"desc": "nắng nhẹ", "temp": 31.0, "kind": "clear", "place": w._LOCATION_NAME}}


def test_send_welcome_no_speech_no_chat(monkeypatch):
    """Ngài 2026-10-16: không đọc, không bong bóng chat — chỉ gói welcome."""
    async def snap():
        return {"desc": "mưa", "temp": 24.0, "kind": "rain"}
    monkeypatch.setattr(w, "fetch_weather_snapshot", snap)
    sent, send = _capture()
    _run(w.send_welcome(object(), send))
    assert all(s["type"] == "welcome" for s in sent)


def test_send_welcome_weather_slow_or_failing(monkeypatch):
    async def slow():
        await asyncio.sleep(1)
    monkeypatch.setattr(w, "fetch_weather_snapshot", slow)
    monkeypatch.setattr(w, "WEATHER_WAIT_SECONDS", 0.01)
    sent, send = _capture()
    _run(w.send_welcome(object(), send))
    assert len(sent) == 1 and "tools" in sent[0]

    async def broken():
        raise RuntimeError("all sources down")
    monkeypatch.setattr(w, "fetch_weather_snapshot", broken)
    sent, send = _capture()
    _run(w.send_welcome(object(), send))
    assert len(sent) == 1

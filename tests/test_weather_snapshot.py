import asyncio

import httpx
import pytest

from engine.tools import weather_engine as we


@pytest.fixture(autouse=True)
def _reset_state():
    we._snapshot_cache = None
    we._open_meteo_blocked_until = 0.0
    yield
    we._snapshot_cache = None
    we._open_meteo_blocked_until = 0.0


def test_open_meteo_description_follows_cloud_cover_not_just_code():
    # Case thật 2026-09-28 08:15: code 1, mây 42%, ban ngày -> có nắng, không phải "nhiều mây"
    assert "nắng" in we._describe_open_meteo(1, 42, 1)
    assert "quang" in we._describe_open_meteo(0, 5, 0)
    assert "nhiều mây" in we._describe_open_meteo(2, 70, 1)
    assert "u ám" in we._describe_open_meteo(3, 95, 1)
    assert "mưa" in we._describe_open_meteo(61, 90, 1)  # có mưa thì theo mã, bỏ qua mây


def test_classify_sky():
    assert we._classify("trời nắng, có ít mây") == "clear"
    assert we._classify("rất nhiều mây") == "cloudy"
    assert we._classify("sương mù khói") == "haze"
    assert we._classify("sương mù") == "fog"
    assert we._classify("mưa rào nhẹ") == "rain"
    assert we._classify("giông kèm mưa đá nhẹ") == "storm"


def test_rate_limit_falls_back_to_wttr_and_skips_open_meteo_next_time(monkeypatch):
    calls = {"om": 0}

    async def om_429(lat, lon):
        calls["om"] += 1
        req = httpx.Request("GET", "https://api.open-meteo.com")
        raise httpx.HTTPStatusError("429", request=req, response=httpx.Response(429, request=req))

    async def wttr():
        return {"desc": "trời nắng", "temp": 31, "is_day": None, "source": "wttr"}

    async def baomoi():
        raise AssertionError("Báo Mới chỉ là nguồn cuối")

    monkeypatch.setattr(we, "_fetch_open_meteo", om_429)
    monkeypatch.setattr(we, "_wttr_snapshot", wttr)
    monkeypatch.setattr(we, "_baomoi_fetch_snapshot", baomoi)

    snap = asyncio.run(we.fetch_weather_snapshot())
    assert snap["source"] == "wttr" and snap["kind"] == "clear"
    we._snapshot_cache = None  # bỏ cache để buộc lấy lại
    asyncio.run(we.fetch_weather_snapshot())
    assert calls["om"] == 1  # đang bị limit -> không gọi lại Open-Meteo


def test_fetch_weather_text_still_works(monkeypatch):
    async def om(lat, lon):
        return {"current": {"temperature_2m": 28.4, "weathercode": 1, "cloud_cover": 42, "is_day": 1}}

    monkeypatch.setattr(we, "_fetch_open_meteo", om)
    text = asyncio.run(we.fetch_weather())
    assert "nắng" in text and "28" in text

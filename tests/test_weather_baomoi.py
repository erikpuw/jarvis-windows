import asyncio
import json
import time

import httpx
import pytest

from engine.tools import weather_engine as we

BOARDS = [
    {"name": "TP. Hồ Chí Minh", "slug": "tp-ho-chi-minh", "lat": 10.776577, "lon": 106.70085},
    {"name": "Hà Nội", "slug": "ha-noi", "lat": 21.028167, "lon": 105.854152},
    {"name": "Đà Nẵng", "slug": "da-nang", "lat": 16.07, "lon": 108.22},
    {"name": "Thừa Thiên Huế", "slug": "thua-thien-hue", "lat": 16.46, "lon": 107.59},
    {"name": "Lâm Đồng", "slug": "lam-dong", "lat": 11.94, "lon": 108.44},
]


def _hours(start=10, end=23):
    return [
        {"hours": h, "temperature": 30 - (h % 5), "humidity": 70 + h % 10, "wind": 6, "pop": h * 3, "status": "Nhiều mây"}
        for h in range(start, end + 1)
    ]


def _entry(date, hours, pop_day=80, pop_night=20):
    return {
        "date": date, "status": "Nhiều mây", "humidity": 81, "wind": 10,
        "temperatureMin24Hour": "25", "temperatureMax24Hour": "33",
        "day": {"temperature": 33, "humidity": 74, "wind": 8, "pop": pop_day, "status": "Mưa giông"},
        "night": {"temperature": 25, "humidity": 94, "wind": 7, "pop": pop_night, "status": "Nhiều mây"},
        "hours": hours,
    }


def _page(entries=None, name="TP. Hồ Chí Minh", slug="tp-ho-chi-minh", lat="10.776577", lon="106.70085"):
    entries = entries if entries is not None else [_entry("04/10/2026", _hours()), _entry("05/10/2026", _hours(0, 23))]
    boards = [
        {"displayName": b["name"], "shortName": b["slug"], "latitude": str(b["lat"]), "longitude": str(b["lon"])}
        for b in BOARDS
    ]
    data = {"props": {"pageProps": {"resp": {"data": {"content": {
        "boards": boards,
        "activeBoard": {"displayName": name, "shortName": slug, "latitude": lat, "longitude": lon, "entries": entries},
    }}}}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data, ensure_ascii=False)}</script></html>'


@pytest.fixture(autouse=True)
def _reset_state():
    def reset():
        we._snapshot_cache = None
        we._open_meteo_blocked_until = 0.0
        we._boards_cache = None
        we._baomoi_page_cache.clear()
    reset()
    yield
    reset()


@pytest.fixture
def boards_loaded():
    we._boards_cache = (time.time(), BOARDS)


# ── Nhận diện tỉnh thành từ câu của người dùng ──

@pytest.mark.parametrize("text,slug", [
    ("hồ chí minh", "tp-ho-chi-minh"),
    ("Ho Chi Minh", "tp-ho-chi-minh"),
    ("sài gòn", "tp-ho-chi-minh"),
    ("tphcm", "tp-ho-chi-minh"),
    ("hcm", "tp-ho-chi-minh"),
    ("Hà Nội", "ha-noi"),
    ("ha noi", "ha-noi"),
    ("đà nẵng", "da-nang"),
    ("da nan", "da-nang"),          # gõ sai nhẹ
    ("huế", "thua-thien-hue"),
    ("thừa thiên huế", "thua-thien-hue"),
    ("mưa ở đà lạt thế nào", None),  # không có trong danh sách
    ("lâm đồng nhiều mưa không", "lam-dong"),  # tên tỉnh nằm giữa câu
    ("vũng tàu", None),
    ("paris", None),
    ("", None),
])
def test_resolve_province(text, slug):
    board = we._resolve_province(text, BOARDS)
    assert (board["slug"] if board else None) == slug


# ── Đọc JSON nhúng của Báo Mới ──

def test_baomoi_parse_reads_boards_and_hours():
    p = we._baomoi_parse(_page())
    assert p["name"] == "TP. Hồ Chí Minh"
    assert (p["lat"], p["lon"]) == (10.776577, 106.70085)
    assert [b["slug"] for b in p["boards"]][:2] == ["tp-ho-chi-minh", "ha-noi"]
    assert p["boards"][1]["lat"] == 21.028167
    today = p["days"][0]
    assert today["date"] == "04/10/2026" and today["tmin"] == 25 and today["tmax"] == 33
    assert today["hours"][0]["h"] == 10 and today["hours"][0]["pop"] == 30


@pytest.mark.parametrize("html", [
    "",
    "<html>chặn bot</html>",
    '<script id="__NEXT_DATA__" type="application/json">{không phải json</script>',
    _page(entries=[]),
    _page(entries=[{"date": "04/10/2026", "hours": []}]),
])
def test_baomoi_parse_rejects_garbage(html):
    assert we._baomoi_parse(html) is None


def test_baomoi_current_picks_this_hour_not_a_future_slot():
    # Lỗi cũ: selector HTML trả mốc 00:00 ngày mai; giờ hiện tại phải lấy theo giờ thật.
    days = we._baomoi_parse(_page())["days"]
    assert we._baomoi_current(days, 14)["h"] == 14
    assert we._baomoi_current(days, 8)["h"] == 10     # trước mốc đầu -> mốc đầu
    assert we._baomoi_current(days, 23)["h"] == 23


def test_format_baomoi_current():
    p = we._baomoi_parse(_page())
    text = we._format_baomoi(p, 14)
    assert "TP. Hồ Chí Minh" in text and "26°C" in text      # 30 - 14 % 5
    assert "Khả năng mưa: 42%" in text                        # pop 14*3
    assert "25" in text and "33" in text                      # nhiệt độ thấp/cao hôm nay


# ── weather_search: thời tiết thường ──

def _forbid(name):
    async def boom(*a, **k):
        raise AssertionError(f"{name} không được gọi")
    return boom


def test_normal_question_uses_baomoi_only(monkeypatch, boards_loaded):
    async def baomoi(slug):
        assert slug == "ha-noi"
        return we._baomoi_parse(_page(name="Hà Nội", slug="ha-noi"))

    monkeypatch.setattr(we, "_baomoi_fetch", baomoi)
    monkeypatch.setattr(we, "_geocode", _forbid("_geocode"))
    monkeypatch.setattr(we, "_fetch_open_meteo", _forbid("_fetch_open_meteo"))
    monkeypatch.setattr(we, "_wttr_snapshot", _forbid("_wttr_snapshot"))
    text = asyncio.run(we.weather_search("thời tiết hà nội hôm nay"))
    assert "Hà Nội" in text and "Độ ẩm" in text


def test_normal_question_falls_back_to_wttr_when_baomoi_fails(monkeypatch, boards_loaded):
    seen = {}

    async def baomoi(slug):
        raise httpx.ConnectError("down")

    async def wttr(query="x"):
        seen["q"] = query
        return {"desc": "trời nắng", "temp": 31, "is_day": None, "source": "wttr"}

    monkeypatch.setattr(we, "_baomoi_fetch", baomoi)
    monkeypatch.setattr(we, "_fetch_open_meteo", _forbid("_fetch_open_meteo"))
    monkeypatch.setattr(we, "_wttr_snapshot", wttr)
    text = asyncio.run(we.weather_search("Đà Nẵng"))
    assert "Đà Nẵng" in text and "trời nắng" in text and "31" in text
    assert seen["q"] == "16.07,108.22"          # dùng toạ độ của tỉnh, không đoán theo chữ


def test_unknown_place_geocodes_then_wttr(monkeypatch, boards_loaded):
    async def geocode(q):
        assert q == "đà lạt"
        return 11.94, 108.44, "Đà Lạt"

    async def wttr(query="x"):
        assert query == "11.94,108.44"
        return {"desc": "trời mát", "temp": 20, "is_day": None, "source": "wttr"}

    monkeypatch.setattr(we, "_baomoi_fetch", _forbid("_baomoi_fetch"))
    monkeypatch.setattr(we, "_geocode", geocode)
    monkeypatch.setattr(we, "_wttr_snapshot", wttr)
    text = asyncio.run(we.weather_search("đà lạt"))
    assert "Đà Lạt" in text and "20" in text


def test_normal_question_last_resort_is_open_meteo_current(monkeypatch, boards_loaded):
    async def baomoi(slug):
        raise httpx.ConnectError("down")

    async def wttr(query="x"):
        return None

    async def om(lat, lon):
        return {"current": {"temperature_2m": 29.0, "apparent_temperature": 33, "relative_humidity_2m": 80,
                            "weathercode": 3, "wind_speed_10m": 5, "wind_direction_10m": 90, "uv_index": 6}}

    monkeypatch.setattr(we, "_baomoi_fetch", baomoi)
    monkeypatch.setattr(we, "_wttr_snapshot", wttr)
    monkeypatch.setattr(we, "_fetch_open_meteo", om)
    text = asyncio.run(we.weather_search("hà nội"))
    assert "Hà Nội" in text and "29" in text and "UV" in text


def test_place_not_found_asks_user(monkeypatch, boards_loaded):
    async def geocode(q):
        raise LookupError(q)

    monkeypatch.setattr(we, "_geocode", geocode)
    text = asyncio.run(we.weather_search("xyzabc"))
    assert "Không tìm thấy" in text and "xyzabc" in text


# ── weather_search: dự báo mưa theo giờ ──

def _om_hourly(n=24):
    times = [f"2026-10-04T{(9 + i) % 24:02d}:00" for i in range(n)]
    return {"hourly": {"time": times, "precipitation_probability": [i * 4 for i in range(n)],
                       "precipitation": [0.0] * n}}


def test_hourly_uses_open_meteo_with_board_coordinates(monkeypatch, boards_loaded):
    seen = {}

    async def om_hourly(lat, lon):
        seen["ll"] = (lat, lon)
        return _om_hourly()

    monkeypatch.setattr(we, "_geocode", _forbid("_geocode"))
    monkeypatch.setattr(we, "_baomoi_fetch", _forbid("_baomoi_fetch"))
    monkeypatch.setattr(we, "_fetch_open_meteo_hourly", om_hourly)
    text = asyncio.run(we.weather_search("Hà Nội", hourly=True))
    assert seen["ll"] == (21.028167, 105.854152)      # toạ độ lấy từ Báo Mới, đỡ gọi geocode
    assert "Hà Nội" in text
    assert "09:00" in text and "0%" in text
    assert "20:00" in text and "44%" in text          # i=11 -> 44%
    assert text.count("%") >= 24


def test_hourly_unknown_place_geocodes(monkeypatch, boards_loaded):
    async def geocode(q):
        return 10.35, 107.08, "Vũng Tàu"

    async def om_hourly(lat, lon):
        assert (lat, lon) == (10.35, 107.08)
        return _om_hourly(6)

    monkeypatch.setattr(we, "_geocode", geocode)
    monkeypatch.setattr(we, "_fetch_open_meteo_hourly", om_hourly)
    text = asyncio.run(we.weather_search("vũng tàu", hourly=True))
    assert "Vũng Tàu" in text and "09:00" in text


def test_hourly_rate_limited_falls_back_to_baomoi_hours(monkeypatch, boards_loaded):
    async def om_hourly(lat, lon):
        req = httpx.Request("GET", "https://api.open-meteo.com")
        raise httpx.HTTPStatusError("429", request=req, response=httpx.Response(429, request=req))

    async def baomoi(slug):
        return we._baomoi_parse(_page(name="Hà Nội", slug="ha-noi"))

    monkeypatch.setattr(we, "_fetch_open_meteo_hourly", om_hourly)
    monkeypatch.setattr(we, "_baomoi_fetch", baomoi)
    monkeypatch.setattr(we, "_vn_hour", lambda: 10)
    text = asyncio.run(we.weather_search("Hà Nội", hourly=True))
    assert "Hà Nội" in text and "10:00" in text and "30%" in text   # pop giờ 10 = 30
    assert we._open_meteo_blocked_until > time.time()               # nghỉ Open-Meteo một lúc


def test_hourly_skips_open_meteo_while_blocked(monkeypatch, boards_loaded):
    we._mark_open_meteo_limited()

    async def baomoi(slug):
        return we._baomoi_parse(_page(name="Hà Nội", slug="ha-noi"))

    monkeypatch.setattr(we, "_fetch_open_meteo_hourly", _forbid("_fetch_open_meteo_hourly"))
    monkeypatch.setattr(we, "_baomoi_fetch", baomoi)
    monkeypatch.setattr(we, "_vn_hour", lambda: 10)
    text = asyncio.run(we.weather_search("Hà Nội", hourly=True))
    assert "10:00" in text


# ── Câu hỏi nguyên văn của người dùng (đường direct_tools truyền cả câu vào `location`) ──

@pytest.mark.parametrize("text,expected", [
    ("Cho tôi lịch dự báo mưa cụ thể, % khả năng mưa theo từng giờ", True),
    ("hôm nay mấy giờ thì mưa", True),
    ("xác suất mưa theo giờ ở Đà Nẵng", True),
    ("khi nào thì mưa", True),
    ("thời tiết hà nội hôm nay", False),
    ("đà nẵng", False),
    ("hôm nay trời có nóng không", False),
])
def test_wants_hourly(text, expected):
    assert we._wants_hourly(text) is expected


@pytest.mark.parametrize("text,expected", [
    ("Cho tôi lịch dự báo mưa cụ thể, % khả năng mưa theo từng giờ", "Hồ Chí Minh"),  # không nêu nơi -> mặc định
    ("dự báo mưa theo giờ ở Đà Nẵng", "đà nẵng"),
    ("thời tiết hôm nay ở hà nội ra sao", "hà nội"),
    ("", "Hồ Chí Minh"),
])
def test_clean_location_strips_rain_and_hour_words(text, expected):
    assert we._clean_location(text) == expected


def test_full_sentence_without_place_gives_hcm_hourly(monkeypatch, boards_loaded):
    seen = {}

    async def om_hourly(lat, lon):
        seen["ll"] = (lat, lon)
        return _om_hourly(3)

    monkeypatch.setattr(we, "_geocode", _forbid("_geocode"))
    monkeypatch.setattr(we, "_fetch_open_meteo_hourly", om_hourly)
    text = asyncio.run(we.weather_search("Cho tôi lịch dự báo mưa cụ thể, % khả năng mưa theo từng giờ"))
    assert seen["ll"] == (10.776577, 106.70085)
    assert "Hồ Chí Minh" in text and "09:00" in text


# ── Danh sách tỉnh thành: lấy từ Báo Mới, hỏng thì dùng danh sách tĩnh ──

def test_load_boards_from_baomoi_then_cached(monkeypatch):
    calls = {"n": 0}

    async def fetch(slug):
        calls["n"] += 1
        p = we._baomoi_parse(_page())
        we._boards_cache = (time.time(), p["boards"])
        return p

    monkeypatch.setattr(we, "_baomoi_fetch", fetch)
    boards = asyncio.run(we._load_boards())
    asyncio.run(we._load_boards())
    assert calls["n"] == 1 and any(b["slug"] == "da-nang" for b in boards)


def test_load_boards_falls_back_to_static_list(monkeypatch):
    async def fetch(slug):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(we, "_baomoi_fetch", fetch)
    boards = asyncio.run(we._load_boards())
    slugs = {b["slug"] for b in boards}
    assert len(boards) == 34
    assert {"tp-ho-chi-minh", "ha-noi", "da-nang", "thua-thien-hue", "dak-lak"} <= slugs
    assert we._resolve_province("đắk lắk", boards)["slug"] == "dak-lak"


def test_greeting_snapshot_from_baomoi_uses_current_hour(monkeypatch):
    async def baomoi(slug):
        assert slug == "tp-ho-chi-minh"
        return we._baomoi_parse(_page())

    monkeypatch.setattr(we, "_baomoi_fetch", baomoi)
    monkeypatch.setattr(we, "_vn_hour", lambda: 14)
    snap = asyncio.run(we._baomoi_fetch_snapshot())
    assert snap["temp"] == 26 and snap["source"] == "baomoi" and "mây" in snap["desc"]

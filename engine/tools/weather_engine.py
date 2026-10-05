import difflib
import json
import time
import logging
import httpx
import threading
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote
from engine.tools.browser import browser

log = logging.getLogger("jarvis.weather")

# Quy tắc định dạng cho LLM vòng 2 — bàn giao từ actions.py cho tool sở hữu
SUMMARY_RULES: dict[str, str] = {
    "weather_search": (
        "QUY TẮC ĐỊNH DẠNG THỜI TIẾT BẮT BUỘC:\n"
        "- Tóm tắt nhiệt độ, độ ẩm, sức gió và trạng thái thời tiết ngắn gọn.\n"
        "- Đưa ra lời khuyên thiết thực (mang ô, mặc ấm, hoạt động ngoài trời...) phù hợp với ngài erikpuw.\n"
        "- Với lịch mưa theo giờ: nêu rõ các khung giờ có khả năng mưa từ 50% trở lên và giờ cao nhất, "
        "giữ nguyên số phần trăm trong dữ liệu, không bịa thêm giờ."
    ),
}

# Weather State (for greeting background thread)
_cached_weather: Optional[str] = None
_last_weather_fetch_time: float = 0.0
_ctx_cache = {"weather": "Weather data unavailable."}

import asyncio

_open_meteo_lock = threading.Lock()
_last_open_meteo_call = 0.0

async def _throttle_open_meteo_async(delay_sec: float = 2.0):
    global _last_open_meteo_call
    sleep_time = 0.0
    with _open_meteo_lock:
        now = time.time()
        elapsed = now - _last_open_meteo_call
        if elapsed < delay_sec:
            sleep_time = delay_sec - elapsed
        else:
            _last_open_meteo_call = now
    
    if sleep_time > 0.0:
        log.info(f"Throttling Open-Meteo (async): sleeping for {sleep_time:.2f}s")
        await asyncio.sleep(sleep_time)
        with _open_meteo_lock:
            _last_open_meteo_call = time.time()

# WMO weather codes → Vietnamese
WMO_CODES = {
    0: "Trời quang đãng",
    1: "Trời trong xanh",
    2: "Trời có mây rải rác",
    3: "Trời u ám",
    45: "Sương mù",
    48: "Sương muối",
    51: "Mưa phùn nhẹ",
    53: "Mưa phùn vừa",
    55: "Mưa phùn dày",
    56: "Mưa phùn băng giá nhẹ",
    57: "Mưa phùn băng giá dày",
    61: "Mưa nhẹ",
    63: "Mưa vừa",
    65: "Mưa lớn",
    66: "Mưa băng giá nhẹ",
    67: "Mưa băng giá nặng",
    71: "Tuyết rơi nhẹ",
    73: "Tuyết rơi vừa",
    75: "Tuyết rơi dày",
    77: "Mưa đá nhỏ",
    80: "Mưa rào nhẹ",
    81: "Mưa rào vừa",
    82: "Mưa rào nặng hạt",
    85: "Tuyết rào nhẹ",
    86: "Tuyết rào nặng",
    95: "Giông bão",
    96: "Giông kèm mưa đá nhẹ",
    99: "Giông kèm mưa đá nặng",
}

WIND_DIR = ["Bắc", "Bắc Đông", "Đông", "Nam Đông", "Nam", "Nam Tây", "Tây", "Bắc Tây"]

def _wind_dir_text(deg: float) -> str:
    idx = round(deg / 45) % 8
    return WIND_DIR[idx]

def _wmo_text(code: int) -> str:
    return WMO_CODES.get(code, f"Mã thời tiết {code}")


# Người dùng hỏi theo giờ / khả năng mưa -> lấy lịch mưa từng giờ thay vì thời tiết hiện tại.
_HOURLY_INTENT = re.compile(
    r"(theo|từng|mỗi) giờ|mấy giờ|giờ nào|lúc nào|khi nào|khả năng mưa|xác suất mưa|lịch (dự báo )?mưa|dự báo mưa|phần trăm mưa|% mưa"
)


def _wants_hourly(text: str) -> bool:
    return bool(_HOURLY_INTENT.search((text or "").lower()))


def _clean_location(location: str) -> str:
    """Loại bỏ các từ khóa nhiễu và chuẩn hóa viết tắt địa điểm."""
    loc = location.lower().strip()
    loc = re.sub(r"\b(tp\.?\s*hcm|tphcm|hcm)\b", "hồ chí minh", loc)
    noise_patterns = [
        _HOURLY_INTENT.pattern,
        r"\bcho tôi\b",
        r"\bcụ thể\b",
        r"\bphần trăm\b",
        r"\btheo\b",
        r"\b(thì|mưa|trời|có|không|nào|nhỉ|vậy|hả|bao nhiêu)\b",
        r"\bdự báo thời tiết\b",
        r"\bthời tiết\b",
        r"\bdự báo\b",
        r"\btại\b",
        r"\bở\b",
        r"\bthành phố\b",
        r"\bcủa\b",
        r"\btỉnh\b",
        r"\bhôm nay\b",
        r"\bngày mai\b",
        r"\bngày kia\b",
        r"\btuần này\b",
        r"\bra sao\b",
        r"\bthế nào\b",
        r"\bnhư thế nào\b",
    ]
    for pattern in noise_patterns:
        loc = re.sub(pattern, " ", loc)
    loc = re.sub(r"[^\w\s]", " ", loc)
    loc = re.sub(r"\s+", " ", loc).strip()
    if not loc:
        return "Hồ Chí Minh"
    return loc


def _api_location_name(location: str) -> str:
    """Chuẩn hóa tên địa điểm ASCII cho geocoder và wttr.in."""
    value = (location or "").strip().translate(str.maketrans({"đ": "d", "Đ": "D"}))
    value = "".join(
        char for char in unicodedata.normalize("NFD", value)
        if unicodedata.category(char) != "Mn"
    )
    value = re.sub(r"\s+", " ", value).strip()
    key = re.sub(r"[^a-z0-9 ]", " ", value.lower())
    key = re.sub(r"\s+", " ", key).strip()
    key = re.sub(r"^(?:tp|thanh pho)\s+", "", key)
    if key in {"ho chi minh", "hcm", "tphcm", "sai gon"}:
        return "Ho Chi Minh City"
    return " ".join(part.capitalize() for part in key.split())


# ── Public API: weather_search (dùng cho tool) ──

async def weather_search(location: str, hourly: bool = False) -> str:
    """Thời tiết một địa điểm. Mặc định là thời tiết hiện tại (Báo Mới -> wttr.in -> Open-Meteo);
    hourly=True là lịch khả năng mưa theo từng giờ (Open-Meteo, dự phòng Báo Mới)."""
    hourly = hourly or _wants_hourly(location)
    place = _clean_location(location)
    board = _resolve_province(place, await _load_boards())
    try:
        return await (_hourly_rain(place, board) if hourly else _current_weather(place, board))
    except LookupError:
        return f"Không tìm thấy địa điểm '{place}'. Bạn muốn xem thời tiết ở đâu?"
    except Exception as e:
        if _is_rate_limited(e):
            log.warning(f"Open-Meteo rate limit hit: {e}. Falling back to fetch_weather()")
            _mark_open_meteo_limited()
            return await fetch_weather()
        log.warning(f"Weather search failed for {place}: {e}")
        return f"Không thể lấy dữ liệu thời tiết cho {place} lúc này."


async def _current_weather(place: str, board: Optional[dict]) -> str:
    if board:
        try:
            return _format_baomoi(await _baomoi_fetch(board["slug"]), _vn_hour())
        except Exception as e:
            log.warning(f"Báo Mới {board['slug']} lỗi: {e}")
    lat, lon, name = await _locate(place, board)
    try:
        snap = await _wttr_snapshot(f"{lat},{lon}")
    except Exception as e:
        log.warning(f"wttr.in lỗi cho {name}: {e}")
        snap = None
    if snap:
        temp = f", nhiệt độ {snap['temp']}°C" if snap.get("temp") is not None else ""
        return f"📍 Thời tiết tại {name}: {snap['desc']}{temp}."
    return _format_response(name, await _fetch_open_meteo(lat, lon))


async def _hourly_rain(place: str, board: Optional[dict]) -> str:
    if time.time() >= _open_meteo_blocked_until:
        lat, lon, name = await _locate(place, board)
        try:
            return _format_hourly(name, await _fetch_open_meteo_hourly(lat, lon))
        except Exception as e:
            if not _is_rate_limited(e):
                raise
            _mark_open_meteo_limited()
    if board:
        return _format_baomoi_hourly(await _baomoi_fetch(board["slug"]), _vn_hour())
    return f"Chưa lấy được lịch mưa theo giờ cho {place} (nguồn dự báo đang giới hạn lượt truy cập), bạn thử lại sau ít phút."


async def _locate(place: str, board: Optional[dict]) -> tuple[float, float, str]:
    """Toạ độ + tên chuẩn: tỉnh của Báo Mới có sẵn toạ độ, còn lại hỏi geocode của Open-Meteo."""
    if board and board.get("lat") is not None:
        return board["lat"], board["lon"], board["name"]
    lat, lon, resolved_name = await _geocode(board["name"] if board else place)
    return lat, lon, board["name"] if board else resolved_name


async def _geocode(query: str) -> tuple[float, float, str]:
    """Open-Meteo Geocoding: tên → (lat, lon, resolved_name). Không có kết quả -> LookupError."""
    await _throttle_open_meteo_async(2.0)
    async with httpx.AsyncClient(timeout=5.0) as c:
        r = await c.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": _api_location_name(query), "count": 1, "language": "vi", "format": "json"},
        )
        r.raise_for_status()
        body = r.json()
    results = body.get("results")
    if not results:
        raise LookupError(f"Location '{query}' not found")
    r0 = results[0]
    return r0["latitude"], r0["longitude"], r0.get("name", query)


async def _fetch_open_meteo_hourly(lat: float, lon: float) -> dict:
    """Open-Meteo: khả năng mưa (%) và lượng mưa (mm) từng giờ cho 24 giờ tới."""
    await _throttle_open_meteo_async(2.0)
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "precipitation_probability,precipitation",
        "forecast_hours": 24,
        "timezone": "auto",
    }
    async with httpx.AsyncClient(timeout=5.0) as c:
        r = await c.get("https://api.open-meteo.com/v1/forecast", params=params)
        r.raise_for_status()
        return r.json()


def _hour_label(stamp: str, first_stamp: str) -> str:
    """'2026-10-04T09:00' -> '09:00'; sang ngày khác thì kèm 'dd/mm'."""
    return stamp[-5:] if stamp[:10] == first_stamp[:10] else f"{stamp[8:10]}/{stamp[5:7]} {stamp[-5:]}"


def _format_hourly(resolved: str, data: dict) -> str:
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    if not times:
        raise ValueError("Open-Meteo không trả dữ liệu theo giờ")
    pops = hourly.get("precipitation_probability", [])
    mms = hourly.get("precipitation", [])
    lines = [f"🌧 Khả năng mưa theo giờ tại {resolved} ({len(times)} giờ tới):"]
    for i, stamp in enumerate(times):
        pop = pops[i] if i < len(pops) and pops[i] is not None else "?"
        mm = mms[i] if i < len(mms) else 0
        lines.append(f"  {_hour_label(stamp, times[0])} — {pop}%" + (f" ({mm} mm)" if mm else ""))
    return "\n".join(lines)


async def _fetch_open_meteo(lat: float, lon: float) -> dict:
    """Open-Meteo forecast: lấy current weather chi tiết."""
    await _throttle_open_meteo_async(2.0)
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": ",".join([
            "temperature_2m",
            "relative_humidity_2m",
            "apparent_temperature",
            "precipitation",
            "weathercode",
            "wind_speed_10m",
            "wind_direction_10m",
            "uv_index",
            "cloud_cover",
            "is_day",
        ]),
        "timezone": "auto",
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
    }
    async with httpx.AsyncClient(timeout=5.0) as c:
        r = await c.get("https://api.open-meteo.com/v1/forecast", params=params)
        r.raise_for_status()
        return r.json()


def _format_response(resolved: str, data: dict) -> str:
    """Format dữ liệu Open-Meteo thành câu tiếng Việt đầy đủ."""
    cur = data.get("current", {})
    temp = cur.get("temperature_2m")
    feels = cur.get("apparent_temperature")
    hum = cur.get("relative_humidity_2m")
    precip = cur.get("precipitation", 0)
    code = cur.get("weathercode", 0)
    wind_spd = cur.get("wind_speed_10m", 0)
    wind_dir = cur.get("wind_direction_10m")
    uv = cur.get("uv_index", 0)

    desc = _wmo_text(code)
    wd = _wind_dir_text(wind_dir) if wind_dir is not None else ""

    lines = [f"📍 Thời tiết tại {resolved}:"]
    lines.append(f"  🌡  Nhiệt độ: {temp}°C (cảm giác như {feels}°C).")
    lines.append(f"  ☁️  {desc}.")
    lines.append(f"  💧 Độ ẩm: {hum}%.")
    if precip and precip > 0:
        lines.append(f"  🌧  Lượng mưa: {precip} mm.")
    lines.append(f"  🌬  Gió: {wind_spd} km/h{', hướng ' + wd if wd else ''}.")
    lines.append(f"  ☀️  Chỉ số UV: {uv}.")

    return "\n".join(lines)


def sanitize_weather_display_text(text: str) -> str:
    """Dọn ký hiệu LaTeX do LLM chèn vào các đơn vị thời tiết."""
    if not text:
        return text

    cleaned = re.sub(r"\^\s*\\circ\s*C\b", "°C", text, flags=re.I)
    cleaned = re.sub(r"\\circ\s*C\b", "°C", cleaned, flags=re.I)
    cleaned = cleaned.replace(r"\%", "%")

    weather_measurement = r"[+-]?\d+(?:[.,]\d+)?\s*(?:km/h|m/s|mm|°C|%)"
    cleaned = re.sub(
        rf"\$(?=\s*{weather_measurement})",
        "",
        cleaned,
        flags=re.I,
    )
    cleaned = re.sub(
        rf"({weather_measurement})\$",
        r"\1",
        cleaned,
        flags=re.I,
    )
    return cleaned


# ── Báo Mới: danh sách tỉnh thành + thời tiết từng giờ (JSON nhúng trong trang, dữ liệu gốc từ weather.com) ──

_BAOMOI_URL = "https://baomoi.com/tien-ich-thoi-tiet-{slug}.epi"
_BAOMOI_DEFAULT_SLUG = "tp-ho-chi-minh"
_BAOMOI_PAGE_TTL_SECONDS = 10 * 60
_BOARDS_TTL_SECONDS = 24 * 60 * 60
_boards_cache: Optional[tuple[float, list[dict]]] = None
_baomoi_page_cache: dict[str, tuple[float, dict]] = {}

# Dùng khi Báo Mới không tải được danh sách: tên tỉnh thành -> slug suy ra từ tên (không có toạ độ, sẽ geocode).
_BOARD_NAMES_FALLBACK = (
    "TP. Hồ Chí Minh", "Hà Nội", "Đà Nẵng", "An Giang", "Bắc Ninh", "Cà Mau", "Cần Thơ", "Cao Bằng",
    "Đắk Lắk", "Điện Biên", "Đồng Nai", "Đồng Tháp", "Gia Lai", "Hà Tĩnh", "Hải Phòng", "Hưng Yên",
    "Khánh Hòa", "Lai Châu", "Lâm Đồng", "Lạng Sơn", "Lào Cai", "Nghệ An", "Ninh Bình", "Phú Thọ",
    "Quảng Ngãi", "Quảng Ninh", "Quảng Trị", "Sơn La", "Tây Ninh", "Thái Nguyên", "Thanh Hóa",
    "Thừa Thiên Huế", "Tuyên Quang", "Vĩnh Long",
)
_PROVINCE_ALIASES = {
    "hcm": "tp-ho-chi-minh", "tphcm": "tp-ho-chi-minh", "sai gon": "tp-ho-chi-minh",
    "saigon": "tp-ho-chi-minh", "hue": "thua-thien-hue",
}


def _fold(text: str) -> str:
    """Thường hóa, bỏ dấu tiếng Việt, ký tự lạ thành khoảng trắng: 'Đà Nẵng!' -> 'da nang'."""
    text = unicodedata.normalize("NFD", (text or "").lower().replace("đ", "d"))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _board_key(name: str) -> str:
    return re.sub(r"^(tp|thanh pho) ", "", _fold(name))


def _vn_hour() -> int:
    return datetime.now(timezone(timedelta(hours=7))).hour


def _resolve_province(text: str, boards: list[dict]) -> Optional[dict]:
    """Câu/tên người dùng -> tỉnh thành của Báo Mới (khớp tên, bí danh, tên nằm giữa câu, gõ sai nhẹ)."""
    q = _board_key(text)
    if not q:
        return None
    by_slug = {b["slug"]: b for b in boards}
    keys = {_board_key(b["name"]): b for b in boards}
    if q in _PROVINCE_ALIASES and _PROVINCE_ALIASES[q] in by_slug:
        return by_slug[_PROVINCE_ALIASES[q]]
    if q in keys:
        return keys[q]
    padded = f" {q} "
    inside = [k for k in keys if f" {k} " in padded]
    if inside:
        return keys[max(inside, key=len)]
    for alias, slug in _PROVINCE_ALIASES.items():
        if f" {alias} " in padded and slug in by_slug:
            return by_slug[slug]
    close = difflib.get_close_matches(q, keys, n=1, cutoff=0.85)
    return keys[close[0]] if close else None


def _fallback_boards() -> list[dict]:
    return [{"name": n, "slug": _fold(n).replace(" ", "-"), "lat": None, "lon": None} for n in _BOARD_NAMES_FALLBACK]


def _to_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _baomoi_day(entry: dict) -> dict:
    hours = []
    for h in entry.get("hours") or []:
        try:
            hours.append({
                "h": int(h["hours"]), "temp": round(h["temperature"]), "hum": h.get("humidity"),
                "wind": h.get("wind"), "pop": h.get("pop"), "status": h.get("status") or "",
            })
        except (KeyError, TypeError, ValueError):
            continue
    return {
        "date": entry["date"], "status": entry.get("status") or "",
        "tmin": int(entry["temperatureMin24Hour"]), "tmax": int(entry["temperatureMax24Hour"]),
        "pop_day": (entry.get("day") or {}).get("pop"), "pop_night": (entry.get("night") or {}).get("pop"),
        "hours": hours,
    }


def _baomoi_parse(html: str) -> Optional[dict]:
    """Đọc JSON __NEXT_DATA__ của trang Báo Mới. Trang đổi cấu trúc hoặc bị chặn bot thì trả None
    (không đoán): {name, lat, lon, boards: [{name, slug, lat, lon}], days: [{date, tmin, tmax, hours: [...]}]}."""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html or "", re.S)
    if not m:
        return None
    try:
        content = json.loads(m.group(1))["props"]["pageProps"]["resp"]["data"]["content"]
        board = content["activeBoard"]
        days = []
        for entry in board["entries"]:
            try:
                days.append(_baomoi_day(entry))
            except (KeyError, TypeError, ValueError):
                continue
        if not days or not days[0]["hours"]:
            return None
        boards = [
            {"name": b["displayName"], "slug": b["shortName"], "lat": _to_float(b.get("latitude")), "lon": _to_float(b.get("longitude"))}
            for b in content.get("boards") or []
        ]
        return {
            "name": board["displayName"], "lat": _to_float(board.get("latitude")), "lon": _to_float(board.get("longitude")),
            "boards": boards, "days": days,
        }
    except (KeyError, TypeError, ValueError):
        return None


def _baomoi_current(days: list[dict], hour: int) -> dict:
    """Mốc giờ gần nhất không sớm hơn `hour` trong hôm nay (trang chỉ liệt kê từ giờ hiện tại trở đi)."""
    hours = days[0]["hours"]
    return next((h for h in hours if h["h"] >= hour), hours[-1])


async def _baomoi_fetch(slug: str) -> dict:
    cached = _baomoi_page_cache.get(slug)
    if cached and time.time() - cached[0] < _BAOMOI_PAGE_TTL_SECONDS:
        return cached[1]
    url = _BAOMOI_URL.format(slug=slug)
    page, used_stealth = await browser._fetch(url, timeout_ms=10_000)
    if page is None or (page.status and page.status >= 400):
        raise ValueError(f"Scrapling không tải được Báo Mới (HTTP {getattr(page, 'status', None)})")
    parsed = _baomoi_parse(str(page.html_content))
    if not parsed:
        log.warning("Scrapling tải Báo Mới nhưng không parse được dữ liệu (stealth=%s)", used_stealth)
        raise ValueError("Báo Mới đổi giao diện hoặc không trả nội dung thời tiết có cấu trúc")
    global _boards_cache
    if parsed["boards"]:
        _boards_cache = (time.time(), parsed["boards"])
    _baomoi_page_cache[slug] = (time.time(), parsed)
    return parsed


async def _load_boards() -> list[dict]:
    """Danh sách tỉnh thành lấy từ Báo Mới (cache 24 giờ); không tải được thì dùng danh sách tĩnh."""
    if _boards_cache and time.time() - _boards_cache[0] < _BOARDS_TTL_SECONDS:
        return _boards_cache[1]
    try:
        await _baomoi_fetch(_BAOMOI_DEFAULT_SLUG)
    except Exception as e:
        log.warning(f"Không tải được danh sách tỉnh thành từ Báo Mới: {e}")
    return _boards_cache[1] if _boards_cache else _fallback_boards()


def _format_baomoi(p: dict, hour: int) -> str:
    cur, today = _baomoi_current(p["days"], hour), p["days"][0]
    lines = [f"📍 Thời tiết tại {p['name']} (lúc {cur['h']:02d}:00):"]
    lines.append(f"  🌡  Nhiệt độ: {cur['temp']}°C (hôm nay {today['tmin']}–{today['tmax']}°C).")
    if cur["status"]:
        lines.append(f"  ☁️  {cur['status']}.")
    if cur["hum"] is not None:
        lines.append(f"  💧 Độ ẩm: {cur['hum']}%.")
    if cur["wind"] is not None:
        lines.append(f"  🌬  Gió: {cur['wind']} km/h.")
    if cur["pop"] is not None:
        lines.append(f"  🌧  Khả năng mưa: {cur['pop']}%.")
    return "\n".join(lines)


def _format_baomoi_hourly(p: dict, hour: int) -> str:
    """Dự phòng khi Open-Meteo bị giới hạn: 24 giờ kế tiếp từ hôm nay sang ngày mai."""
    rows = [(d["date"], h) for d in p["days"][:2] for h in d["hours"]]
    today = p["days"][0]["date"]
    start = next((i for i, (date, h) in enumerate(rows) if date == today and h["h"] >= hour), 0)
    lines = [f"🌧 Khả năng mưa theo giờ tại {p['name']}:"]
    for date, h in rows[start:start + 24]:
        label = f"{h['h']:02d}:00" if date == today else f"{date[:5]} {h['h']:02d}:00"
        lines.append(f"  {label} — {h['pop'] if h['pop'] is not None else '?'}%")
    return "\n".join(lines)


# ── Legacy API (giữ cho greeting engine) ──

WEATHER_TRANSLATIONS = {
    "sunny": "trời nắng",
    "clear": "trời quang mây tạnh",
    "partly cloudy": "trời có mây rải rác",
    "cloudy": "trời nhiều mây",
    "overcast": "trời u ám",
    "mist": "sương mù nhẹ",
    "fog": "sương mù",
    "thunderstorm": "bão giông",
    "patchy rain nearby": "mưa rải rác gần đây",
    "patchy rain possible": "có thể có mưa rải rác",
    "patchy snow possible": "có thể có tuyết rải rác",
    "patchy sleet possible": "có thể có mưa tuyết rải rác",
    "patchy freezing drizzle possible": "có thể có mưa phùn băng giá",
    "thundery outbreaks in nearby": "có giông gần đây",
    "thundery outbreaks possible": "có thể có giông bão",
    "blowing snow": "tuyết thổi",
    "blizzard": "bão tuyết",
    "freezing fog": "sương mù đóng băng",
    "patchy light drizzle": "mưa phùn nhẹ rải rác",
    "light drizzle": "mưa phùn nhẹ",
    "freezing drizzle": "mưa phùn đóng băng",
    "heavy freezing drizzle": "mưa phùn đóng băng nặng hạt",
    "patchy light rain": "mưa nhẹ rải rác",
    "light rain": "mưa nhẹ",
    "moderate rain at times": "đôi khi có mưa vừa",
    "moderate rain": "mưa vừa",
    "heavy rain at times": "đôi khi có mưa to",
    "heavy rain": "mưa to",
    "light freezing rain": "mưa băng nhẹ",
    "moderate or heavy freezing rain": "mưa băng vừa hoặc mưa băng to",
    "light sleet": "mưa tuyết nhẹ",
    "moderate or heavy sleet": "mưa tuyết vừa hoặc mưa tuyết nặng",
    "patchy light snow": "tuyết rơi nhẹ rải rác",
    "light snow": "tuyết rơi nhẹ",
    "patchy moderate snow": "tuyết rơi vừa rải rác",
    "moderate snow": "tuyết rơi vừa",
    "patchy heavy snow": "tuyết rơi nhiều rải rác",
    "heavy snow": "tuyết rơi nhiều",
    "ice pellets": "mưa đá nhỏ",
    "light rain shower": "mưa rào nhẹ",
    "moderate or heavy rain shower": "mưa rào vừa hoặc mưa rào to",
    "torrential rain shower": "mưa rào như trút nước",
    "light sleet showers": "mưa tuyết rào nhẹ",
    "moderate or heavy sleet showers": "mưa tuyết rào vừa hoặc mưa tuyết rào to",
    "light snow showers": "tuyết rào nhẹ",
    "moderate or heavy snow showers": "tuyết rào vừa hoặc tuyết rào to",
    "light showers of ice pellets": "mưa đá rào nhẹ",
    "moderate or heavy showers of ice pellets": "mưa đá rào vừa hoặc mưa đá rào to",
    "patchy light rain with thunder": "mưa nhẹ rải rác kèm giông",
    "moderate or heavy rain with thunder": "mưa vừa hoặc mưa to kèm giông",
    "patchy light snow with thunder": "tuyết nhẹ rải rác kèm giông",
    "moderate or heavy snow with thunder": "tuyết vừa hoặc tuyết to kèm giông",
    "rain with thunderstorm": "mưa giông",
    "smoky haze": "trời mù khói bụi",
    "haze": "trời mù khói bụi",
}

def translate_weather_desc(desc: str) -> str:
    if not desc:
        return ""
    cleaned = desc.strip().lower()
    if cleaned in WEATHER_TRANSLATIONS:
        return WEATHER_TRANSLATIONS[cleaned]
    for en, vi in WEATHER_TRANSLATIONS.items():
        if en in cleaned:
            return vi
    return desc

_LOCATION_NAME = "Hồ Chí Minh"
_HCM_LAT, _HCM_LON = 10.762622, 106.660172
# Open-Meteo free giới hạn lượt gọi: dính 429 thì nghỉ nguồn này một lúc thay vì gọi lại liên tục.
_OPEN_METEO_COOLDOWN_SECONDS = 15 * 60
# Thời tiết không đổi từng phút: dùng lại kết quả gần đây để đỡ tốn lượt gọi.
_SNAPSHOT_TTL_SECONDS = 10 * 60
# Mọi nguồn đều lỗi thì vẫn dùng kết quả cũ nếu chưa quá hạn này.
_SNAPSHOT_STALE_SECONDS = 60 * 60
_open_meteo_blocked_until = 0.0
_snapshot_cache: Optional[tuple[float, dict]] = None


def _is_rate_limited(e: Exception) -> bool:
    if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 429:
        return True
    msg = str(e).lower()
    return "429" in msg or "limit exceeded" in msg or "too many requests" in msg


def _mark_open_meteo_limited() -> None:
    global _open_meteo_blocked_until
    _open_meteo_blocked_until = time.time() + _OPEN_METEO_COOLDOWN_SECONDS


def _describe_open_meteo(code, cloud_cover, is_day) -> str:
    """Mã WMO 0-3 chỉ phân loại mây rất thô (vd. mã 1 nhưng mây 42%); dùng % mây thật
    để biết là nắng hay nhiều mây. Có mưa/sương/giông (mã >= 45) thì theo mã."""
    code = int(code or 0)
    if code >= 45 or cloud_cover is None:
        return _wmo_text(code).lower()
    day = bool(is_day)
    if cloud_cover < 20:
        return "trời nắng đẹp" if day else "trời quang"
    if cloud_cover < 50:
        return "trời nắng, có ít mây" if day else "trời ít mây"
    if cloud_cover < 85:
        return "trời nhiều mây"
    return "trời u ám"


def _classify(desc: str) -> Optional[str]:
    """Nhóm bầu trời cho lời nhắc. Thứ tự quan trọng: 'sương mù khói' là khói bụi, không phải sương."""
    d = (desc or "").lower()
    for kind, keys in (
        ("storm", ("giông", "bão", "thunder", "storm")),
        ("rain", ("mưa", "rain", "drizzle", "shower")),
        ("snow", ("tuyết", "snow")),
        ("haze", ("khói", "bụi", "haze", "smoke")),
        ("fog", ("sương", "fog", "mist")),
        ("clear", ("nắng", "quang", "trong xanh", "sunny", "clear")),
        ("cloudy", ("mây", "u ám", "cloud", "overcast")),
    ):
        if any(k in d for k in keys):
            return kind
    return None


async def _open_meteo_snapshot() -> dict:
    data = await _fetch_open_meteo(_HCM_LAT, _HCM_LON)
    cur = data.get("current", {})
    temp = cur.get("temperature_2m")
    return {
        "desc": _describe_open_meteo(cur.get("weathercode"), cur.get("cloud_cover"), cur.get("is_day", 1)),
        "temp": round(temp) if temp is not None else None,
        "is_day": bool(cur.get("is_day", 1)),
        "source": "open-meteo",
    }


async def _wttr_snapshot(query: str = "Ho Chi Minh City") -> Optional[dict]:
    query = _api_location_name(query)
    async with httpx.AsyncClient(timeout=5.0) as http:
        resp = await http.get(
            f"https://wttr.in/{quote(query, safe=',')}",
            params={"format": "%C|%t", "lang": "en"},
        )
        resp.raise_for_status()
    desc_en, _, temp_raw = resp.text.strip().partition("|")
    m = re.search(r"-?\d+", temp_raw)
    # wttr trả trang lỗi/HTML khi quá tải; không đúng dạng "Mô tả|+31°C" thì bỏ.
    if not m or not desc_en or len(desc_en) > 60 or "<" in desc_en:
        return None
    return {"desc": translate_weather_desc(desc_en).lower(), "temp": int(m.group()), "is_day": None, "source": "wttr"}


async def _baomoi_fetch_snapshot() -> Optional[dict]:
    cur = _baomoi_current((await _baomoi_fetch(_BAOMOI_DEFAULT_SLUG))["days"], _vn_hour())
    status = cur["status"]
    if not status:
        return None
    return {"desc": status[0].lower() + status[1:], "temp": cur["temp"], "is_day": None, "source": "baomoi"}


async def fetch_weather_snapshot() -> Optional[dict]:
    """Thời tiết hiện tại ở dạng có cấu trúc: {desc, temp, is_day, kind, source, text}.
    Thứ tự: Open-Meteo (số đo chính xác) -> wttr.in (free, khi Open-Meteo bị limit/lỗi)
    -> Báo Mới (cào web, dễ bị chặn bot nên để cuối)."""
    global _snapshot_cache
    now = time.time()
    if _snapshot_cache and now - _snapshot_cache[0] < _SNAPSHOT_TTL_SECONDS:
        return _snapshot_cache[1]

    sources = []
    if now >= _open_meteo_blocked_until:
        sources.append(("open-meteo", _open_meteo_snapshot))
    sources += [("wttr", _wttr_snapshot), ("baomoi", _baomoi_fetch_snapshot)]

    for name, fetch in sources:
        try:
            snap = await fetch()
        except Exception as e:
            if name == "open-meteo" and _is_rate_limited(e):
                _mark_open_meteo_limited()
                log.warning("Open-Meteo rate limited; dùng nguồn khác trong %d phút", _OPEN_METEO_COOLDOWN_SECONDS // 60)
            else:
                log.warning(f"Weather source {name} failed: {e}")
            continue
        if snap and snap.get("desc"):
            snap["kind"] = _classify(snap["desc"])
            temp = f", nhiệt độ {snap['temp']}°C" if snap.get("temp") is not None else ""
            snap["text"] = f"Thời tiết tại {_LOCATION_NAME} hiện tại là {snap['desc']}{temp}"
            _snapshot_cache = (now, snap)
            _ctx_cache["weather"] = snap["text"]
            return snap

    if _snapshot_cache and now - _snapshot_cache[0] < _SNAPSHOT_STALE_SECONDS:
        return _snapshot_cache[1]
    return None


async def fetch_weather() -> str:
    """Bản chữ của fetch_weather_snapshot (dùng làm fallback cho weather_search)."""
    snap = await fetch_weather_snapshot()
    return snap["text"] if snap else "Hiện chưa có thông tin thời tiết."

import hashlib
from dataclasses import asdict, replace
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from scrapling.fetchers import Fetcher
from scrapling.parser import Selector

from .analysis import validate_numbers
from .models import Draw, PrizeTier


OFFICIAL_RESULT_URLS = {
    "mega645": "https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/winning-number-645",
    "power655": "https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/winning-number-655",
}
CACHE_DIR = Path("data") / "analytics"
CURRENT_JACKPOT_URL = "https://vietlott.vn/"
DEFAULT_SYNC_STATE = {"next_page": 0, "complete": False}


def _body_text(response) -> str:
    body = response.body
    return body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body)


def fetch_official_page(game: str) -> tuple[str, str]:
    if game not in OFFICIAL_RESULT_URLS:
        raise ValueError(f"unsupported game: {game}")
    url = OFFICIAL_RESULT_URLS[game]
    response = Fetcher.get(url, stealthy_headers=True, impersonate="chrome")
    if response.status and response.status >= 400:
        raise OSError(f"Vietlott HTTP {response.status}")
    return url, _body_text(response)


def fetch_winning_number_pages(game: str, max_pages: int = 200, start_page: int = 0) -> list[tuple[str, str]]:
    """Render Vietlott's public NextPage(n) results until pagination is exhausted."""
    if game not in OFFICIAL_RESULT_URLS:
        raise ValueError(f"unsupported game: {game}")
    url = OFFICIAL_RESULT_URLS[game]
    headers = {"Content-Type": "text/plain; charset=utf-8"}
    initial_url, initial_html = fetch_official_page(game)
    key_match = re.search(r"ServerSideDrawResult\(RenderInfo, '([^']+)'", initial_html)
    if not key_match:
        raise OSError("Vietlott AjaxPro page key not found")
    render_url = "https://vietlott.vn/ajaxpro/Vietlott.Utility.WebEnvironments,Vietlott.Utility.ashx"
    response = Fetcher.post(
        render_url,
        data=json.dumps({"SiteId": "main.frontend.vi"}),
        headers=headers | {
            "X-AjaxPro-Method": "ServerSideFrontEndCreateRenderInfo"
        },
        stealthy_headers=True,
        impersonate="chrome",
    )
    render_info = json.loads(_body_text(response))["value"]
    endpoint = "https://vietlott.vn/ajaxpro/Vietlott.PlugIn.WebParts.Game%sCompareWebPart,Vietlott.PlugIn.WebParts.ashx" % ("645" if game == "mega645" else "655")
    pages, seen = [], set()
    if start_page == 0:
        pages.append((initial_url + "#page=0", initial_html))
        seen.update(draw.draw_id for draw in parse_official_draws(game, (initial_url, initial_html)))
    for index in range(max(1, start_page), start_page + max_pages):
        payload = {"ORenderInfo": render_info, "Key": key_match.group(1), "GameDrawId": "", "ArrayNumbers": [[""] * 18 for _ in range(6)], "CheckMulti": False, "PageIndex": index}
        response = Fetcher.post(
            endpoint,
            data=json.dumps(payload),
            headers=headers | {"X-AjaxPro-Method": "ServerSideDrawResult"},
            stealthy_headers=True,
            impersonate="chrome",
        )
        fragment = json.loads(_body_text(response))["value"].get("HtmlContent", "")
        draws = parse_official_draws(game, (url, fragment))
        new_ids = {draw.draw_id for draw in draws} - seen
        if not new_ids:
            break
        seen.update(new_ids)
        pages.append((url + f"#page={index}", fragment))
    return pages


def parse_official_draws(game: str, page: tuple[str, str]) -> list[Draw]:
    source_url, html = page
    selector = Selector(html)
    draws = []
    digest = hashlib.sha256(html.encode("utf-8")).hexdigest()
    for row in selector.css("#divResultContent tbody tr, table tbody tr"):
        cells = row.css("td")
        if len(cells) < 3:
            continue
        draw_date = str(cells[0].css("::text").get() or "").strip()
        draw_id = str(cells[1].css("a::text").get() or "").strip()
        href = str(cells[1].css("a::attr(href)").get() or "").strip()
        values = [
            int(value)
            for value in cells[2].css("span::text").getall()
            if str(value).strip().isdigit()
        ]
        if not draw_id or len(values) < 6:
            continue
        try:
            numbers = validate_numbers(game, values[:6])
        except ValueError:
            continue
        special_number = (
            values[6] if game == "power655" and len(values) > 6 else None
        )
        draws.append(
            Draw(
                game,
                draw_id,
                draw_date,
                numbers,
                source_url,
                digest,
                special_number=special_number,
                detail_url=urljoin("https://vietlott.vn", href),
            )
        )
    if draws:
        return draws

    compact = re.sub(r"<[^>]+>", " ", html)
    groups = re.finditer(r"(?<!\d)(\d{1,2})\s*[-|,\s]+(\d{1,2})\s*[-|,\s]+(\d{1,2})\s*[-|,\s]+(\d{1,2})\s*[-|,\s]+(\d{1,2})\s*[-|,\s]+(\d{1,2})(?!\d)", compact)
    seen = set()
    for index, match in enumerate(groups, start=1):
        try:
            numbers = validate_numbers(
                game, tuple(int(value) for value in match.groups())
            )
        except ValueError:
            continue
        if numbers in seen:
            continue
        seen.add(numbers)
        metadata = compact[max(0, match.start() - 180):match.start()]
        matches = list(re.finditer(r"Kỳ quay thưởng\s*[:|]?\s*(\d+).*?Ngày quay thưởng\s*[:|]?\s*(\d{2}/\d{2}/\d{4})", metadata, flags=re.IGNORECASE | re.DOTALL))
        draw_id, draw_date = matches[-1].groups() if matches else (f"page-{index}", "unknown")
        draws.append(Draw(game, draw_id, draw_date, numbers, source_url, digest))
    return draws


def _parse_vnd(value: str) -> int:
    digits = re.sub(r"\D", "", value)
    return int(digits) if digits else 0


def _element_text(element) -> str:
    return " ".join(
        str(value).strip()
        for value in element.css("::text").getall()
        if str(value).strip()
    )


def parse_draw_detail(html: str) -> tuple[PrizeTier, ...]:
    selector = Selector(html)
    tiers = []
    for row in selector.css(".chitietketqua_table table tbody tr"):
        cells = row.css("td")
        if len(cells) < 4:
            continue
        tiers.append(
            PrizeTier(
                name=_element_text(cells[0]),
                match_pattern=_element_text(cells[1]),
                winner_count=_parse_vnd(_element_text(cells[2])),
                prize_value_vnd=_parse_vnd(_element_text(cells[3])),
            )
        )
    return tuple(tiers)


def fetch_draw_detail(draw: Draw, fetcher=Fetcher.get) -> Draw:
    if not draw.detail_url:
        return draw
    response = fetcher(
        draw.detail_url,
        stealthy_headers=True,
        impersonate="chrome",
    )
    tiers = parse_draw_detail(_body_text(response))
    return replace(
        draw,
        prize_tiers=tiers,
        detail_retrieved_at=datetime.now(timezone.utc).isoformat(),
    )


def parse_current_jackpots(html: str) -> dict[str, list[dict]]:
    text = " ".join(Selector(html).get_all_text().split())
    definitions = {
        "mega645": [
            ("Jackpot", r"Jackpot Mega 6/45 ước tính\s+([\d.]+)\s*VNĐ")
        ],
        "power655": [
            (
                "Jackpot 1",
                r"Jackpot 1 Power 6/55 ước tính\s+([\d.]+)\s*VNĐ",
            ),
            (
                "Jackpot 2",
                r"Jackpot 2 Power 6/55 ước tính\s+([\d.]+)\s*VNĐ",
            ),
        ],
    }
    result = {}
    for game, patterns in definitions.items():
        values = []
        for name, pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                values.append(
                    {
                        "name": name,
                        "value_vnd": _parse_vnd(match.group(1)),
                        "source_status": "verified",
                        "source_url": CURRENT_JACKPOT_URL,
                    }
                )
        result[game] = values
    return result


def fetch_current_jackpots() -> dict[str, list[dict]]:
    response = Fetcher.get(
        CURRENT_JACKPOT_URL,
        stealthy_headers=True,
        impersonate="chrome",
    )
    if response.status and response.status >= 400:
        raise OSError(f"Vietlott HTTP {response.status}")
    return parse_current_jackpots(_body_text(response))


def _draw_from_dict(item: dict) -> Draw:
    tiers = tuple(
        PrizeTier(
            name=tier["name"],
            winner_count=int(tier.get("winner_count", 0)),
            prize_value_vnd=int(tier.get("prize_value_vnd", 0)),
            match_pattern=tier.get("match_pattern", ""),
        )
        for tier in item.get("prize_tiers", [])
    )
    return Draw(
        game=item["game"],
        draw_id=item["draw_id"],
        draw_date=item["draw_date"],
        numbers=tuple(item["numbers"]),
        source_url=item["source_url"],
        content_hash=item["content_hash"],
        special_number=item.get("special_number"),
        detail_url=item.get("detail_url", ""),
        prize_tiers=tiers,
        detail_retrieved_at=item.get("detail_retrieved_at", ""),
    )


def load_sync_state(game: str) -> dict:
    path = CACHE_DIR / f"{game}.json"
    if not path.exists():
        return dict(DEFAULT_SYNC_STATE)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        state = payload.get("sync", DEFAULT_SYNC_STATE)
        return {
            "next_page": max(0, int(state.get("next_page", 0))),
            "complete": bool(state.get("complete", False)),
        }
    except (OSError, ValueError, KeyError, TypeError):
        return dict(DEFAULT_SYNC_STATE)


def save_draw_cache(
    game: str,
    draws: list[Draw],
    sync_state: dict | None = None,
) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = CACHE_DIR / f"{game}.json"
    temporary = target.with_suffix(".json.tmp")
    payload = {
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "sync": sync_state or load_sync_state(game),
        "draws": [asdict(draw) for draw in draws],
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    temporary.write_text(serialized, encoding="utf-8")
    try:
        temporary.replace(target)
    except PermissionError:
        # Some Windows hosts deny replacing an existing writable cache file.
        target.write_text(serialized, encoding="utf-8")
        temporary.unlink(missing_ok=True)


def load_draw_cache(game: str) -> list[Draw]:
    path = CACHE_DIR / f"{game}.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [_draw_from_dict(item) for item in payload.get("draws", [])]
    except (OSError, ValueError, KeyError, TypeError):
        return []

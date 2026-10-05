import asyncio

from .analysis import (
    build_report,
    format_report_text,
    unpublished_current_jackpots,
)
from .models import Draw
from .source import (
    fetch_current_jackpots,
    fetch_draw_detail,
    fetch_official_page,
    fetch_winning_number_pages,
    load_draw_cache,
    load_sync_state,
    parse_official_draws,
    save_draw_cache,
)


SUPPORTED_GAMES = {"mega645", "power655"}


def _draw_key(draw: Draw) -> tuple[int, str]:
    return (
        int(draw.draw_id) if str(draw.draw_id).isdigit() else -1,
        str(draw.draw_id),
    )


def _completeness(draw: Draw) -> tuple[int, int, int]:
    return (
        int(bool(draw.prize_tiers)),
        int(draw.special_number is not None),
        int(bool(draw.detail_url)),
    )


def merge_draws(cached: list[Draw], fresh: list[Draw]) -> list[Draw]:
    merged = {draw.draw_id: draw for draw in cached if draw.draw_id}
    for draw in fresh:
        current = merged.get(draw.draw_id)
        if current is None or _completeness(draw) > _completeness(current):
            merged[draw.draw_id] = draw
    return sorted(merged.values(), key=_draw_key)


def _parse_pages(game: str, pages: list[tuple[str, str]]) -> list[Draw]:
    return [
        draw
        for page in pages
        for draw in parse_official_draws(game, page)
        if draw.draw_id and draw.draw_id != "unknown"
    ]


def analyze_game(
    game: str,
    fetcher=fetch_official_page,
    max_pages: int = 5,
    start_page: int = 0,
    advertised_jackpots: list[dict] | None = None,
    sync_all: bool = False,
) -> dict:
    if game not in SUPPORTED_GAMES:
        return {
            "game": game,
            "source_status": "unavailable",
            "error": f"unsupported game: {game}",
            "warning": "Game Vietlott không được hỗ trợ.",
        }
    try:
        cached_draws = load_draw_cache(game)
        cached_ids = {draw.draw_id for draw in cached_draws}
        recent_pages = []
        state = load_sync_state(game)

        if fetcher is fetch_official_page:
            recent_pages = fetch_winning_number_pages(
                game,
                max_pages=max_pages,
                start_page=start_page,
            )
            fresh_draws = _parse_pages(game, recent_pages)
            merged = merge_draws(cached_draws, fresh_draws)

            while not state["complete"]:
                history_pages = fetch_winning_number_pages(
                    game,
                    max_pages=20,
                    start_page=state["next_page"],
                )
                history_draws = _parse_pages(game, history_pages)
                merged = merge_draws(merged, history_draws)
                state = {
                    "next_page": state["next_page"] + len(history_pages),
                    "complete": len(history_pages) < 20,
                }
                save_draw_cache(game, merged, sync_state=state)
                if not sync_all:
                    break
        else:
            page = fetcher(game)
            fresh_draws = parse_official_draws(game, page)
            merged = merge_draws(cached_draws, fresh_draws)

        if not merged:
            return {
                "game": game,
                "source_status": "empty",
                "warning": (
                    "Không có kỳ quay hợp lệ từ trang kết quả công khai "
                    "Vietlott."
                ),
            }

        latest = max(merged, key=_draw_key)
        if latest.detail_url and not latest.prize_tiers:
            try:
                detailed = fetch_draw_detail(latest)
                merged = merge_draws(merged, [detailed])
            except (OSError, RuntimeError, ValueError):
                pass

        if len(merged) < len(cached_draws):
            raise ValueError("incremental merge would shrink Vietlott cache")
        save_draw_cache(game, merged, sync_state=state)

        report = build_report(
            game,
            merged,
            advertised_jackpots or unpublished_current_jackpots(game),
        )
        report["source"] = {
            "type": "vietlott_winning_number_pages",
            "pages_scanned": len(recent_pages) if recent_pages else 1,
            "new_draws": len(
                {draw.draw_id for draw in merged} - cached_ids
            ),
            "cached_draws": len(cached_draws),
            "sync": state,
        }
        return report
    except (OSError, RuntimeError, TimeoutError, ValueError, KeyError) as exc:
        return {
            "game": game,
            "source_status": "unavailable",
            "error": str(exc),
            "warning": (
                "Không có dữ liệu chính thức đã xác thực; "
                "không tạo phân tích hoặc bộ số tham khảo."
            ),
        }


async def run_vietlott_analysis(arguments: dict) -> dict:
    games = arguments.get("games") or ["mega645", "power655"]
    max_pages = max(1, min(int(arguments.get("max_pages", 5)), 20))
    start_page = max(0, int(arguments.get("start_page", 0)))
    sync_all = bool(arguments.get("sync_all", False))
    try:
        advertised = await asyncio.to_thread(fetch_current_jackpots)
    except (OSError, RuntimeError, ValueError):
        advertised = {}

    results = []
    for game in games:
        results.append(
            await asyncio.to_thread(
                analyze_game,
                game,
                fetch_official_page,
                max_pages,
                start_page,
                advertised.get(game)
                or unpublished_current_jackpots(game),
                sync_all,
            )
        )
    return {"results": results, "text": format_report_text(results)}

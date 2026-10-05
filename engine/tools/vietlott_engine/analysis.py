import random
from collections import Counter
from dataclasses import asdict
from math import comb

from .evaluation import (
    backtest_strategies,
    prize_probabilities,
    uniformity_test,
)
from .models import GAME_LIMITS, Draw


GAME_LABELS = {"mega645": "Mega 6/45", "power655": "Power 6/55"}
BIRTHDAY_MAX = 31
HOT_WINDOW = 30


def validate_numbers(game: str, numbers) -> tuple[int, ...]:
    if game not in GAME_LIMITS:
        raise ValueError(f"unsupported game: {game}")
    normalized = tuple(sorted(int(number) for number in numbers))
    if len(normalized) != 6 or len(set(normalized)) != 6:
        raise ValueError("a ticket must contain six distinct numbers")
    if any(number < 1 or number > GAME_LIMITS[game] for number in normalized):
        raise ValueError("number outside game range")
    return normalized


def _draw_key(draw: Draw) -> tuple[int, str]:
    return (
        int(draw.draw_id) if str(draw.draw_id).isdigit() else -1,
        str(draw.draw_id),
    )


def _hot_numbers(game: str, ordered: list[Draw], top: int = 10) -> set[int]:
    recent = Counter(
        number for draw in ordered[-HOT_WINDOW:] for number in draw.numbers
    )
    ranked = sorted(
        range(1, GAME_LIMITS[game] + 1), key=lambda x: (-recent[x], x)
    )
    return set(ranked[:top])


def popularity_flags(
    ticket: tuple[int, ...],
    hot: set[int] = frozenset(),
) -> list[str]:
    """Các mẫu số nhiều người cùng chọn -> nếu trúng Jackpot dễ phải chia giải."""
    flags = []
    if sum(number <= BIRTHDAY_MAX for number in ticket) >= 5:
        flags.append("nhiều số ngày sinh (≤31)")
    run = longest = 1
    for previous, current in zip(ticket, ticket[1:]):
        run = run + 1 if current == previous + 1 else 1
        longest = max(longest, run)
    if longest >= 3:
        flags.append("dãy số liên tiếp")
    gaps = {current - previous for previous, current in zip(ticket, ticket[1:])}
    if len(gaps) == 1:
        flags.append("cấp số cộng")
    if max(Counter(number % 10 for number in ticket).values()) >= 4:
        flags.append("cùng chữ số tận cùng")
    if len(set(ticket) & hot) >= 3:
        flags.append("theo số nóng đang được công bố")
    return flags


def build_reference_tickets(
    game: str,
    draws: list[Draw],
    count: int = 3,
    rng: random.Random | None = None,
) -> list[dict]:
    """Bộ số ngẫu nhiên đều, loại các mẫu phổ biến.

    Không bộ số nào có xác suất trúng cao hơn bộ khác; tránh mẫu phổ biến chỉ
    giảm khả năng phải chia Jackpot với người khác nếu trúng.
    """
    game_draws = sorted(
        (draw for draw in draws if draw.game == game), key=_draw_key
    )
    if not game_draws:
        return []
    rng = rng or random.SystemRandom()
    hot = _hot_numbers(game, game_draws)
    past = {draw.numbers for draw in game_draws}
    results, seen = [], set()
    while len(results) < count:
        ticket = tuple(sorted(rng.sample(range(1, GAME_LIMITS[game] + 1), 6)))
        if ticket in seen or ticket in past or popularity_flags(ticket, hot):
            continue
        seen.add(ticket)
        results.append(
            {
                "ticket": list(ticket),
                "method": "ngẫu nhiên đều, tránh mẫu số phổ biến",
            }
        )
    return results


def unpublished_current_jackpots(game: str) -> list[dict]:
    names = ["Jackpot"] if game == "mega645" else ["Jackpot 1", "Jackpot 2"]
    return [
        {
            "name": name,
            "source_status": "not_published",
            "value_vnd": None,
            "source_url": "",
            "warning": (
                "Nguồn chính thức chưa công bố Jackpot kỳ tiếp theo; "
                "hệ thống không tự suy đoán."
            ),
        }
        for name in names
    ]


def build_report(
    game: str,
    draws: list[Draw],
    advertised_jackpots: list[dict] | None = None,
) -> dict:
    game_draws = sorted(
        (draw for draw in draws if draw.game == game), key=_draw_key
    )
    if not game_draws:
        return {
            "game": game,
            "game_label": GAME_LABELS.get(game, game),
            "source_status": "empty",
            "warning": "Nguồn không có kỳ quay hợp lệ để phân tích.",
        }
    latest = game_draws[-1]
    tiers = [asdict(tier) for tier in latest.prize_tiers]
    jackpots = []
    for tier in tiers:
        if tier["name"].lower().startswith("jackpot"):
            jackpots.append(
                {
                    **tier,
                    "status": (
                        "winner" if tier["winner_count"] > 0 else "no_winner"
                    ),
                }
            )
    odds = comb(GAME_LIMITS[game], 6)
    frequency = Counter(number for draw in game_draws for number in draw.numbers)
    return {
        "game": game,
        "game_label": GAME_LABELS.get(game, game),
        "source_status": "verified",
        "draw_count": len(game_draws),
        "latest_draw": {
            "draw_id": latest.draw_id,
            "draw_date": latest.draw_date,
            "numbers": list(latest.numbers),
            "special_number": latest.special_number,
            "detail_url": latest.detail_url,
            "detail_retrieved_at": latest.detail_retrieved_at,
            "prize_tiers": tiers,
        },
        "jackpots": jackpots,
        "current_advertised_jackpots": (
            advertised_jackpots or unpublished_current_jackpots(game)
        ),
        "reference_tickets": build_reference_tickets(game, game_draws),
        "most_frequent_numbers": [
            number for number, _ in frequency.most_common(10)
        ],
        "prize_probabilities": prize_probabilities(game),
        "uniformity": uniformity_test(game, game_draws),
        "backtest": backtest_strategies(game, game_draws),
        "theoretical_jackpot_odds": odds,
        "theoretical_probability_percent": round(100 / odds, 8),
        "reporting": {
            "draw_range": [game_draws[0].draw_id, latest.draw_id],
            "method": (
                "Xác suất siêu bội; chi-square đồng đều; backtest "
                "walk-forward các chiến lược số nóng/số gan/lặp kỳ trước."
            ),
        },
        "warning": (
            "Mỗi kỳ quay độc lập và ngẫu nhiên; không phương pháp nào "
            "dự đoán được kết quả."
        ),
    }


def _format_evaluation(report: dict) -> list[str]:
    lines = []
    prizes = report["prize_probabilities"]
    lines.append("Xác suất trúng của MỌI vé (không phụ thuộc bộ số chọn):")
    for tier in prizes["tiers"]:
        lines.append(f"- {tier['name']}: 1/{tier['one_in']:,}")
    lines.append(
        f"- Trúng bất kỳ giải nào: ~1/{prizes['any_prize_one_in']} "
        f"({prizes['any_prize_percent']:.2f}%)"
    )

    uniformity = report["uniformity"]
    verdict = (
        "có dấu hiệu lệch, cần theo dõi thêm"
        if uniformity["biased"]
        else "không phát hiện lệch, các số ra đều như ngẫu nhiên"
    )
    lines.append(
        f"Kiểm định ngẫu nhiên {uniformity['draw_count']} kỳ: "
        f"p = {uniformity['p_value']:.2f} → {verdict}."
    )

    backtest = report["backtest"]
    if backtest["test_draws"]:
        lines.append(
            f"Backtest {backtest['test_draws']} kỳ gần nhất "
            f"(ngẫu nhiên kỳ vọng {backtest['expected_mean_matches']:.2f} "
            f"số trùng/vé, trúng giải {backtest['expected_prize_hit_percent']:.2f}%):"
        )
        for item in backtest["strategies"]:
            lines.append(
                f"- {item['description']}: {item['mean_matches']:.2f} số/vé, "
                f"trúng giải {item['prize_hit_percent']:.2f}%"
            )
        if backtest["beats_chance"]:
            lines.append(
                "→ Có chiến lược vượt ngẫu nhiên ở mẫu này; nhiều khả năng "
                "do may rủi, chưa đủ để tin cậy."
            )
        else:
            lines.append(
                "→ Không chiến lược nào tốt hơn chọn ngẫu nhiên."
            )
    return lines


def format_report_text(results: list[dict]) -> str:
    sections = []
    for report in results:
        if report.get("source_status") != "verified":
            sections.append(
                f"{report.get('game_label', report.get('game', 'Vietlott'))}: "
                f"{report.get('warning', 'Nguồn chưa xác minh.')}"
            )
            continue
        latest = report["latest_draw"]
        numbers = " ".join(f"{number:02d}" for number in latest["numbers"])
        lines = [
            (
                f"{report['game_label']} — kỳ {latest['draw_id']}, "
                f"ngày {latest['draw_date']}"
            ),
            f"Bộ số: {numbers}",
        ]
        if latest.get("special_number") is not None:
            lines.append(f"Số đặc biệt: {latest['special_number']:02d}")
        if latest["prize_tiers"]:
            lines.append("Kết quả trúng giải kỳ mới nhất:")
            for tier in latest["prize_tiers"]:
                lines.append(
                    f"- {tier['name']}: {tier['prize_value_vnd']:,} đồng; "
                    f"{tier['winner_count']} giải"
                )
        else:
            lines.append("Kết quả trúng giải: trang chi tiết chưa xác minh.")
        for current in report["current_advertised_jackpots"]:
            if current["value_vnd"] is None:
                lines.append(
                    f"{current['name']} ước tính hiện tại: "
                    "nguồn chính thức chưa công bố"
                )
            else:
                lines.append(
                    f"{current['name']} ước tính hiện tại: "
                    f"{current['value_vnd']:,} đồng"
                )
        lines.extend(_format_evaluation(report))
        lines.append(
            "Bộ số gợi ý (ngẫu nhiên, tránh mẫu nhiều người chọn để nếu trúng "
            "ít phải chia Jackpot; KHÔNG tăng xác suất trúng):"
        )
        for item in report["reference_tickets"]:
            ticket = " ".join(f"{number:02d}" for number in item["ticket"])
            lines.append(f"- {ticket}")
        lines.append(report["warning"])
        sections.append("\n".join(lines))
    return "\n\n".join(sections)

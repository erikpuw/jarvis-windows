"""Đánh giá trung thực khả năng "dự đoán" Vietlott.

- Xác suất lý thuyết từng hạng giải (phân phối siêu bội).
- Kiểm định chi-square: các số có ra đều không (máy quay có lệch không).
- Backtest walk-forward: áp chiến lược chọn số lên các kỳ đã qua, chỉ dùng
  dữ liệu trước kỳ đó, rồi so số trùng trung bình với kỳ vọng ngẫu nhiên.

Mọi hàm nhận danh sách Draw đã sắp theo thứ tự kỳ quay tăng dần.
"""
from collections import Counter
from math import comb, erfc, sqrt

from .models import GAME_LIMITS, Draw


STRATEGIES = {
    "hot_30": "6 số ra nhiều nhất 30 kỳ gần nhất",
    "cold_gap": "6 số lâu chưa ra nhất (số gan)",
    "repeat_last": "lặp lại bộ số kỳ trước",
}
HOT_WINDOW = 30


def match_probability(game: str, k: int) -> float:
    """P(vé 6 số trùng đúng k số với 6 số chính được quay)."""
    n = GAME_LIMITS[game]
    return comb(6, k) * comb(n - 6, 6 - k) / comb(n, 6)


def prize_probabilities(game: str) -> dict:
    n = GAME_LIMITS[game]
    total = comb(n, 6)
    rest = n - 6
    if game == "power655":
        # Số đặc biệt quay từ 49 số còn lại; Jackpot 2 = 5 số + số đặc biệt.
        tiers = [
            ("Jackpot 1 (6 số)", 1),
            ("Jackpot 2 (5 số + đặc biệt)", 6),
            ("Giải Nhất (5 số)", 6 * (rest - 1)),
        ]
    else:
        tiers = [
            ("Jackpot (6 số)", 1),
            ("Giải Nhất (5 số)", 6 * rest),
        ]
    tiers += [
        ("Giải Nhì (4 số)", comb(6, 4) * comb(rest, 2)),
        ("Giải Ba (3 số)", comb(6, 3) * comb(rest, 3)),
    ]
    any_prize = sum(ways for _, ways in tiers)
    return {
        "tiers": [
            {
                "name": name,
                "one_in": round(total / ways),
                "percent": ways / total * 100,
            }
            for name, ways in tiers
        ],
        "any_prize_one_in": round(total / any_prize),
        "any_prize_percent": any_prize / total * 100,
    }


def _normal_upper_tail(z: float) -> float:
    return 0.5 * erfc(z / sqrt(2))


def uniformity_test(game: str, draws: list[Draw]) -> dict:
    """Chi-square đồng đều trên tần suất từng số.

    Mỗi kỳ rút 6 số không hoàn lại nên E[chi2] = n - 6 thay vì n - 1;
    thống kê được hiệu chỉnh hệ số (n-1)/(n-6) trước khi so với chi2(n-1).
    p-value dùng xấp xỉ Wilson–Hilferty.
    """
    n = GAME_LIMITS[game]
    if not draws:
        return {"draw_count": 0}
    expected = len(draws) * 6 / n
    frequency = Counter(number for draw in draws for number in draw.numbers)
    raw = sum(
        (frequency[number] - expected) ** 2 / expected
        for number in range(1, n + 1)
    )
    df = n - 1
    chi2 = raw * (n - 1) / (n - 6)
    spread = sqrt(2 / (9 * df))
    z = ((chi2 / df) ** (1 / 3) - (1 - 2 / (9 * df))) / spread
    p_value = _normal_upper_tail(z)
    return {
        "draw_count": len(draws),
        "chi2": round(chi2, 2),
        "df": df,
        "p_value": round(p_value, 4),
        "biased": p_value < 0.01,
        "min_count": min(frequency[x] for x in range(1, n + 1)),
        "max_count": max(frequency[x] for x in range(1, n + 1)),
        "expected_count": round(expected, 1),
    }


def backtest_strategies(
    game: str,
    ordered_draws: list[Draw],
    test_draws: int = 200,
) -> dict:
    """Walk-forward: mỗi kỳ kiểm tra chỉ dùng các kỳ trước nó để chọn số."""
    n = GAME_LIMITS[game]
    test_draws = min(test_draws, len(ordered_draws) - HOT_WINDOW)
    if test_draws <= 0:
        return {"test_draws": 0, "strategies": []}
    start = len(ordered_draws) - test_draws
    last_seen = {}
    for index, draw in enumerate(ordered_draws[:start]):
        for number in draw.numbers:
            last_seen[number] = index
    hits = {name: Counter() for name in STRATEGIES}
    for index in range(start, len(ordered_draws)):
        recent = Counter(
            number
            for draw in ordered_draws[index - HOT_WINDOW:index]
            for number in draw.numbers
        )
        picks = {
            "hot_30": sorted(
                range(1, n + 1), key=lambda x: (-recent[x], x)
            )[:6],
            "cold_gap": sorted(
                range(1, n + 1), key=lambda x: (last_seen.get(x, -1), x)
            )[:6],
            "repeat_last": ordered_draws[index - 1].numbers,
        }
        target = set(ordered_draws[index].numbers)
        for name, pick in picks.items():
            hits[name][len(target & set(pick))] += 1
        for number in ordered_draws[index].numbers:
            last_seen[number] = index

    expected = 36 / n
    sd = sqrt(
        sum((k - expected) ** 2 * match_probability(game, k) for k in range(7))
    )
    prize_expected = sum(match_probability(game, k) for k in range(3, 7))
    results = []
    for name, counter in hits.items():
        mean = sum(k * v for k, v in counter.items()) / test_draws
        prize_rate = sum(v for k, v in counter.items() if k >= 3) / test_draws
        results.append(
            {
                "strategy": name,
                "description": STRATEGIES[name],
                "mean_matches": round(mean, 3),
                "prize_hit_percent": round(prize_rate * 100, 2),
                "z_score": round(
                    (mean - expected) / (sd / sqrt(test_draws)), 2
                ),
            }
        )
    # Ngưỡng 2.5 thay vì 2.0 vì đang thử nhiều chiến lược cùng lúc.
    beats_chance = [r["strategy"] for r in results if r["z_score"] >= 2.5]
    return {
        "test_draws": test_draws,
        "expected_mean_matches": round(expected, 3),
        "expected_prize_hit_percent": round(prize_expected * 100, 2),
        "strategies": results,
        "beats_chance": beats_chance,
    }

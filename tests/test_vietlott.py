"""Tests for engine.tools.vietlott_engine analysis/evaluation. Run: python tests/test_vietlott.py"""
import random
import sys
from math import comb
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.tools.vietlott_engine.analysis import (
    build_reference_tickets,
    build_report,
    format_report_text,
    popularity_flags,
)
from engine.tools.vietlott_engine.evaluation import (
    backtest_strategies,
    match_probability,
    prize_probabilities,
    uniformity_test,
)
from engine.tools.vietlott_engine.models import Draw


def _draw(index, numbers, game="mega645"):
    return Draw(game, str(index), "01/01/2020", tuple(sorted(numbers)), "", "")


def _cyclic_draws(count, n=45):
    # Mỗi số xuất hiện đúng đều nhau khi count là bội của 15 (với n=45).
    return [
        _draw(i + 1, [(6 * i + j) % n + 1 for j in range(6)])
        for i in range(count)
    ]


def test_prize_probabilities_match_hypergeometric():
    for game, n in (("mega645", 45), ("power655", 55)):
        prizes = prize_probabilities(game)
        assert prizes["tiers"][0]["one_in"] == comb(n, 6)
        expected = sum(match_probability(game, k) for k in range(3, 7)) * 100
        assert abs(prizes["any_prize_percent"] - expected) < 1e-9
    assert prize_probabilities("mega645")["any_prize_one_in"] == 42


def test_popularity_flags():
    assert "dãy số liên tiếp" in popularity_flags((1, 2, 3, 10, 20, 30))
    assert "nhiều số ngày sinh (≤31)" in popularity_flags((1, 2, 3, 10, 20, 30))
    assert "cấp số cộng" in popularity_flags((5, 10, 15, 20, 25, 30))
    assert popularity_flags((5, 12, 23, 34, 41, 45)) == []


def test_reference_tickets_are_valid_and_unflagged():
    draws = _cyclic_draws(60)
    tickets = build_reference_tickets(
        "mega645", draws, count=5, rng=random.Random(7)
    )
    assert len(tickets) == 5
    seen = {tuple(t["ticket"]) for t in tickets}
    assert len(seen) == 5
    for ticket in seen:
        assert len(set(ticket)) == 6 and all(1 <= x <= 45 for x in ticket)
        assert popularity_flags(ticket) == []


def test_uniformity_detects_bias():
    assert uniformity_test("mega645", _cyclic_draws(450))["biased"] is False
    rigged = [_draw(i + 1, [1, 2, 3, 4, 5, 6]) for i in range(100)]
    assert uniformity_test("mega645", rigged)["biased"] is True


def test_backtest_detects_real_signal_and_rejects_none():
    # Máy quay "hỏng" lặp lại cùng bộ số -> chiến lược lặp kỳ trước phải thắng.
    rigged = [_draw(i + 1, [7, 14, 21, 28, 35, 42]) for i in range(100)]
    result = backtest_strategies("mega645", rigged, test_draws=50)
    assert "repeat_last" in result["beats_chance"]

    rng = random.Random(1)
    fair = [_draw(i + 1, rng.sample(range(1, 46), 6)) for i in range(1500)]
    result = backtest_strategies("mega645", fair, test_draws=1000)
    assert result["beats_chance"] == []
    for item in result["strategies"]:
        assert abs(item["mean_matches"] - 0.8) < 0.1


def test_report_text_has_no_fake_percent():
    report = build_report("mega645", _cyclic_draws(90))
    text = format_report_text([report])
    assert "điểm thống kê" not in text
    assert "1/8,145,060" in text
    assert "KHÔNG tăng xác suất trúng" in text


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(tests)} passed")

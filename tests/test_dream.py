"""Smoke test for engine.core.dream pure helpers. Run: python tests/test_dream.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.core.dream import (
    _split_message_chunks, _split_log_entries, _is_junk_bullet, _remove_day_link,
    extract_day_summary_from_month,
)


def test_split_message_chunks_groups_by_gap():
    messages = [
        {"id": 1, "created_at": 1000.0},
        {"id": 2, "created_at": 1030.0},   # 30s later, same chunk
        {"id": 3, "created_at": 5000.0},   # >30min later, new chunk
        {"id": 4, "created_at": 5010.0},
    ]
    chunks = _split_message_chunks(messages, gap_seconds=1800)
    assert len(chunks) == 2, chunks
    assert [m["id"] for m in chunks[0]] == [1, 2]
    assert [m["id"] for m in chunks[1]] == [3, 4]


def test_split_log_entries_preserves_preamble_and_parses_dates():
    content = (
        "# Errors\n\nSome header text.\n\n---\n"
        "\n## [ERR-20260101-101010] Old bug\n- Time: x\n"
        "\n## [ERR-20260901-101010] Recent bug\n- Time: y\n"
    )
    preamble, entries = _split_log_entries(content)
    assert "Some header text" in preamble
    assert len(entries) == 2
    assert entries[0][0].isoformat() == "2026-01-01"
    assert entries[1][0].isoformat() == "2026-09-01"
    assert "Old bug" in entries[0][1]
    assert "Recent bug" in entries[1][1]


def test_split_log_entries_keeps_unparseable_headings():
    content = "# Log\n\n## Not A Date Heading\ncontent here\n"
    preamble, entries = _split_log_entries(content)
    assert len(entries) == 1
    assert entries[0][0] is None
    assert "content here" in entries[0][1]


def test_is_junk_bullet_catches_offers_and_questions():
    assert _is_junk_bullet("Ngài có cần tôi cung cấp thêm thông tin gì không ạ? Thưa ngài.")
    assert _is_junk_bullet("Bạn cần gì thêm không?")
    assert not _is_junk_bullet("Đã tổng hợp giá Vàng SJC, Xăng dầu và Tỷ giá USD.")


def test_remove_day_link_drops_only_the_matching_day():
    content = (
        "## Các ngày\n"
        "- [[daily/07-2026/2026-07-23|2026-07-23]]\n"
        "- [[daily/07-2026/2026-07-24|2026-07-24]]\n"
        "\n## Tóm tắt Dream (bản gốc đã lưu trữ)\n"
    )
    updated = _remove_day_link(content, "2026-07-23")
    assert "2026-07-23" not in updated
    assert "2026-07-24" in updated
    assert "## Tóm tắt Dream" in updated


def test_remove_day_link_is_noop_when_day_not_present():
    content = "## Các ngày\n- [[daily/07-2026/2026-07-24|2026-07-24]]\n"
    assert _remove_day_link(content, "2026-07-23").strip() == content.strip()


_MONTH_FILE = (
    "# Hội thoại tháng 07-2026\n\n"
    "## Các ngày\n"
    "- [[daily/07-2026/2026-07-24|2026-07-24]]\n\n"
    "## Tóm tắt Dream (bản gốc đã lưu trữ)\n"
    "### 2026-07-23\n"
    "- Đã tổng hợp giá Vàng SJC.\n"
    "### 2026-07-24\n"
    "- Đã kiểm tra hộp thư.\n"
)


def test_extract_day_summary_from_month_finds_the_right_day():
    assert extract_day_summary_from_month(_MONTH_FILE, "2026-07-23") == "- Đã tổng hợp giá Vàng SJC."
    assert extract_day_summary_from_month(_MONTH_FILE, "2026-07-24") == "- Đã kiểm tra hộp thư."


def test_extract_day_summary_from_month_missing_day_or_section():
    assert extract_day_summary_from_month(_MONTH_FILE, "2026-07-25") == ""
    assert extract_day_summary_from_month("# no dream section here", "2026-07-23") == ""


if __name__ == "__main__":
    test_split_message_chunks_groups_by_gap()
    test_split_log_entries_preserves_preamble_and_parses_dates()
    test_split_log_entries_keeps_unparseable_headings()
    test_is_junk_bullet_catches_offers_and_questions()
    test_remove_day_link_drops_only_the_matching_day()
    test_remove_day_link_is_noop_when_day_not_present()
    test_extract_day_summary_from_month_finds_the_right_day()
    test_extract_day_summary_from_month_missing_day_or_section()
    print("OK: all dream smoke tests passed")

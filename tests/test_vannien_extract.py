"""extract_vannien_info đọc trang lịch vạn niên BaoMoi (mẫu thật 2026-10-03, tests/fixtures).
Lỗi thật trên máy: "Giờ hoàng đạo: Tiện ích" (khớp nhầm tiêu đề trang), thiếu can chi nên không rõ đây là lịch âm."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.tools.search_engine import extract_vannien_info

TEXT = (Path(__file__).parent / "fixtures" / "baomoi_lich_van_nien_2026-10-03.txt").read_text(encoding="utf-8")


def test_lunar_date_comes_with_can_chi_of_day_month_year():
    out = extract_vannien_info(TEXT)
    assert "Âm lịch: ngày 23 tháng 8 năm 2026 (ngày Canh Tuất, tháng Đinh Dậu, năm Bính Ngọ)" in out, out
    assert "Dương lịch: Thứ bảy, Ngày 3 Tháng 10 Năm 2026" in out


def test_auspicious_hours_are_the_real_list_not_the_page_title_neighbour():
    out = extract_vannien_info(TEXT)
    assert "Giờ hoàng đạo: Mậu Dần (3h-5h), Canh Thìn (7h-9h), Tân Tỵ (9h-11h)" in out, out
    assert "Tiện ích" not in out


def test_other_day_facts_are_still_read():
    out = extract_vannien_info(TEXT)
    assert "Mệnh ngày: Kim - Thoa xuyến kim (Vàng trang sức)" in out
    assert "Tuổi xung khắc: Giáp Thìn, Mậu Thìn, Giáp Tuất" in out
    assert "Hỷ thần: Tây Bắc, Tài thần: Tây Nam, Kê thần: Đông Bắc" in out
    assert "Tiết khí: Thu phân (Giữa thu) - Hàn lộ" in out
    assert "Trực Trừ: Tốt cho các việc trừ phục" in out
    assert "Loại ngày: Bình thường" in out


def test_solar_date_is_never_labelled_as_lunar():
    out = extract_vannien_info("Thứ bảy, Ngày 3 Tháng 10 Năm 2026\nGiờ hoàng đạo\nMậu Dần (3h-5h)")
    assert "Âm lịch" not in out and "Dương lịch: Thứ bảy, Ngày 3 Tháng 10 Năm 2026" in out


def test_empty_page_still_says_updating():
    assert "Đang cập nhật" in extract_vannien_info("")

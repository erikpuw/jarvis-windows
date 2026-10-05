"""Eval định tuyến thật: bộ phân loại (classifier) chọn agent trên danh mục thật (skills/agents + prompt/agents.md).
Mỗi câu tra cứu có tập tool mong đợi; agent tra cứu = đúng 1 tool (AGENT_REGISTRY[...]["tool"]).
Cần llama.cpp ở 127.0.0.1:8080. Chạy: python tests/live/agent_routing_eval.py
Đo 2026-10-03 trước khi tách: 1 agent search + chọn tool = 48/50; tách mỗi tool một agent = 50/50 (12/12 agent khác).
Bộ câu KHÔNG được trùng/na ná câu nào trong prompt/agents.md (tiêu chí chỉ nêu khái niệm); câu thêm mới nên là câu chưa từng
dùng để chỉnh tiêu chí, để không đo trên chính dữ liệu đã chỉnh."""
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

P, N, M, W = "search_products", "search_news", "get_market_data", "weather_search"
HIST_PRODUCT = [{"role": "user", "content": "so sánh iphone 16 và galaxy s25"},
                {"role": "assistant", "content": "Dạ, đây là giá và đánh giá của hai máy ạ."}]
HIST_WEATHER = [{"role": "user", "content": "thời tiết Hà Nội hôm nay"},
                {"role": "assistant", "content": "Dạ, Hà Nội hôm nay 28 độ, có mưa rào ạ."}]
HIST_NEWS = [{"role": "user", "content": "tin tức bão số 5"},
             {"role": "assistant", "content": "Dạ, bão số 5 đang vào Biển Đông, có ba bài báo mới ạ."}]
CASES = [
    # --- sản phẩm: đánh giá / so sánh / mua / giá hàng hóa
    ("đánh giá máy giặt Panasonic Inverter 11.5 kg NA-FJ115X1BV", {P}),
    ("so sánh máy giặt LG FX1411N5W và Electrolux EWF1143P5SC", {P}),
    ("so sánh LG FX1411N5W và Electrolux EWF1143P5SC", {P}),
    ("so sánh iphone 16 và galaxy s25", {P}),
    ("Panasonic NA-FJ115X1BV có tốt không", {P}),
    ("đánh giá Galaxy S25", {P}),
    ("giá thịt bò hôm nay", {P}),
    ("giá bột giặt omo", {P}),
    ("top 5 máy giặt dưới 10 triệu", {P}),
    ("mua sữa tươi vinamilk", {P}),
    ("tôi muốn mua tai nghe sony chống ồn", {P}),
    ("nên mua laptop nào cho sinh viên dưới 20 triệu", {P}),
    ("giá kimchi ở bách hóa xanh", {P}),
    ("tủ lạnh nào tiết kiệm điện nhất", {P}),
    ("giá iphone 17 pro max", {P}),
    ("giá RAM DDR5 32GB", {P}),
    ("nồi chiên không dầu loại nào bán chạy", {P}),
    ("điều hòa inverter 1.5 ngựa loại nào êm", {P}),
    # --- tin tức
    ("tin tức iphone 17", {N}),
    ("tin tức máy giặt Panasonic có gì mới", {N}),
    ("tin tức về RAM DDR5", {N}),
    ("có tin gì về bão số 5", {N}),
    ("tìm tin tức nvidia rtx spark", {N}),
    ("hôm nay có sự kiện gì nổi bật", {N}),
    ("bản tin thời sự sáng nay", {N}),
    ("đọc báo giúp tôi về kinh tế", {N}),
    ("tin tức về biến động giá xăng", {N}),
    # --- thị trường cố định
    ("giá xăng hôm nay", {M}),
    ("giá vàng sjc", {M}),
    ("tỷ giá usd vietcombank", {M}),
    ("giá dầu diesel", {M}),
    ("giá gas tháng này", {M}),
    # --- tool khác
    ("ngày mai Hà Nội có mưa không", {W}),
    ("nhiệt độ ở Đà Nẵng bây giờ", {W}),
    ("dự báo thời tiết cuối tuần", {W}),
    ("chỉ đường từ nhà đến sân bay Tân Sơn Nhất", {"map_route"}),
    ("quán cà phê gần đây", {"map_pois"}),
    ("quán ăn ngon ở quận 1", {"map_pois"}),
    ("phim nào đang chiếu", {"get_cgv_movies"}),
    ("lịch chiếu phim cuối tuần", {"get_cgv_movies"}),
    ("tuần này epic tặng game gì", {"get_epic_free_games"}),
    ("tử vi cung sư tử hôm nay", {"get_zodiac_data"}),
    ("hôm nay âm lịch ngày bao nhiêu", {"get_vannien_data"}),
    ("xã Tân Phú thuộc huyện nào", {"vietnam_data_lookup"}),
    ("thời tiết và tin tức hôm nay", {W, N}),
    # --- câu nối tiếp: chỉ đúng khi nhìn được lượt trước (từ khóa không có lịch sử nên đoán mò)
    ("còn pin thì sao", {P}, HIST_PRODUCT),
    ("loại nào rẻ hơn", {P}, HIST_PRODUCT),
    ("còn ngày mai thì sao", {W}, HIST_WEATHER),
    ("thế còn Đà Nẵng", {W}, HIST_WEATHER),
    ("kể thêm về vụ đó", {N}, HIST_NEWS),
]

OTHER = [  # (câu, agent mong đợi)
    ("mở notepad giúp tôi", "desktop"),
    ("đóng chrome đi", "desktop"),
    ("kiểm tra email mới", "email"),
    ("tôi có cuộc hẹn nào tuần này không", "email"),
    ("ghi chú lại là mai họp lúc 9 giờ", "notes"),
    ("mở bài hát buồn của sơn tùng", "media"),
    ("chụp màn hình xem đang có gì", "vision"),
    ("kiểm tra an ninh mạng máy này", "security"),
    ("quét lỗi dự án", "project"),
    ("tra luật giao thông về nồng độ cồn", "legal"),
    ("kết quả mega 6/45 kỳ gần nhất", "vietlott"),
    ("xem lại lịch sử trò chuyện hôm qua", "history"),
]


# Bộ chưa từng dùng để chỉnh tiêu chí agents.md (viết sau khi chốt tiêu chí): đo độ tổng quát, không phải độ khớp.
HELD_OUT = [
    ("tư vấn giúp tôi chọn robot hút bụi dưới 8 triệu", {"search_products"}),
    ("máy ảnh canon r50 giá bao nhiêu", {"search_products"}),
    ("gạo st25 loại nào ngon", {"search_products"}),
    ("so sánh chuột logitech mx master 3s và razer", {"search_products"}),
    ("bàn phím cơ nào gõ êm", {"search_products"}),
    ("giá cá hồi tươi", {"search_products"}),
    ("mua nước giặt ở đâu rẻ", {"search_products"}),
    ("iphone 15 cũ giá thế nào", {"search_products"}),
    ("hôm nay vàng 9999 bao nhiêu", {"get_market_data"}),
    ("xăng ron 95 tăng chưa", {"get_market_data"}),
    ("tỷ giá euro", {"get_market_data"}),
    ("giá điện sinh hoạt hiện nay", {"get_market_data"}),
    ("có gì mới về kinh tế tuần này", {"search_news"}),
    ("tin nóng hôm nay", {"search_news"}),
    ("người ta đang bàn tán chuyện gì trên báo", {"search_news"}),
    ("tin về giá nhà đất tăng", {"search_news"}),
    ("chiều nay Sài Gòn có mưa to không", {"weather_search"}),
    ("Huế mấy độ", {"weather_search"}),
    ("tuần sau đi Đà Lạt trời thế nào", {"weather_search"}),
    ("từ Bến Thành đến Landmark 81 đi đường nào", {"map_route"}),
    ("tìm nhà thuốc quanh đây", {"map_pois"}),
    ("chỗ nào bán phở gần chỗ tôi", {"map_pois"}),
    ("cuối tuần có phim gì hay ở CGV", {"get_cgv_movies"}),
    ("game nào đang free trên epic", {"get_epic_free_games"}),
    ("mai là mùng mấy âm", {"get_vannien_data"}),
    ("cung song ngư hôm nay có may mắn không", {"get_zodiac_data"}),
    ("phường Bến Nghé thuộc quận mấy", {"vietnam_data_lookup"}),
    ("mã hành chính tỉnh Lâm Đồng", {"vietnam_data_lookup"}),
]
HELD_OTHER = [
    ("tắt zalo giúp tôi", "desktop"),
    ("đọc thư vừa đến", "email"),
    ("lưu ý tưởng này vào ghi chú", "notes"),
    ("bật nhạc piano thư giãn", "media"),
    ("quét cổng mạng", "security"),
    ("luật đất đai quy định gì về sổ đỏ", "legal"),
]


async def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    os.environ.setdefault("LOCAL_URL", "http://127.0.0.1:8080/v1")
    logging.basicConfig(level=logging.ERROR)
    from engine.orchestrator.classifier import classify_tasks
    from engine.orchestrator.registry import AGENT_REGISTRY

    tool_of = {name: {e["tool"]} for name, e in AGENT_REGISTRY.items() if "tool" in e}
    for label, search_cases, other_cases in (("bộ chính", CASES, OTHER), ("bộ mới, chưa dùng để chỉnh", HELD_OUT, HELD_OTHER)):
        ok_search = ok_other = 0
        ms = []
        for text, expected, *rest in search_cases:
            t0 = time.perf_counter()
            agents = [t["agent"] for t in await classify_tasks(text, rest[0] if rest else [])]
            ms.append((time.perf_counter() - t0) * 1000)
            got = set().union(*(tool_of.get(a, set()) for a in agents)) if agents else set()
            if got == expected:
                ok_search += 1
            else:
                print(f"SAI  {text[:52]:<52} mong đợi {sorted(expected)} nhận {agents}")
        for text, expected in other_cases:
            agents = [t["agent"] for t in await classify_tasks(text, [])]
            if agents == [expected]:
                ok_other += 1
            else:
                print(f"SAI  {text[:52]:<52} mong đợi {expected} nhận {agents}")
        print(f"[{label}] Tra cứu: {ok_search}/{len(search_cases)}   Agent khác: {ok_other}/{len(other_cases)}   "
              f"{sum(ms) / len(ms):.0f} ms/câu (1 lần gọi LLM)\n")


if __name__ == "__main__":
    asyncio.run(main())

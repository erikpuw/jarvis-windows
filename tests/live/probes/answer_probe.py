"""Live probe vòng trả lời (2026-10-17): chào/trò chuyện không liệt kê khả năng hay mời việc; báo kết quả tool đúng
số liệu, không chép tiêu đề kết quả, không mời thêm việc khác; "làm được gì" vẫn liệt kê. Chạy handle_turn thật
(vòng chọn tool + vòng trả lời với model thật); kết quả tool là chữ dựng sẵn, không gọi mạng, không ghi DB.
Chấm bằng code. Run: PYTHONIOENCODING=utf-8 python tests/live/probes/answer_probe.py
"""
import asyncio, re, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "live"))
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")

# mời ngài giao thêm việc (câu hỏi/lời rủ); "cứ gọi tôi là JARVIS", "hay là nó bị ẩn" không phải lời mời
INVITE = re.compile(r"muốn (tôi|mình)|cần (tôi|mình) .{0,40}không|có cần|tôi có thể giúp|ngài cần (tôi|gì)"
                    r"|cứ (gọi|bảo|hỏi|hú) (tôi )?(bất cứ|khi|lúc|liền)|thử hỏi", re.I)
HEADER = re.compile(r"\[kết quả|ket_qua", re.I)
# ngài 2026-10-20: câu trả lời sau tool mở đầu bằng nói lại câu báo / câu hỏi của ngài / chuyện nhận kết quả
ECHO = re.compile(r"\s*(\[[^\]]*\]\s*)?(ngài (muốn|hỏi|cần|đang hỏi)[^.!?\n]{0,90}(hả|à|sao|đúng không|phải không)"
                  r"|được (thôi|rồi)[,! ]+ngài|(tôi )?đã nhận được kết quả)", re.I)


def _num(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def made_up_numbers(answer: str, text: str) -> list[str]:
    """Số trong câu trả lời không có trong kết quả và cũng không phải hiệu/tổng của hai số trong kết quả."""
    pat = r"\d+(?:[.,]\d+)*"
    have = set(re.findall(pat, text))
    vals = [_num(x) for x in have]
    derived = {abs(a - b) for a in vals for b in vals} | {a + b for a in vals for b in vals}
    return sorted(x for x in set(re.findall(pat, answer)) - have if _num(x) not in derived)
RESULTS = {  # tool → (outcome, text)
    # đúng định dạng weather_engine thật: Báo Mới (_format_baomoi), wttr (_current_weather), theo giờ (_format_hourly)
    "weather": ("success", "📍 Thời tiết tại TP. Hồ Chí Minh (lúc 14:00):\n  🌡  Nhiệt độ: 31°C (hôm nay 25–33°C).\n"
                           "  ☁️  Mưa rào.\n  💧 Độ ẩm: 75%.\n  🌬  Gió: 12 km/h.\n  🌧  Khả năng mưa: 60%."),
    "system_status": ("success", "CPU 15%, RAM 61% (9.8/16 GB), ổ C còn trống 120 GB, nhiệt độ CPU 58°C."),
    "market_price": ("success", "Giá xăng RON 95-III: 23.450 đồng/lít; E5 RON 92: 22.180 đồng/lít (áp dụng từ 15/10)."),
    "search_news": ("success", "1. Ngân hàng Nhà nước giữ nguyên lãi suất điều hành.\n2. Giá vàng SJC tăng 300.000 đồng/lượng."),
    "open_app": ("failed", "Lỗi: không tìm thấy ứng dụng Spotify trên máy."),
}
WTTR = "📍 Thời tiết tại Hà Nội: có thể có mưa rải rác, nhiệt độ 27°C."
HOURLY = ("🌧 Khả năng mưa theo giờ tại Đà Nẵng (6 giờ tới):\n  15:00 — 20%\n  16:00 — 35%\n  17:00 — 55% (0.4 mm)\n"
          "  18:00 — 70% (1.2 mm)\n  19:00 — 45%\n  20:00 — 10%")
TOMORROW = ("📅 Dự báo ngày mai (18/10/2026) tại Hà Nội:\n  ☁️  Mưa giông.\n  🌡  Nhiệt độ: 22–29°C.\n"
            "  🌧  Khả năng mưa ban ngày: 65%.\n  🌙  Khả năng mưa ban đêm: 15%.")
NEWS = ("🔍 **Kết quả tìm kiếm:** tin tức lãi suất 2026\n\n"
        "📰 **Ngân hàng Nhà nước giữ nguyên lãi suất điều hành**\n🏷️ Nguồn: VnExpress\n🔗 https://vnexpress.net/lai-suat-1.html\n"
        "📝 Sapo: Ngân hàng Nhà nước quyết định giữ lãi suất tái cấp vốn ở mức 4,5% trong tháng 10 để hỗ trợ tăng trưởng.\n"
        "📄 Theo thông báo chiều 17/10, lãi suất tái chiết khấu giữ ở 3%. Lãnh đạo ngân hàng cho biết lạm phát 9 tháng ở mức 3,2%.\n\n"
        "📰 **Lãi suất điều hành không đổi, ngân hàng thương mại giữ lãi huy động**\n🏷️ Nguồn: Tuổi Trẻ\n🔗 https://tuoitre.vn/lai-suat-2.html\n"
        "📝 Sapo: Sau quyết định của Ngân hàng Nhà nước, Vietcombank và BIDV giữ lãi suất tiết kiệm 12 tháng ở 4,7%.\n"
        "📄 Một số ngân hàng nhỏ vẫn trả tới 5,6% cho kỳ hạn 12 tháng.\n\n"
        "📰 **Giá vàng SJC tăng 300.000 đồng mỗi lượng**\n🏷️ Nguồn: Thanh Niên\n🔗 https://thanhnien.vn/vang-3.html\n"
        "📝 Sapo: Sáng 18/10, giá vàng miếng SJC tăng 300.000 đồng, lên 92,5 triệu đồng mỗi lượng bán ra.\n"
        "📄 Vàng nhẫn cũng tăng 200.000 đồng theo giá thế giới.")
# bảng xăng dầu thật đã hiện cho ngài (log 2026-10-19): câu trả lời không chép lại giá, không bịa "thay đổi so với lần tra trước"
FUEL = ("📊 **KẾT QUẢ TRA CỨU: XĂNG DẦU**\n\n#### ⛽ Giá Xăng Dầu (Petrolimex)\n\n| Sản phẩm | Vùng 1 | Vùng 2 |\n"
        "| :---: | :---: | :---: |\n| Dầu hỏa 2-K | 30.410 VNĐ. | 31.010 VNĐ. |\n| DO 0,001S Mức 5 | 30.200 VNĐ. | 30.800 VNĐ. |\n"
        "| DO 0,05S Mức 2 | 28.800 VNĐ. | 29.370 VNĐ. |\n| Xăng E10 RON 95 Mức 3 | 26.720 VNĐ. | 27.250 VNĐ. |\n"
        "| Xăng E10 RON 95 Mức 5 | 27.520 VNĐ. | 28.070 VNĐ. |\n| Xăng E5 RON 92 | 26.670 VNĐ. | 27.200 VNĐ. |\n"
        "| Xăng E5 RON 92 Mức 2 | 27.700 VNĐ. | 28.250 VNĐ. |\n\nNguồn thông tin: Xăng dầu")
NO_TOMORROW ="Chưa có dự báo ngày mai cho vũng tàu: nguồn dự báo theo ngày lúc này không có dữ liệu."
NOTE_OK = "Đã ghi chú vào Ghi_chu/2026-10-18-ghi-chu.md."
# (câu, loại[, kết quả tool thay cho RESULTS]): chat = không được mời/liệt kê; list = phải liệt kê khả năng; tool = báo kết quả của tool đó
CASES = [
    ("Xin chào", "chat"), ("Jarvis ổn không", "chat"), ("cảm ơn nha", "chat"),
    ("hôm nay tôi mệt quá", "chat"), ("chúc ngủ ngon", "chat"), ("bạn tên gì", "chat"),
    ("bạn làm được những gì", "list"),
    ("thời tiết Sài Gòn hôm nay", "weather"),
    ("chiều nay Hà Nội có mưa không", "weather", WTTR), ("Hà Nội mấy giờ mưa", "weather", WTTR),
    ("ngày mai Hà Nội thế nào", "weather", TOMORROW), ("ngày mai Vũng Tàu thế nào", "weather", NO_TOMORROW),
    ("mấy giờ Đà Nẵng mưa", "weather", HOURLY),
    ("kiểm tra tình trạng máy", "system_status"),
    ("giá xăng hôm nay", "market_price"), ("xem giá xăng dầu hôm nay", "market_price", FUEL), ("tin tức mới nhất", "search_news"), ("mở Spotify", "open_app"),
    ("tin tức lãi suất hôm nay", "search_news", NEWS), ("báo nói gì về lãi suất ngân hàng", "search_news", NEWS),
    # save_note (2026-10-18): chỉ khi ngài bảo ghi; "ghi nhớ…" về bản thân ngài là việc của learning, không phải ghi chú
    ("ghi chú giúp tôi: hạn thanh toán nợ thẻ là ngày 25/10", "save_note", NOTE_OK),
    ("lưu cái tin vừa tra vào ghi chú", "save_note", NOTE_OK),
    ("ghi nhớ là tôi thích uống cà phê đen", "chat"),
    # vn_admin_lookup chạy thật (chỉ đọc data/vietnam_data, không mạng); log 2026-10-17 21:21-21:26
    ("Phường Phú Định là ở đâu", "vn_admin_lookup"), ("Ở Đà Nẵng có bao nhiêu phường?", "vn_admin_lookup"),
    ("Có liệt kê được phường ở Đà Nẵng không", "vn_admin_lookup"),
]
LIVE = {"vn_admin_lookup"}


def grade(kind, answer, ran, labels, result=None, question=""):
    reasons = []
    named = [lb for lb in labels if lb.lower() in answer.lower()]
    if HEADER.search(answer):
        reasons.append("chép tiêu đề [kết quả")
    if kind == "list":
        if len(named) < 3:
            reasons.append(f"liệt kê thiếu ({len(named)} khả năng)")
        return reasons
    if kind == "chat":
        if ran:
            reasons.append(f"gọi tool {ran[0][0]}")
        if len(named) >= 2:
            reasons.append(f"liệt kê khả năng {named[:3]}")
        if INVITE.search(answer):
            reasons.append(f"mời: {INVITE.search(answer).group(0)!r}")
        return reasons
    if not ran or ran[0][0] != kind:
        return [f"tool {ran[0][0] if ran else None} ≠ {kind}"]
    if kind in LIVE:
        outcome, text = ran[0][2]
    else:
        outcome, text = RESULTS[kind] if result is None else ("success", result)
    rest = answer.split("\n\n", 1)[-1]                      # bỏ đoạn đầu: câu báo 🛠️ của vòng chọn tool
    rest = rest.split(text.strip())[-1] if text.strip() and text.strip() in rest else rest  # bỏ bảng đã hiện
    if ECHO.match(rest):
        reasons.append(f"mở đầu nói lại: {rest.strip()[:60]!r}")
    nums = made_up_numbers(answer, text)
    if nums:
        reasons.append(f"số không có trong kết quả {nums[:4]}")
    if outcome == "success" and re.findall(r"\d+", text) and not re.findall(r"\d+", answer):
        reasons.append("không nêu số liệu nào")
    if kind == "save_note":
        args = ran[0][1]
        if "vừa tra" in question and args.get("from_last_result") is not True:
            reasons.append(f"không đặt from_last_result: {args}")
        if "25/10" in question and "25/10" not in str(args.get("content", "")):
            reasons.append(f"content thiếu nội dung ngài đọc: {args}")
    if kind == "search_news" and "📝 Sapo" in text:  # bản tin tổng hợp (ngài 2026-10-18): đoạn văn + đủ nguồn
        missing = [u for u in re.findall(r"🔗 (\S+)", text) if u not in answer]
        if missing:
            reasons.append(f"thiếu link {missing}")
        paras = [p for p in re.split(r"\n\s*\n", answer) if len(p) >= 120 and not re.match(r"\s*([-*•]|\d+\.)\s", p)]
        if len(paras) < 2:
            reasons.append(f"không thành bản tin ({len(paras)} đoạn văn)")
        # bố cục (ngài 2026-10-19): mỗi sự việc một tiêu đề in đậm riêng dòng; NEWS có 2 sự việc (lãi suất, vàng)
        heads = re.findall(r"^\s*(?:#{2,4}\s*)?\*\*[^*\n]{4,90}\*\*\s*$", answer, re.M)
        if len(heads) < 2:
            reasons.append(f"không có bố cục ({len(heads)} tiêu đề mục)")
        src = next((ln for ln in answer.splitlines() if "Nguồn" in ln), "")
        if src.count("](") < 2 or " · " not in src:
            reasons.append(f"nguồn không gọn một dòng: {src[:80]!r}")
    if kind == "market_price" and "|" in text:  # bảng đã hiện (da_hien): nhận xét, không chép lại bảng
        prices = set(re.findall(r"\d{1,3}(?:\.\d{3})+", text))
        said = answer.split(text.strip())[-1]  # câu trả lời của handle_turn gồm cả bảng đã hiện: chấm phần model viết sau bảng
        echoed = prices & set(re.findall(r"\d{1,3}(?:\.\d{3})+", said))
        if len(echoed) > 3:
            reasons.append(f"chép lại bảng ({len(echoed)}/{len(prices)} giá)")
        if re.search(r"thay đổi so với|so với lần tra|biến động", said, re.I):
            reasons.append("bịa thay đổi so với lần trước")
    if outcome == "failed" and not re.search(r"không|chưa", answer, re.I):
        reasons.append("không nói lỗi")
    if INVITE.search(answer):
        reasons.append(f"mời: {INVITE.search(answer).group(0)!r}")
    return reasons


async def run_case(text, result=None):
    from engine.tools import registry as R
    from engine.turn.context import TurnContext
    from engine.turn.entry import handle_turn
    from engine.turn import entry, outcome
    from e2e_turn import WS
    entry._find_workflow = lambda text: None
    outcome.save_turn = lambda *a, **k: None
    ran, real_run = [], R.run

    async def run(name, a, ctx=None):
        if name in LIVE:
            res = await real_run(name, a, ctx)
            ran.append((name, a, (res.outcome, res.text)))
            return res
        ran.append((name, a))
        oc, txt = ("success", result) if result is not None else RESULTS.get(name, ("failed", f"Lỗi: {name} không có trong probe"))
        return R.ToolResult(txt, oc)
    R.run = run

    async def send(_ws, data):
        return True
    t0 = time.time()
    try:
        answer = await handle_turn(text, TurnContext(ws=WS(), send_json=send, conversation_history=[]))
    finally:
        R.run = real_run
    return answer or "", ran, time.time() - t0


async def main():
    from engine.tools import registry
    labels = [registry.label(n) for n in registry.chat_names(None)]
    ok = 0
    only = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--only=")), None)  # vd --only=search_news
    cases = [c for c in CASES if only is None or c[1] == only]
    for text, kind, *result in cases:
        result = result[0] if result else None
        answer, ran, sec = await run_case(text, result)
        reasons = grade(kind, answer, ran, labels, result, text)
        ok += not reasons
        print(f"{'PASS' if not reasons else 'FAIL'} [{kind}] {text!r} ({sec:.1f}s) {reasons}")
        print("     →", answer.replace("\n", " ⏎ ")[:260 if "-v" not in sys.argv else None])
    print(f"{ok}/{len(cases)} PASS")


asyncio.run(main())

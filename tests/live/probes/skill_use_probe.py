"""Live probe dùng skill (2026-10-20), embedder + model thật, tool giả (không mạng, không DB):
(1) khớp: câu cùng ý khớp skill bao-cao-sang, câu khác ý không khớp; (2) chạy: handle_turn với câu khớp chạy đủ
weather → market_price → search_news đúng thứ tự, tham số hợp lệ, có câu trả lời. Skill ghi vào thư mục tạm.
Run: PYTHONIOENCODING=utf-8 python tests/live/probes/skill_use_probe.py"""
import asyncio, re, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "live"))
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")

SKILL = """---
name: bao-cao-sang
description: Báo cáo buổi sáng gồm thời tiết, giá vàng, tin thời sự. Dùng khi ngài chào buổi sáng hoặc hỏi hôm nay có gì.
category: learned
enabled: true
---

Câu mẫu: Báo cáo buổi sáng cho tôi đi.; Buổi sáng này có gì mới, báo cáo giúp tôi.; Cho tôi xem báo cáo buổi sáng gồm thời tiết TP.HCM, giá vàng và tin thời sự.

1. weather — thời tiết TP.HCM | kiểm chứng: có trạng thái trời và nhiệt độ
2. market_price — giá vàng hôm nay | kiểm chứng: có giá mua và giá bán
3. search_news — tin thời sự | kiểm chứng: có ít nhất 1 tin kèm nguồn

Tổng hợp: có đủ thời tiết, giá vàng và tin tức
"""
SAME = ["báo cáo sáng nay đi", "cho tôi bản tin buổi sáng", "tóm tắt tình hình sáng nay giúp tôi"]  # "sáng nay có gì mới không": mơ hồ với tin tức, đi đường cũ là đúng
OTHER = ["giá vàng hôm nay", "thời tiết Huế thế nào", "tin tức mới nhất", "có tin gì mới không", "hôm nay thế nào", "mở Spotify", "chào buổi tối"]
WANT = ["weather", "market_price", "search_news"]
FAKE = {"weather": "📍 Thời tiết tại TP.HCM: nắng, 31°C.", "market_price": "| Sản phẩm | Mua | Bán |\n|---|---|---|\n| Vàng SJC | 140.100.000 | 143.100.000 |",
        "search_news": "📰 **Ngân hàng Nhà nước giữ lãi suất**\n🏷️ Nguồn: VnExpress\n🔗 https://vnexpress.net/a.html\n📝 Sapo: Giữ 4,5%."}


async def main():
    from engine.tools import registry as R, skill_manager
    from engine.turn import skills, entry, outcome
    from engine.turn.context import TurnContext
    from engine.turn.entry import handle_turn
    from e2e_turn import WS
    ok = total = 0
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "bao-cao-sang").mkdir()
        (Path(tmp) / "bao-cao-sang" / "SKILL.md").write_text(SKILL, encoding="utf-8")
        skill_manager.SKILLS_DIR = Path(tmp)
        skill_manager.get_skill_manager().skills.clear()
        tools = set(R.chat_names(None))
        for text in SAME + OTHER:
            hit = await asyncio.to_thread(skills.match, text, tools)
            good = bool(hit) == (text in SAME)
            total += 1; ok += good
            print(f"{'PASS' if good else 'FAIL'} [khớp] {text!r} → {hit['name'] if hit else None}")
        entry._find_workflow = lambda text: None
        outcome.save_turn = lambda *a, **k: None
        real_run = R.run
        # (câu, thời tiết): "ok" → đủ 3 bước, mỗi bước báo số liệu theo thứ tự, có tổng hợp đạt kiểm chứng;
        # "none" → tool không có dữ liệu; "thin" → tool trả kết quả nhưng thiếu nhiệt độ: kiểm chứng phải chặn, dừng
        for text, weather in ((SAME[0], "ok"), (SAME[1], "ok"), (SAME[0], "none"), (SAME[0], "thin")):
            weather_ok = weather == "ok"
            ran = []

            async def run(name, a, ctx=None):
                ran.append((name, a))
                if name == "weather" and weather == "none":
                    return R.ToolResult("Không lấy được thời tiết TP.HCM: nguồn không trả dữ liệu.", "no_result")
                if name == "weather" and weather == "thin":
                    return R.ToolResult("📍 Thời tiết tại TP.HCM: đang cập nhật.", "success")
                return R.ToolResult(FAKE.get(name, "ok"), "success")
            R.run = run

            async def send(_ws, data):
                return True
            ws = WS()
            try:
                answer = await handle_turn(text, TurnContext(ws=ws, send_json=send, conversation_history=[]))
            finally:
                R.run = real_run
            says = [st.get("say", "") for st in (getattr(ws, "last_turn", None) or {}).get("steps", [])]
            final = (getattr(ws, "last_turn", None) or {}).get("final_say", "")  # câu tổng hợp một lần ở cuối
            got, said = [n for n, _ in ran], answer or ""
            if weather_ok:  # số liệu từng bước xuất hiện đúng thứ tự trong lời báo cáo
                marks = [final.find("31"), final.find("140"), final.find("4,5")]  # tổng hợp đủ, đúng thứ tự bước
                # ngài 2026-10-20: báo dùng công cụ một lần (🛠️ một lần); câu báo bước 2-3 ngắn, không nhắc kết quả cũ
                quiet = said.count("🛠️") == 1 and all(len(x) <= 120 and not re.search(r"31|140|nắng", x) for x in says[1:])
                good = got == WANT and -1 not in marks and marks == sorted(marks) and "⚠️" not in said and quiet
                print(f"      icon={said.count('🛠️')} says={says}")
            else:
                # báo bước lỗi, không hứa chạy tiếp (skill đã dừng)
                good = (got == ["weather"] and bool(re.search(r"không|chưa|thiếu|thất bại", final, re.I))
                        and not re.search(r"(tôi|để tôi|giờ tôi)( sẽ)? (tiếp tục|chạy tiếp|làm tiếp)", final, re.I))
            total += 1; ok += good
            print(f"{'PASS' if good else 'FAIL'} [chạy, thời tiết {weather}] {text!r} → {got}")
            print("      →", said.replace("\n", " ⏎ ")[:700])
    print(f"{ok}/{total} PASS")

asyncio.run(main())

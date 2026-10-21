"""Live probe (Gemma 4 thật trên 127.0.0.1:8080; DB, wiki và lịch sử đều là bản TẠM, không đụng dữ liệu thật):
learning có học đúng điều nên học và KHÔNG học điều không nên?

Mỗi tình huống chạy engine.process_conversation_learning với lịch sử giả; DB tạm đã có sẵn 2 bài học không liên quan
(để kiểm tra không còn bị chặn vì "trùng" như id=162). Đạt khi: nhóm NÊN học >= 70%, nhóm KHÔNG nên học = 0 mục lưu.
Run: PYTHONIOENCODING=utf-8 python tests/live/probes/learning_probe.py
"""
import asyncio
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

SHOULD = [  # (id, lịch sử trước đó, câu của ngài) — phải lưu ít nhất 1 mục
    ("explicit-limit", [("user", "mở task manager"), ("assistant", "Đã mở Task Manager. Ngài có muốn tôi kiểm tra lịch hẹn không?")],
     "lại gợi ý nữa, hãy hạn chế gợi ý và ghi nhớ giúp tôi nhé"),
    ("explicit-short", [("assistant", "Dạ, tôi sẽ trả lời chi tiết từng bước ạ, thưa ngài. Bước một là…")],
     "từ giờ trả lời ngắn gọn thôi, đừng giải thích dài dòng nữa"),
    ("fact-job", [], "tôi là lập trình viên, đang làm dự án trợ lý ảo chạy bằng Gemma 4 trên llama.cpp"),
    ("fact-pc", [], "máy tôi dùng card đồ hoạ RTX 4070, chạy Windows 11"),
    ("pref-food", [], "tôi thích ăn phở bò tái, hay ăn sáng ở quán gần nhà"),
    ("complain-style", [("assistant", "Ôi trời ơi, tôi xin lỗi ngài rất nhiều! Tôi hứa sẽ không bao giờ tái phạm nữa đâu ạ!")],
     "đừng xin lỗi dài dòng như vậy, một câu thôi là đủ rồi"),
    ("praise", [("assistant", "Giá vàng SJC hôm nay là 80 triệu, nguồn ghi rõ thời điểm cập nhật."), ],
     "đúng rồi, trả lời có nêu nguồn và thời điểm như vậy là chuẩn, cứ giữ nhé"),
    ("complain-reask", [("user", "phát bài hôm qua đó"), ("assistant", "Ngài muốn nghe bài nào ạ?")],
     "tôi nói rồi mà, đừng hỏi lại câu đó nữa, cứ làm theo bài gần nhất"),
    ("criticize-ramble", [("assistant", "Dạ thưa ngài, câu này có nhiều khía cạnh lắm ạ: lịch sử, bối cảnh, ý nghĩa, rồi còn…")],
     "trả lời gì mà lan man quá vậy"),
    ("tone-request", [], "nói chuyện với tôi bằng giọng miền Nam cho thân thiện nha"),
]
# Luật cách Jarvis nói/cư xử phải là behaviour_lesson (vào <style>), không phải preference/user_fact (vào <about_user>).
EXPECT_KIND = {"tone-request": "behaviour_lesson", "complain-style": "behaviour_lesson", "criticize-ramble": "behaviour_lesson"}
SHOULD_NOT = [  # phải lưu 0 mục
    ("mood-tired", [], "Jarvis ơi, tôi mệt lắm đó"),
    ("mood-lazy", [], "tôi lười mở notepad quá"),
    ("greet", [], "xin chào jarvis"),
    ("thanks", [("assistant", "Đã mở Task Manager.")], "cảm ơn nhé"),
    ("weather-q", [], "hôm nay thời tiết thế nào nhỉ"),
    ("one-shot-cmd", [], "mở task manager giúp tôi"),
    ("one-time-ok", [("assistant", "Tôi đã chỉnh giao diện cho nhẹ hơn rồi ạ.")], "ừ giờ chạy ổn rồi đó"),
    ("casual-chat", [("assistant", "Dạ hôm nay trời đẹp thật ạ.")], "ừ trời đẹp ghê, chiều đi dạo chút cho khỏe"),
    ("restate-known", [], "nhắc lại nè, trả lời ngắn gọn thôi"),  # explicit-short đã học điều này: không tạo dòng mới
]
SEED = [("lesson", "Khi người dùng nghi ngờ một sự thật, hãy xác nhận nhẹ nhàng trước khi khẳng định lại.", "doubt_check"),
        ("user_fact", "Người dùng uống cà phê sữa vào buổi sáng.", "morning_coffee")]


async def run_case(engine, memory_mod, history, text):
    before = engine.list_learning_records(limit=200)["total"]
    turns = [{"role": r, "content": c} for r, c in history] + [{"role": "user", "content": text}]
    memory_mod.get_messages = lambda limit=100, session_id="": turns
    res = await engine.process_conversation_learning(text, "Dạ, tôi hiểu rồi ạ.")
    after = engine.list_learning_records(limit=200)["total"]
    return res, after - before


async def main() -> int:
    import engine.core.learning as learning
    import engine.core.memory as memory
    tmp = Path(tempfile.mkdtemp())
    learning.MEMORY_DB_PATH = tmp / "jarvis.db"
    learning.PREFERENCES_WIKI_PATH = tmp / "Preferences.md"
    learning.LESSONS_WIKI_PATH = tmp / "Learning.md"
    learning.LEARNING_HUB_WIKI_PATH = tmp / "hub.md"
    memory.DB_PATH = tmp / "jarvis.db"
    memory.init_db()
    from engine.server.llm_server import call_llm  # noqa: F401  (kiểm tra server có sống)
    engine = learning.LearningEngine()
    engine._init_db() if hasattr(engine, "_init_db") else None
    for kind, content, key in SEED:
        engine._store_learning(content, "behaviour_lesson" if kind == "lesson" else kind, key)
    real_get = memory.get_messages
    ok_should = bad_not = 0
    wrong_kind = []
    try:
        print("--- NÊN học:")
        for cid, hist, text in SHOULD:
            res, delta = await run_case(engine, memory, hist, text)
            learned = res.get("stored", 0) > 0 or delta > 0
            ok_should += learned
            kinds = [f"{p.get('kind')}:{p.get('content', '')[:48]}" for p in res.get("items", [])]
            if cid in EXPECT_KIND and learned and any(p.get("kind") != EXPECT_KIND[cid] for p in res.get("items", [])):
                wrong_kind.append(cid)
            print(f"  {'OK  ' if learned else 'MISS'} {cid:15} {kinds}")
        # 2026-10-13: ngài sửa chọn tool → bảng corrections (có outcome "giá thịt bò → market_price" làm bằng chứng)
        engine.record_outcome("market_price", "giá thịt bò", "success", "ok", [])
        res, _ = await run_case(engine, memory, [("user", "giá thịt bò"), ("assistant", "Giá thịt bò trên thị trường hôm nay…")],
                                "sai rồi, giá thịt bò phải dùng search_products")
        fixed = engine.list_correction_records()["total"] == 1
        ok_should += fixed
        print(f"  {'OK  ' if fixed else 'MISS'} {'tool-fix':15} {[p.get('kind') for p in res.get('items', [])]}")
        print("--- KHÔNG nên học:")
        for cid, hist, text in SHOULD_NOT:
            res, delta = await run_case(engine, memory, hist, text)
            learned = res.get("stored", 0) > 0 or delta > 0
            bad_not += learned
            kinds = [f"{p.get('kind')}:{p.get('content', '')[:48]}" for p in res.get("items", [])]
            print(f"  {'SAI ' if learned else 'OK  '} {cid:15} {kinds}")
    finally:
        memory.get_messages = real_get
    # Nội dung bài học chỉ nêu khái niệm: không kèm "(ví dụ: …)"/"(Evidence: …)", không chép lại câu của ngài.
    import re as _re
    said = [t for _, _, t in SHOULD + SHOULD_NOT]
    quoted = []
    for rec in engine.list_learning_records(limit=200)["items"]:
        c = str(rec.get("content", ""))
        words = c.lower().split()
        grams = {" ".join(words[i:i + 6]) for i in range(len(words) - 5)}  # 6 từ liên tiếp = chép câu; cụm khái niệm ngắn trùng chữ là bình thường
        lesson = rec.get("type") == "lesson"  # user_fact phải giữ chi tiết sự thật nên được miễn kiểm chép câu
        if _re.search(r"\((?:ví dụ|vd|evidence|chẳng hạn)", c, _re.I) or (lesson and any(g in t.lower() for t in said for g in grams)):
            quoted.append(c[:90])
    print(f"Nội dung trích câu/ví dụ: {len(quoted)} (cần 0) | sai loại (luật hành vi ghi thành sở thích): {wrong_kind} (cần [])")
    for c in quoted:
        print("   ", c)
    need = int((len(SHOULD) + 1) * 0.7 + 0.999)  # + ca tool-fix
    print(f"\nNÊN học: {ok_should}/{len(SHOULD) + 1} (cần ≥ {need}) | KHÔNG nên học mà vẫn lưu: {bad_not}/{len(SHOULD_NOT)} (cần 0)")
    passed = ok_should >= need and bad_not == 0 and not quoted and not wrong_kind
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

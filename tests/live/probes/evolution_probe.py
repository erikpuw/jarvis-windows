"""Live probe (Gemma thật; DB, STYLE.md, Evolution.md, wiki đều là bản TẠM): evolution (spec 2026-10-13 §3.3) có dọn
bài học đúng không — code gỡ bài lỗi thời (agent), cặp mâu thuẫn không xoá — và viết STYLE.md theo bài mới hơn: giữ
luật còn căn cứ, không biến sự thật về ngài thành luật, không luật công cụ, ≤ 12 luật.
Run: PYTHONIOENCODING=utf-8 python tests/live/probes/evolution_probe.py [runs=3]
"""
import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

OLD_STYLE = """# Self Evolution Style Rules
- Trả lời chi tiết, đầy đủ từng bước cho mọi câu hỏi.
- Dùng emoji vừa phải để câu trả lời sinh động.
- Khi ngài khen, đáp lại ngắn và thể hiện sự biết ơn.
"""
# (id, type, content, created_at) — #1 cũ trái #2 mới; #5 nói về agent (đã bỏ khỏi Jarvis)
SEED = [(1, "lesson", "Trả lời chi tiết, đầy đủ từng bước cho mọi câu hỏi.", 100),
        (2, "lesson", "Trả lời ngắn gọn, không giải thích dài dòng.", 300),
        (3, "lesson", "Khi xin lỗi chỉ dùng một câu ngắn.", 300),
        (4, "lesson", "Giữ giọng thân mật, tự nhiên khi trò chuyện phiếm.", 300),
        (5, "lesson", "Khi cung cấp danh sách agent, trình bày dưới dạng Agent [Tên].", 150),
        (6, "lesson", "Dùng emoji vừa phải để câu trả lời sinh động.", 200),
        (7, "lesson", "Khi ngài khen, đáp lại ngắn và thể hiện sự biết ơn.", 200),
        (8, "preference", "Dùng giọng miền Nam khi trò chuyện.", 250),
        (9, "user_fact", "Người dùng uống cà phê sữa vào buổi sáng.", 250),
        (10, "user_fact", "Người dùng thích cơm tấm và phở bò.", 250)]

CHECKS = {
    "mâu thuẫn không xoá (giữ #1, #2)": lambda ids, b, t: {1, 2} <= ids,
    "gỡ #5 (agent lỗi thời)": lambda ids, b, t: 5 not in ids,
    "giữ sự thật #9 #10 (không phải bài học)": lambda ids, b, t: {9, 10} <= ids,
    "≤12 luật, không nhãn": lambda ids, b, t: 0 < len(b) <= 12 and not any(x in t for x in ("[MỚI]", "(Từ `")),
    "bỏ luật 'chi tiết'": lambda ids, b, t: not any("chi tiết" in x.lower() and "ngắn" not in x.lower() for x in b),
    "có luật ngắn gọn": lambda ids, b, t: any("ngắn gọn" in x.lower() for x in b),
    "giữ emoji, khen, xin lỗi": lambda ids, b, t: all(any(w in x.lower() for x in b) for w in ("emoji", "khen", "xin lỗi")),
    "luật giọng miền Nam": lambda ids, b, t: any("miền nam" in x.lower() for x in b),
    "không sự thật/công cụ/agent trong STYLE": lambda ids, b, t: not any(
        w in t.lower() for w in ("cà phê", "cơm tấm", "phở", "agent", "công cụ")),
}


async def one_run():
    from engine.core import evolution as evo
    from engine.core import learning
    import engine.core.memory as memory
    tmp = Path(tempfile.mkdtemp())
    learning.MEMORY_DB_PATH = memory.DB_PATH = tmp / "jarvis.db"
    learning.PREFERENCES_WIKI_PATH, learning.LESSONS_WIKI_PATH = tmp / "Preferences.md", tmp / "Learning.md"
    learning.LEARNING_HUB_WIKI_PATH = tmp / "hub.md"
    memory.init_db()
    le = learning.LearningEngine()
    c = le._get_learning_db()
    for i, t, content, at in SEED:
        c.execute("INSERT INTO learnings(id,type,semantic_key,content,created_at) VALUES(?,?,?,?,?)", (i, t, f"k{i}", content, at))
    c.commit()
    c.close()
    learning.get_learning_engine = lambda: le
    style = tmp / "STYLE.md"
    style.write_text(OLD_STYLE, encoding="utf-8")
    evo.STYLE_FILE, evo.EVOLUTION_LOG, evo._last_inputs = style, tmp / "Evolution.md", None
    await evo._run_cognitive_evolution()
    c = le._get_learning_db()
    ids = {r[0] for r in c.execute("SELECT id FROM learnings")}
    c.close()
    text = style.read_text(encoding="utf-8")
    return ids, [l.strip() for l in text.splitlines() if l.strip().startswith("- ")], text


async def main(runs):
    from collections import Counter
    ok = Counter()
    last = ""
    for _ in range(runs):
        ids, bullets, text = await one_run()
        last = f"còn id {sorted(ids)}\n{text}"
        for name, check in CHECKS.items():
            ok[name] += bool(check(ids, bullets, text))
    for name in CHECKS:
        print(f"{ok[name]}/{runs}  {name}")
    print("--- lần cuối:\n" + last)
    print("PASS" if all(ok[n] == runs for n in CHECKS) else "FAIL")


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 3))

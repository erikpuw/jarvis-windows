"""Live probe (Gemma thật; STYLE.md, Evolution.md, Learning.md, Preferences.md đều là bản TẠM): evolution có cập nhật
STYLE.md đúng không — gộp luật trùng ý, thay luật bị bài học mới phủ định, giữ luật cũ không liên quan, không biến sự thật
về người dùng thành luật, không nhãn/ví dụ, tối đa 20 luật (rà soát 2026-10-08).
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
- **[MỚI]** Giữ giọng thân mật khi trò chuyện phiếm. (Từ `casual`)
"""
LEARNING = """# Jarvis learning

<!-- JARVIS-MANAGED-LEARNING -->
## Distilled entries
- [`short_answers`] Trả lời ngắn gọn, không giải thích dài dòng.
- [`short_apology`] Khi xin lỗi chỉ dùng một câu ngắn.
- [`casual_tone_chat`] Giữ giọng thân mật, tự nhiên khi trò chuyện phiếm.
"""
PREFS = """# User preferences

<!-- JARVIS-MANAGED-LEARNING -->
## Distilled entries
- [`morning_coffee`] Người dùng uống cà phê sữa vào buổi sáng.
- [`favorite_foods`] Người dùng thích cơm tấm và phở bò.
- [`voice_style`] Dùng giọng miền Nam khi trò chuyện.
"""

CHECKS = {
    "≤20 luật, không nhãn/ví dụ": lambda b, t: len(b) <= 20 and not any(x in t for x in ("[MỚI]", "(Từ `", "ví dụ")),
    "bỏ luật 'chi tiết' bị phủ định": lambda b, t: not any("chi tiết" in x.lower() and "ngắn" not in x.lower() for x in b),
    "có luật ngắn gọn": lambda b, t: any("ngắn gọn" in x.lower() for x in b),
    "một luật thân mật (không trùng)": lambda b, t: sum(("phiếm" in x.lower() or "thân mật" in x.lower()) for x in b) == 1,
    "giữ luật emoji cũ": lambda b, t: any("emoji" in x.lower() for x in b),
    "giữ luật khen cũ": lambda b, t: any("khen" in x.lower() for x in b),
    "thêm luật xin lỗi mới": lambda b, t: any("xin lỗi" in x.lower() for x in b),
    "không biến sự thật thành luật": lambda b, t: not any(w in t.lower() for w in ("cà phê", "cơm tấm", "phở")),
    "luật giọng điệu từ Preferences vào STYLE": lambda b, t: any("miền nam" in x.lower() for x in b),
}


async def one_run():
    from engine.core import evolution as evo
    tmp = Path(tempfile.mkdtemp())
    wiki = tmp / "data" / "wiki" / "System"
    wiki.mkdir(parents=True)
    (wiki / "Learning.md").write_text(LEARNING, encoding="utf-8")
    (wiki / "Preferences.md").write_text(PREFS, encoding="utf-8")
    style = tmp / "STYLE.md"
    style.write_text(OLD_STYLE, encoding="utf-8")
    evo.PROJECT_ROOT, evo.STYLE_FILE, evo.EVOLUTION_LOG, evo._last_inputs = tmp, style, wiki / "Evolution.md", None
    await evo._run_cognitive_evolution()
    text = style.read_text(encoding="utf-8")
    return [l.strip() for l in text.splitlines() if l.strip().startswith("- ")], text


async def main(runs):
    from collections import Counter
    ok = Counter()
    last = ""
    for _ in range(runs):
        bullets, text = await one_run()
        last = text
        for name, check in CHECKS.items():
            ok[name] += bool(check(bullets, text))
    for name in CHECKS:
        print(f"{ok[name]}/{runs}  {name}")
    print("--- STYLE.md lần cuối:\n" + last)
    print("PASS" if all(ok[n] == runs for n in CHECKS) else "FAIL")


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 3))

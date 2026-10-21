"""Live probe tạo skill (2026-10-20): (1) vòng chọn tool có chọn save_skill cho câu bảo tạo skill, không chọn cho câu
không phải; (2) write_skill với model thật ra skill đúng khung, bước đúng tool. Ghi vào thư mục tạm, không đụng skills/.
Run: PYTHONIOENCODING=utf-8 python tests/live/probes/skill_probe.py"""
import asyncio, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")

PICK = [("tạo skill báo cáo buổi sáng gồm thời tiết, giá vàng và tin thời sự", "save_skill"),
        ("nhớ cách làm vừa rồi thành skill", "save_skill"),
        ("ghi chú giúp tôi mai họp lúc 9 giờ", "save_note"),
        ("giá vàng hôm nay", "market_price")]
WRITE = [("tạo skill báo cáo buổi sáng gồm thời tiết, giá vàng và tin thời sự", [],
          ["weather", "market_price", "search_news"]),
         ("nhớ cách làm vừa rồi thành skill", [{"tool": "weather", "args": {"location": "Huế"}},
                                               {"tool": "market_price", "args": {"item": "vàng"}}],
          ["weather", "market_price"])]


async def main():
    from engine.turn.loop import step
    from engine.turn.entry import skill_request
    from engine.tools import skill_manager, skill_writer
    ok = total = 0
    for text, want in PICK:
        got = "save_skill" if skill_request(text) else (await step(text, []))["tool"]  # đúng đường entry
        total += 1; ok += got == want
        print(f"{'PASS' if got == want else 'FAIL'} [chọn] {text!r} → {got} (cần {want})")
    with tempfile.TemporaryDirectory() as tmp:
        skill_manager.SKILLS_DIR = Path(tmp)
        for text, run, want in WRITE:
            out = await skill_writer.write_skill(text, run)
            files = list(Path(tmp).glob("*/SKILL.md"))
            body = files[-1].read_text(encoding="utf-8") if files else ""
            tools = [ln.split(". ", 1)[1].split(" — ")[0] for ln in body.splitlines() if ln[:1].isdigit()]
            checks = [ln.split("| kiểm chứng:", 1)[1].strip() for ln in body.splitlines() if "| kiểm chứng:" in ln]
            good = (tools == want and "Câu mẫu:" in body and len(checks) == len(tools) and all(checks)
                    and "Tổng hợp: có đủ" in body)  # mỗi bước có kiểm chứng, có tiêu chí tổng hợp
            total += 1; ok += good
            print(f"{'PASS' if good else 'FAIL'} [viết] {text!r} → bước {tools} (cần {want})")
            print("     ", body.split("---", 2)[-1].replace("\n", " ⏎ ")[:700])
            for f in files:
                f.unlink(); f.parent.rmdir()
    print(f"{ok}/{total} PASS")

asyncio.run(main())

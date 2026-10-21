"""Live probe lượt tạo skill (2026-10-20, log 02:19: báo "đã tạo" 2 lần): handle_turn thật (route save_skill + vòng
trả lời), skill ghi vào thư mục tạm. Đạt: "say" một dòng, chưa nói "đã tạo" trước khi tool chạy; cả lượt nói đã tạo một lần.
Run: PYTHONIOENCODING=utf-8 python tests/live/probes/skill_create_turn_probe.py"""
import asyncio, re, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "live"))
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")

ASK = "tạo skill báo cáo buổi sáng gồm thời tiết thành phố hồ chí minh, giá vàng và tin tức chính phủ việt nam"
DONE = re.compile(r"đã tạo|tạo xong|thành công", re.I)


async def main():
    from engine.tools import skill_manager
    from engine.turn import outcome
    from engine.turn.context import TurnContext
    from engine.turn.entry import handle_turn
    from e2e_turn import WS
    outcome.save_turn = lambda *a, **k: None
    ok = 0
    for _ in range(2):
        with tempfile.TemporaryDirectory() as tmp:
            skill_manager.SKILLS_DIR = Path(tmp)

            async def send(_ws, data):
                return True
            ws = WS()
            answer = await handle_turn(ASK, TurnContext(ws=ws, send_json=send, conversation_history=[]))
            say = ws.last_turn["steps"][0]["say"]
            made = list(Path(tmp).glob("*/SKILL.md"))
            good = len(made) == 1 and "\n" not in say and not DONE.search(say) and len(DONE.findall(answer or "")) >= 1 \
                and (answer or "").count("Skill này") <= 1
            ok += good
            print(f"{'PASS' if good else 'FAIL'} say={say!r} done_mentions={len(DONE.findall(answer or ''))}")
            print("      →", (answer or "").replace("\n", " ⏎ ")[:600])
    print(f"{ok}/2 PASS")

asyncio.run(main())

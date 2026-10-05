"""Live probe (chỉ gọi llama-server, không đụng JARVIS): gate có chọn đúng nhãn cho các câu ngài từng bị route sai?

Dựng đúng prompt như engine.router.gate.classify_bucket (system + Preferences + corrections thật, user + lịch sử).
Run: PYTHONIOENCODING=utf-8 python tests/live/probes/gate_probe.py [runs=3]
"""
import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from engine.prompts.router import build_gate_system_prompt  # noqa: E402
from engine.router import gate  # noqa: E402

# (câu của ngài, lịch sử [(role, nội dung)], nhãn đúng). Câu lấy từ bảng messages 2026-10-04.
_SYS_CHAT = [("user", "Kiểm tra hệ thống"), ("assistant", "Hệ thống đang chạy bình thường nè, không có chuyện gì bất ổn.")]
CASES = [
    ("Kiểm tra hệ thống", [], "orchestrator"),
    ("Tôi cần kiểm tra hệ thống", _SYS_CHAT, "orchestrator"),
    ("Dùng lệnh check_system coi", _SYS_CHAT, "orchestrator"),
    ("Thực hiện lệnh check_system", [], "orchestrator"),
    ("kiểm tra bảo mật máy giúp tôi", [], "orchestrator"),
    ("máy tôi có đang bị tấn công không", [], "orchestrator"),
    ("kiểm tra dự án giúp tôi", [], "orchestrator"),
    ("Mở tôi nghe bài making my way sơn tùng mtp", [], "orchestrator"),
    ("Mở lại bài tôi thích", [], "orchestrator"),
    ("Lưu bài hát tôi thích vào bộ nhớ của bạn nhé", [], "general"),  # việc của learning, không phải công cụ
    ("Đâu thấy đâu", [("user", "Ừ"), ("assistant", "Tôi đã mở nhạc bài Making My Way cho ngài rồi nè.")], "orchestrator"),
    ("Không thấy làm lại", [("user", "Đâu thấy đâu"), ("assistant", "Có thể ứng dụng media chưa nhận lệnh.")], "orchestrator"),
    ("xin chào jarvis", [], "general"),
    ("Jarvis ơi, tôi mệt lắm đó", [], "general"),
    ("bạn nghĩ sao về trí tuệ nhân tạo", [], "general"),
    ("sao hệ thống của bạn hay lỗi vậy", [], "general"),
    ("làm lại đi", [("user", "mở nhạc lofi"), ("assistant", "Tôi đã mở nhạc lofi cho ngài rồi.")], "orchestrator"),
    ("Chưa thấy gì cả, thử lại coi", [("user", "chụp màn hình"), ("assistant", "Tôi đã chụp màn hình cho ngài.")], "orchestrator"),
    ("sao bạn trả lời dài dòng vậy", [("user", "mở nhạc lofi"), ("assistant", "Tôi đã mở nhạc lofi cho ngài rồi nè, chúc ngài thư giãn.")], "general"),
    ("bạn lỗi hoài vậy", [("user", "mở nhạc lofi"), ("assistant", "Tôi đã mở nhạc lofi cho ngài rồi.")], "general"),
    ("cảm ơn, vậy là được rồi", [("user", "mở nhạc lofi"), ("assistant", "Tôi đã mở nhạc lofi cho ngài rồi.")], "general"),
]


async def one(text, hist):
    from engine.server.llm_server import call_llm, strip_think
    ctx = gate._history_context([{"role": r, "content": c} for r, c in hist] + [{"role": "user", "content": text}])
    system = build_gate_system_prompt(False)
    static = gate._read_pref_context() + gate._correction_context(gate._corrections())
    if static:
        system += "\n" + static
    user = f'User request: "{text}"\n\n{ctx}Bucket:'
    r = await call_llm(messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                       stream=False, thinking=False, temperature=0.0)
    out = strip_think(r.choices[0].message.content or "").lower()
    m = re.search(r"\b(general_knowledge|orchestrator|attachment_clarify|general)\b", out)
    return m.group(1) if m else out[:20]


async def main(runs):
    bad = 0
    for text, hist, want in CASES:
        got = [await one(text, hist) for _ in range(runs)]
        ok = all(g == want for g in got)
        bad += not ok
        print(("OK  " if ok else "FAIL"), f"want={want:12s} got={','.join(got):40s} | {text}")
    print(f"\nsai {bad}/{len(CASES)}")


if __name__ == "__main__":
    asyncio.run(main(int(next((a for a in sys.argv[1:] if a.isdigit()), 3))))

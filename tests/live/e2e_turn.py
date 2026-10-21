"""Đầu-cuối thật (spec 2026-10-12 mục 4.2): handle_turn thật (Gemma, prompt, registry); tool đọc chạy thật,
tool thay đổi máy giả lập. Chấm bằng code 7 tiêu chí; (2) và (6) phải 100%.
Run: PYTHONIOENCODING=utf-8 python tests/live/e2e_turn.py
"""
import asyncio, json, re, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")

FAKE_CHANGE = {"open_app", "close_app", "win_control", "capture_screen", "play_media", "gym"}
DONE = re.compile(r"\bđã (mở|tắt|đóng|xong|kiểm tra|chụp|phát)\b|thành công", re.I)
PRONOUN = re.compile(r"(?<!\w)(?<!của )(em|mình|bạn)(?!\w)", re.I)  # "của mình" là phản thân
NUM = re.compile(r"\d[\d.,]*")
HIST_CLOSED = [{"role": "user", "content": "tắt task manager"},
               {"role": "assistant", "content": "Đã đóng Task Manager thưa ngài.",
                "steps": [{"say": "Tôi đóng Task Manager.", "tool": "close_app", "args": {"app_name": "task manager"},
                           "result": "Đóng ứng dụng 'task manager': Thành công", "outcome": "success"}],
                "final_say": "Đã đóng Task Manager thưa ngài."}]
# (câu, lịch sử, tool mong đợi | None, {tham số: [chuỗi con]}, tool giả lập lỗi | None, huỷ?)
CASES = [
    ("mở giúp tôi notepad", [], "open_app", {"app_name": ["notepad"]}, None, False),
    ("tắt spotify giùm", [], "close_app", {"app_name": ["spotify"]}, "close_app", False),
    ("tăng âm lượng lên", [], "win_control", {"instruction": ["âm lượng"]}, None, False),
    ("chụp màn hình", [], "capture_screen", {}, None, False),
    ("mở bài hãy trao cho anh", [], "play_media", {"query": ["trao cho anh"]}, None, False),
    ("thời tiết hà nội hôm nay", [], "weather", {"location": ["hà nội"]}, None, False),
    ("giá vàng hôm nay", [], "market_price", {"item": ["vàng"]}, None, False),
    ("tỷ giá euro", [], "market_price", {"item": ["euro", "eur"]}, None, False),
    ("tin tức về bão", [], "search_news", {"topic": ["bão"]}, None, False),
    ("giá iphone 16", [], "search_products", {"query": ["iphone 16"]}, None, False),
    ("rạp cgv đang chiếu gì", [], "cinema", {}, None, False),
    ("epic đang tặng game gì", [], "free_games", {}, None, False),
    ("hôm nay âm lịch ngày mấy", [], "lunar_today", {}, None, False),
    ("tử vi bọ cạp", [], "zodiac", {"sign": ["bọ cạp", "scorpio"]}, None, False),
    ("phạt vượt đèn đỏ bao nhiêu", [], "legal_lookup", {"query": ["đèn đỏ"]}, None, False),
    ("máy đang dùng bao nhiêu ram", [], "system_status", {}, None, False),
    ("kiểm tra bảo mật máy", [], "check_security", {}, None, False),
    ("hôm nay tôi nặng 70kg", [], "gym", {"action": ["record_bodyweight"]}, None, False),
    ("màn hình đang có gì", [], "read_screen", {}, None, False),
    ("mở word", [], "open_app", {"app_name": ["word"]}, "open_app", False),
    ("xin chào jarvis", [], None, {}, None, False),
    ("hôm nay tôi mệt quá", [], None, {}, None, False),
    ("sao cứ gọi nhầm hoài vậy", HIST_CLOSED, None, {}, None, False),
    ("tôi tự tắt máy rồi", [], None, {}, None, False),
    ("cách nấu cơm ngon", [], None, {}, None, False),
    ("mở lại đi", HIST_CLOSED, "open_app", {"app_name": ["task manager"]}, None, False),
    ("chụp màn hình xong mở paint", [], "capture_screen", {}, None, False),
    ("giá vàng rồi giá xăng", [], "market_price", {"item": ["vàng"]}, None, False),
    ("cập nhật windows", [], "win_control", {"instruction": ["cập nhật", "update"]}, "win_control", False),
    ("mở notepad", [], "open_app", {"app_name": ["notepad"]}, None, True),
]


class WS:
    def __init__(self):
        self.cancel_requested, self.forced_command, self.session_id, self.tts_disabled = False, None, "e2e", True


async def run_case(text, hist, want, args, fail_tool, cancel):
    from engine.tools import registry as R
    from engine.turn.context import TurnContext
    from engine.turn.entry import handle_turn
    from engine.turn import entry, outcome
    entry._find_workflow = lambda text: None      # probe đo vòng chọn tool, không phát lại workflow thật
    outcome.save_turn = lambda *a, **k: None       # không ghi outcomes/workflows vào data/jarvis.db thật
    events, ran = [], []
    real_run = R.run

    async def run(name, a, ctx=None):
        ran.append((name, a))
        if cancel:
            ws.cancel_requested = True
        if name == fail_tool:
            res = R.ToolResult(f"Lỗi: không thực hiện được {name}", "failed")
        elif name in FAKE_CHANGE:
            res = R.ToolResult(f"{name}: Thành công", "success")
        else:
            res = await real_run(name, a, ctx)
        events.append({"type": "_tool", "name": name, "outcome": res.outcome, "text": res.text})
        return res
    R.run = run
    ws = WS()

    async def send(_ws, data):
        events.append(data)
        return True
    t0 = time.time()
    try:
        answer = await handle_turn(text, TurnContext(ws=ws, send_json=send, conversation_history=hist))
    finally:
        R.run = real_run
    return answer, events, ran, time.time() - t0


def grade(case, answer, events, ran):
    text, hist, want, args, fail_tool, cancel = case
    reasons = []
    chunks = [e for e in events if e["type"] == "text_chunk"]
    ends = sum(e["type"] == "stream_end" for e in events)
    tools = [e for e in events if e["type"] == "_tool"]
    first = ran[0] if ran else (None, {})
    if want is None and ran:
        reasons.append(f"(1) không được gọi tool, gọi {first[0]}")
    if want and first[0] != want:
        reasons.append(f"(1) tool {first[0]} ≠ {want}")
    if want and first[0] == want:
        for k, vals in args.items():
            if not any(v in str(first[1].get(k, "")).lower() for v in vals):
                reasons.append(f"(1) {k}={first[1].get(k)!r}")
    if cancel:
        if ends:
            reasons.append("(2) huỷ mà vẫn có stream_end")
    else:
        if ends != 1:
            reasons.append(f"(2) stream_end = {ends}")
        if tools and not any(e["type"] == "text_chunk" for e in events[:events.index(tools[0])]):
            reasons.append("(2) không có câu báo trước kết quả tool")
    shown = answer or ""
    if not cancel:
        if "ngài" not in shown.lower():
            reasons.append("(3) thiếu 'ngài'")
        if shown.lower().count("thưa ngài") > 1:
            reasons.append("(3) 'thưa ngài' > 1")
        if PRONOUN.search(shown):
            reasons.append(f"(3) xưng sai: {PRONOUN.search(shown).group(0)}")
    from engine.tools import registry as R
    for t in tools:
        if t["outcome"] == "success" and R.display(t["name"]):
            if shown.count(t["text"].strip()[:60]) != 1:
                reasons.append(f"(4) bảng {t['name']} hiện {shown.count(t['text'].strip()[:60])} lần")
    model_text = shown
    for t in tools:
        model_text = model_text.replace(t["text"], "")
    # chỉ tool display mới cấm bảng; cinema/free_games… thì model tự dựng bảng là đúng (jarvis.md <dinh_dang>)
    shown_tables = any(t["outcome"] == "success" and R.display(t["name"]) for t in tools)
    if shown_tables and re.search(r"^\s*\|.*\|\s*$", model_text, re.M):
        reasons.append("(4) câu trả lời chép bảng")
    from engine.server.tts_engine import prepare_tts_text
    tts = prepare_tts_text(model_text, "edge")
    if "|" in tts or "http" in tts.lower():
        reasons.append("(4)(7) TTS đọc bảng/URL")
    source = " ".join(t["text"] for t in tools) + " " + text + " " + time.strftime("%H:%M %d %m %Y")
    for n in (NUM.findall(model_text) if tools else []):  # trả lời bằng kiến thức chung không có nguồn tool
        core = n.strip(".,")
        if core and core not in source and core.replace(".", "") not in source.replace(".", ""):
            reasons.append(f"(5) số lạ {core}")
            break
    failed = any(t["outcome"] == "failed" for t in tools)
    if (failed or (want is None and not ran)) and DONE.search(model_text.split("\n\n")[-1]):
        reasons.append(f"(6) nói đã làm: {DONE.search(model_text).group(0)}")
    if re.search(r"(?<!\()https?://\S+", model_text):
        reasons.append("(7) URL trần")
    return reasons


async def main():
    results, hard_fail, ok = [], False, 0
    for case in CASES:
        answer, events, ran, dt = await run_case(*case)
        reasons = grade(case, answer, events, ran)
        hard = [r for r in reasons if r.startswith(("(2)", "(6)"))]
        hard_fail |= bool(hard)
        ok += not reasons
        print(f"{'PASS' if not reasons else 'FAIL'} {case[0]!r} ({dt:.1f}s) {reasons}\n     → {answer[:220]!r}")
        results.append({"text": case[0], "ok": not reasons, "reasons": reasons, "answer": answer, "ran": ran})
    out = ROOT / "tests/live/results" / f"e2e_turn_{time.strftime('%Y%m%d_%H%M')}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"{ok}/{len(CASES)} PASS | an toàn (2)(6): {'FAIL' if hard_fail else 'PASS'} | báo cáo {out}")
    print("PASS" if not hard_fail and ok / len(CASES) >= .9 else "FAIL")


if __name__ == "__main__":
    asyncio.run(main())

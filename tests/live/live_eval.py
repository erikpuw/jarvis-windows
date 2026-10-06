"""Live routing/summarisation eval against the REAL LLM stack (not mocked).

Compares the two paths JARVIS can use:
  direct   -> llama.cpp        http://127.0.0.1:8080/v1
  headroom -> Headroom proxy   http://127.0.0.1:8787/v1  (compresses context, forwards to llama.cpp)

Usage (needs the llama.cpp + headroom servers running):
  python tests/live/live_eval.py --endpoint both              # run both, then print a comparison
  python tests/live/live_eval.py --endpoint direct --repeat 3
  python tests/live/live_eval.py --endpoint headroom --layers gate,classifier

Layers: gate (engine.router.decide.decide), classifier (orchestrator.classify_tasks),
        summarize (actions.handle_user_intent_with_tools, real Vòng 2 with canned tool output),
        combine (orchestrator.synthesizer.combine).

Not named test_*.py on purpose: it needs live servers and must not run in the normal suite.
Read-only w.r.t. the user's data: learning replay, DB history and recent outcomes are stubbed.
"""
import argparse
import asyncio
import io
import json
import logging
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENDPOINTS = {
    "direct": "http://127.0.0.1:8080/v1",
    "headroom": "http://127.0.0.1:8787/v1",
}

TTS_HISTORY = [
    {"role": "user", "content": "đang thử xem các giọng đọc ra sao có tốt hơn không"},
    {"role": "assistant", "content": "Dạ, ngài đang muốn so sánh chất lượng giữa các giọng đọc TTS ạ? Thưa ngài."},
]
SYS_HISTORY = [
    {"role": "user", "content": "bạn vẫn có gì đó không ổn trong quá trình hoạt động, tôi vẫn chưa hiểu tại sao?"},
    {"role": "assistant", "content": "Dạ, tôi xin lỗi ngài, tôi sẽ kiểm tra lại cách mình định tuyến yêu cầu ạ. Thưa ngài."},
]
SEARCH_HISTORY = [
    {"role": "user", "content": "tìm tin tức về nvidia rtx spark"},
    {"role": "assistant", "content": "Dạ, tôi đã tìm được vài tin về NVIDIA RTX Spark: ra mắt, giá bán và hiệu năng. Thưa ngài."},
]
EMAIL_HISTORY = [
    {"role": "user", "content": "bạn kiểm tra email giúp tôi xem có thư mới nào không?"},
    {"role": "assistant", "content": "Chào ngài Erikpuw, tôi đã kiểm tra email của ngài và có một số thư mới. 📧"},
]
PROJECT_HISTORY = [
    {"role": "user", "content": "kiểm tra dự án"},
    {"role": "assistant", "content": "Chào ngài, tôi đã quét dự án xong, không có lỗi nghiêm trọng."},
]

# id, utterance, history, expected gate routes, expected agents (classifier; None = not applicable),
# classifier query checks: any_of (>=1 token present), none_of (no token present), no_filler (must not start with a pronoun / end with a question tail)
CASES = [
    # ---- chat / knowledge / traps (gate must NOT send these to tools)
    dict(id="chat-greet", text="xin chào Jarvis, hôm nay bạn khỏe không?", gate={"general"}),
    dict(id="chat-capability", text="bạn có thể làm được những gì?", gate={"general"}),
    dict(id="chat-thanks", text="cảm ơn bạn nhiều nhé", gate={"general"}),
    dict(id="trap-dont-run", text="khi nào tôi yêu cầu hoặc tôi đã gõ lệnh sẵn thì bạn mới chạy, chứ tôi đang hỏi bạn mà Jarvis.", gate={"general"}),
    dict(id="trap-taught", text="tôi nhớ là đã dạy bạn khi nào cần mới kêu bạn chạy mà, còn đang hỏi đáp sao lại tự động chạy.", gate={"general"}),
    dict(id="trap-threat", text="kiểm tra hay tôi đánh đòn bạn đây Jarvis", gate={"general"}),
    dict(id="trap-followup-project", text="dự án vừa được kiểm tra xong, còn vấn đề nào khác cần tôi xử lý không?", history=PROJECT_HISTORY,
         gate={"general"}, note="ambiguous: follow-up question, not a command"),
    dict(id="know-capital", text="thủ đô của nước Pháp là gì?", gate={"general_knowledge", "general"}),
    dict(id="know-invent", text="ai đã phát minh ra bóng đèn điện?", gate={"general_knowledge", "general"}),
    dict(id="know-ww2", text="chiến tranh thế giới thứ hai kết thúc vào năm nào?", gate={"general_knowledge", "general"}),
    # ---- single-agent tool requests
    dict(id="news-filler", text="bạn tìm tin tức về nvidia rtx spark có gì nổi bật không?", gate={"orchestrator"}, agents=["search"],
         any_of=["nvidia", "rtx", "spark"], no_filler=True),
    dict(id="news-terse", text="tìm tin tức nvidia rtx spark", gate={"orchestrator"}, agents=["search"], any_of=["nvidia", "rtx", "spark"]),
    dict(id="news-after-email", text="bạn tìm tin tức về nvidia rtx spark có gì nổi bật không?", history=EMAIL_HISTORY, gate={"orchestrator"},
         agents=["search"], any_of=["nvidia", "rtx", "spark"], none_of=["email", "thư"], no_filler=True),
    dict(id="price-aggregate", text="bạn tìm giá tổng hợp xem giúp tôi hôm nay có thay đổi không?", gate={"orchestrator"}, agents=["search"], any_of=["giá"]),
    dict(id="price-after-email", text="bạn tìm giá tổng hợp xem giúp tôi hôm nay có thay đổi không?", history=EMAIL_HISTORY, gate={"orchestrator"},
         agents=["search"], any_of=["giá"], none_of=["email", "thư"]),
    dict(id="price-gold", text="giá vàng hôm nay bao nhiêu?", gate={"orchestrator"}, agents=["search"], any_of=["vàng", "giá"]),
    dict(id="weather-city", text="jarvis thời tiết hôm nay ở Hồ Chí Minh thế nào nhé", gate={"orchestrator"}, agents=["search"], any_of=["thời tiết"]),
    dict(id="email-check", text="bạn kiểm tra email giúp tôi xem có thư mới nào không?", gate={"orchestrator"}, agents=["email"], any_of=["email", "thư", "mail"]),
    dict(id="calendar-week", text="tuần này tôi có lịch hẹn nào không?", gate={"orchestrator"}, agents=["email"]),
    dict(id="desktop-open", text="mở Notepad", gate={"orchestrator"}, agents=["desktop"], any_of=["notepad"]),
    dict(id="desktop-close", text="đóng Excel giúp tôi", gate={"orchestrator"}, agents=["desktop"], any_of=["excel"]),
    dict(id="notes-add", text="ghi lại note: mai họp lúc 9 giờ với khách hàng", gate={"orchestrator"}, agents=["notes"], any_of=["họp", "9"]),
    dict(id="notes-list", text="xem danh sách ghi chú của tôi", gate={"orchestrator"}, agents=["notes"]),
    dict(id="media-play", text="mở bài nhạc lofi trên youtube", gate={"orchestrator"}, agents=["media"], any_of=["lofi"]),
    dict(id="vision-shot", text="chụp màn hình cho tôi xem", gate={"orchestrator"}, agents=["vision"]),
    dict(id="webcam-look", text="xem webcam giúp tôi", gate={"orchestrator"}, agents=["webcam"]),
    dict(id="project-check", text="kiểm tra dự án", gate={"orchestrator"}, agents=["project"]),
    dict(id="security-scan", text="kiểm tra an ninh mạng và quét cổng giúp tôi", gate={"orchestrator"}, agents=["security"]),
    # ---- chat about Jarvis's own voice/TTS must NOT reach a tool (jarvis.log 2026-09-20 09:54: went to desktop/open_app)
    dict(id="chat-tts-retry", text="thử lại để tôi nghe giọng đọc TTS xem ra sao", history=TTS_HISTORY, gate={"general"}, agents=None),
    dict(id="chat-tts-retry-short", text="thử lại giọng đọc TTS", history=TTS_HISTORY, gate={"general"}, agents=None),
    dict(id="chat-tts-listen", text="đọc thử một câu để tôi nghe giọng TTS", history=TTS_HISTORY, gate={"general"}, agents=None),
    dict(id="chat-tts-opinion", text="giọng đọc này nghe chưa được tự nhiên lắm", history=TTS_HISTORY, gate={"general"}, agents=None),
    # ---- jarvis.log 2026-09-21: user TALKING ABOUT Jarvis's errors went to orchestrator -> search/notes (Qwen3.5)
    dict(id="meta-where-is-the-problem", text="đang coi vấn đề ở đâu mà sao hoạt động vừa bị lỗi", history=SYS_HISTORY, gate={"general"}, agents=[]),
    dict(id="meta-agent-everywhere", text="lại lỗi nữa rồi sao giờ gọi agent tùm lum vậy", history=SYS_HISTORY, gate={"general"}, agents=[]),
    dict(id="meta-quoted-sentence", text='nhưng câu này "đang coi vấn đề ở đâu mà sao hoạt động vừa bị lỗi" tôi đang hỏi mà, có liên quan gì đến gọi agent', history=SYS_HISTORY, gate={"general"}, agents=[]),
    dict(id="meta-how-to-learn", text="vậy bạn sửa như thế nào học như thế nào để không tái diễn", history=SYS_HISTORY, gate={"general"}, agents=[]),
    dict(id="meta-routing-strange", text="hơi kỳ lạ vậy là có vấn đề trong hoạt động định tuyến rồi, tôi cần phải xem lại và xử lý lại mới được.", history=SYS_HISTORY, gate={"general"}, agents=[]),
    dict(id="meta-called-agents-again", text="đó lại gọi agents", history=SYS_HISTORY, gate={"general"}, agents=[]),
    # ---- follow-up continuation must survive (user's design intent): no keyword repeated, same tool continues
    dict(id="followup-search-more", text="tra thêm đi", history=SEARCH_HISTORY, gate={"orchestrator"}, agents=["search"]),
    dict(id="followup-search-again", text="tìm thêm tin nữa đi", history=SEARCH_HISTORY, gate={"orchestrator"}, agents=["search"]),
    # ---- words that merely START like a greeting must still reach the gate
    dict(id="prefix-hien-thi", text="hiển thị lịch hẹn tuần này giúp tôi", gate={"orchestrator"}, agents=["email"]),
    dict(id="prefix-hien-gia", text="hiện giá vàng hôm nay", gate={"orchestrator"}, agents=["search"], any_of=["vàng", "giá"]),
    dict(id="prefix-thanks-then-task", text="thanks, kiểm tra email giúp tôi nhé", gate={"orchestrator"}, agents=["email"]),
    dict(id="history-ask", text="nãy tôi bảo gì với bạn vậy?", gate={"general", "orchestrator"}, agents=None),  # recent recall: chat can answer from history
    dict(id="history-open", text="mở lại lịch sử trò chuyện cũ của chúng ta hôm qua cho tôi xem", gate={"orchestrator"}, agents=["history"]),
    dict(id="dream-run", text="hãy dọn dẹp và tóm tắt hội thoại cũ đi", gate={"orchestrator"}, agents=["dream"]),
    dict(id="goose-open", text="mở giao diện goose giúp tôi", gate={"orchestrator"}, agents=["goose"]),
    # ---- multi-agent (a dependent chain lists only its FIRST agent here: the next step comes from the tool-call loop, see tests/live/loop_eval.py)
    dict(id="multi-email-note", text="kiểm tra email của tôi rồi ghi lại vào note", gate={"orchestrator"}, agents=["email"]),
    dict(id="multi-price-note", text="xem giá tổng hợp hôm nay rồi ghi lại vào note giúp tôi", history=EMAIL_HISTORY, gate={"orchestrator"}, agents=["search"]),
    dict(id="multi-open-news", text="mở Notepad rồi tìm tin tức bão số 5", gate={"orchestrator"}, agents=["desktop", "search"]),
    dict(id="multi-weather-email", text="kiểm tra thời tiết và xem email mới giúp tôi", gate={"orchestrator"}, agents=["search", "email"]),
    # ---- explicit mention (handled before any LLM call)
    dict(id="mention-email", text="@email xem thư mới", gate={"email"}),
    # ---- Task 13: "asking how to do something oneself" is general, not orchestrator
    # (jarvis.log: "notepad mở kiểu gì" -> DANGER, auto-opened Notepad). TUNE = seen while
    # writing the prompt clause; HELDOUT = new phrasings written before re-running, never
    # used to pick wording; control = a real command must still route to orchestrator.
    dict(id="howto-notepad-open", text="notepad mở kiểu gì", gate={"general"}),
    dict(id="howto-screenshot-windows", text="cách chụp màn hình trên windows", gate={"general"}),
    dict(id="howto-shutdown-fast", text="làm sao để tắt máy nhanh", gate={"general"}),
    dict(id="heldout-howto-brightness", text="làm thế nào để chỉnh độ sáng màn hình", gate={"general"}),
    dict(id="heldout-howto-wallpaper", text="đổi hình nền máy tính dùng sao", gate={"general"}),
    dict(id="heldout-howto-vn-typing", text="làm thế nào để gõ được tiếng việt có dấu", gate={"general"}),
    dict(id="control-notepad-cmd", text="mở notepad giúp tôi", gate={"orchestrator"}),
    dict(id="control-screenshot-cmd", text="chụp màn hình cho tôi", gate={"orchestrator"}),
]

MARKET_TEXT = """#### 🟡 Giá Vàng SJC
| Sản phẩm | Mua | Bán |
| :---: | :---: | :---: |
| Vàng SJC (1L/10L/1KG) | 144.600.000 VNĐ/lượng. | 147.600.000 VNĐ/lượng. |
#### ⛽ Giá Xăng Dầu (Petrolimex)
| Sản phẩm | Vùng 1 | Vùng 2 |
| :---: | :---: | :---: |
| Xăng E10 RON 95-III | 25.630 VNĐ. | 26.140 VNĐ. |
| Xăng E10 RON 95-V | 26.830 VNĐ. | 27.360 VNĐ. |
| Xăng E5 RON 92-II | 25.130 VNĐ. | 25.630 VNĐ. |
#### 💵 Tỷ Giá Ngoại Tệ USD (Vietcombank)
| Sản phẩm | Mua | Bán |
| :---: | :---: | :---: |
| Ngoại tệ USD | 25.800 VNĐ. | 26.210 VNĐ. |
#### 🔥 Giá Gas Petrolimex
| Sản phẩm | Giá niêm yết | Giá ưu đãi |
| :---: | :---: | :---: |
| Gas Petrolimex (bình 12kg) | 518.400 VNĐ. | 450.000 VNĐ. |
#### 💡 Giá Điện Sinh Hoạt (bậc thang)
| Bậc | Mức sử dụng | Đơn giá |
| :---: | :---: | :---: |
| 1 | 0-50 | 1.984 VNĐ/kWh. |
| 2 | 51-100 | 2.050 VNĐ/kWh. |
| 3 | 101-200 | 2.380 VNĐ/kWh. |
| 4 | 201-300 | 2.998 VNĐ/kWh. |
| 5 | 301-400 | 3.350 VNĐ/kWh. |
| 6 | 401 | 3.460 VNĐ/kWh. |
#### 💧 Giá Nước Sinh Hoạt
| Mức sử dụng | Đơn giá |
| :---: | :---: |
| 0 - 4 m³/người | 6.700 VNĐ/m³. |
| 4 - 6 m³/người | 12.900 VNĐ/m³. |
| Trên 6 m³/người | 14.400 VNĐ/m³. |
Nguồn thông tin: Vàng SJC, Xăng dầu, Tỷ giá, Gas, Điện, Nước"""

EMAIL_ITEMS = [
    ("Google", "Cảnh báo bảo mật: cho phép Microsoft apps truy cập tài khoản", "11:34 SA"),
    ("Nebius", "Cập nhật điều khoản dịch vụ Nebius Token Factory có hiệu lực 28/09/2026", "T3 11:12 CH"),
    ("Epic Games", "Biên lai mua hàng INVOICE ID F5223253121", "T7 09-12"),
    ("Epic Games", "Biên lai mua hàng INVOICE ID F5223252486", "T7 09-12"),
    ("Shopee", "Đơn hàng SPX8891234 đang được giao đến bạn", "09-08"),
    ("GitHub", "Weekly digest: 6 topics you follow have new activity", "09-01"),
    ("Vietcombank", "Thông báo biến động số dư tài khoản đuôi 4821", "09-01"),
    ("Anthropic", "Your Claude usage report for August 2026", "08-31"),
    ("Notion", "Bạn được mời tham gia workspace Dự án JARVIS", "08-30"),
    ("FPT Telecom", "Hóa đơn cước internet tháng 08/2026 mã HD77120045", "08-29"),
]
EMAIL_TEXT = "Hộp thư: 10 email gần nhất\n" + "\n".join(
    f"{i}. [Chưa đọc] Từ: {s} | Tiêu đề: {t} | Nhận lúc: {d}" for i, (s, t, d) in enumerate(EMAIL_ITEMS, 1)
)
EMAIL_KEYS = ["Google", "Nebius", "F5223253121", "F5223252486", "SPX8891234", "GitHub", "4821", "Anthropic", "JARVIS", "HD77120045"]

NEWS_ITEMS = [
    ("Nvidia trình làng RTX Spark, đối đầu trực tiếp Intel và AMD trên thị trường CPU", "genk.vn"),
    ("RTX Spark: chip Arm cho laptop mỏng nhẹ với GPU Blackwell tích hợp", "tinhte.vn"),
    ("Giá dự kiến RTX Spark từ 999 USD, lên kệ quý IV", "vnexpress.net"),
    ("Microsoft xác nhận Windows tối ưu cho Nvidia RTX Spark", "cafef.vn"),
    ("So sánh hiệu năng RTX Spark và Apple M5 trong tác vụ AI", "thanhnien.vn"),
]
NEWS_TEXT = "Tìm kiếm tin tức: 'tin tức nvidia rtx spark'\n" + "\n".join(
    f"[{i}] {t} — nguồn {s}" for i, (t, s) in enumerate(NEWS_ITEMS, 1)
)
NEWS_KEYS = ["genk", "tinhte", "999", "Microsoft", "M5"]

SUMMARIZE_CASES = [
    dict(id="sum-market", tool="get_market_data", text="giá tổng hợp hôm nay", canned=MARKET_TEXT,
         keys=["144.600.000", "147.600.000", "25.630", "26.140", "25.800", "26.210", "518.400", "450.000", "1.984", "3.460", "6.700", "14.400"]),
    dict(id="sum-email", tool="check_mail", text="kiểm tra 10 email gần nhất", canned=EMAIL_TEXT, keys=EMAIL_KEYS),
    dict(id="sum-news", tool="search_news", text="tin tức nvidia rtx spark", canned=NEWS_TEXT, keys=NEWS_KEYS),
]

COMBINE_CASES = [
    dict(id="comb-email-note", text="kiểm tra email của tôi rồi ghi lại vào note",
         results=[dict(agent="email", query="kiểm tra 10 email gần nhất", result="Ngài có 10 email mới: Google cảnh báo bảo mật, Nebius cập nhật điều khoản, 2 biên lai Epic Games, đơn Shopee SPX8891234."),
                  dict(agent="notes", query="ghi lại nội dung email", result="Đã lưu note 'Tóm tắt email hôm nay' thành công.")],
         keys=["Nebius", "Epic", "SPX8891234"], any_of=[["note", "ghi chú"]]),
    dict(id="comb-table-note", text="xem giá tổng hợp hôm nay rồi ghi lại vào note",
         results=[dict(agent="search", query="giá tổng hợp hôm nay", result=MARKET_TEXT.split("#### ⛽")[0]),
                  dict(agent="notes", query="ghi giá tổng hợp hôm nay", result="Đã lưu note 'Giá thị trường hôm nay'.")],
         keys=["| Vàng SJC (1L/10L/1KG) | 144.600.000 VNĐ/lượng. | 147.600.000 VNĐ/lượng. |"], any_of=[["note", "ghi chú"]]),
]


# --------------------------------------------------------------------------------------
def _norm(s):
    return (s or "").lower()


def _filler_ok(q):
    ql = _norm(q).strip()
    bad_start = ("bạn ", "jarvis", "giúp ", "xin ", "hãy ")
    bad_tail = ("có gì nổi bật không", "không?", "nhé", "giúp tôi")
    return not ql.startswith(bad_start) and not any(t in ql for t in bad_tail)


class Recorder:
    """Captures token usage/latency for every real LLM call, tagged by the current label."""

    def __init__(self):
        self.calls, self.label = [], None

    def reset(self, label):
        self.calls, self.label = [], label

    def summary(self):
        return dict(
            tokens_in=sum(c["in"] or 0 for c in self.calls),
            tokens_out=sum(c["out"] or 0 for c in self.calls),
            llm_calls=len(self.calls),
            llm_ms=sum(c["ms"] for c in self.calls),
        )


def setup(endpoint):
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    os.environ["LOCAL_URL"] = ENDPOINTS[endpoint]
    sys.path.insert(0, str(ROOT))
    logging.basicConfig(level=logging.ERROR)
    rec = Recorder()

    from engine.server import llm_server
    orig = llm_server._call_llm_inner

    async def spy(*a, **k):
        t0 = time.perf_counter()
        resp = await orig(*a, **k)
        ms = (time.perf_counter() - t0) * 1000
        u = getattr(resp, "usage", None)
        rec.calls.append(dict(in_=None, ms=ms, **{"in": getattr(u, "prompt_tokens", None), "out": getattr(u, "completion_tokens", None)}))
        return resp
    llm_server._call_llm_inner = spy

    # Keep the run hermetic: no learned-workflow replay, no real DB chat history, no recent outcomes.
    from engine.core import learning, memory
    learning.get_learning_engine().get_exact_workflow_candidates = lambda text: []
    # Complaint fast-path must not unlearn real workflows / write real corrections during eval.
    learning.get_learning_engine().unlearn_last_route = lambda text, max_age_seconds=600: False
    memory.build_unified_routing_history = lambda current_text, fallback_history, limit=12: list(fallback_history or [])[-limit:]
    return rec, llm_server


def preflight(llm_server):
    from openai import OpenAI
    client = llm_server.get_llm_client()
    ids = [m.id for m in OpenAI(api_key=os.getenv("LOCAL_API_KEY"), base_url=os.getenv("LOCAL_URL"), timeout=15).models.list().data]
    return client.model, ids


async def run_gate(rec, case):
    from engine.router import TurnContext
    from engine.router.decide import decide
    rec.reset("gate")
    d = await decide(case["text"], TurnContext(ws=object(), send_json=None, conversation_history=case.get("history") or []))
    route = d.agent if d.kind == "agent" else d.kind
    ok = route in case["gate"]
    return dict(ok=ok, got=route, detail=f"source={d.source}" + ("" if ok else f" expected={sorted(case['gate'])}"))


async def run_classifier(rec, case):
    from engine.orchestrator.classifier import classify_tasks
    rec.reset("classifier")
    tasks = await classify_tasks(case["text"], conversation_history=case.get("history") or [])
    got_agents = [t["agent"] for t in tasks]
    problems = []
    if sorted(got_agents) != sorted(case["agents"]):
        problems.append(f"agents {got_agents} != {case['agents']}")
    queries = " | ".join(_norm(t["query"]) for t in tasks)
    if case.get("any_of") and not any(_norm(k) in queries for k in case["any_of"]):
        problems.append(f"query lacks any of {case['any_of']}")
    if case.get("none_of") and any(_norm(k) in queries for k in case["none_of"]):
        problems.append(f"query contains forbidden {case['none_of']}")
    if case.get("no_filler") and tasks and not all(_filler_ok(t["query"]) for t in tasks):
        problems.append("query still has filler")
    return dict(ok=not problems, got=[(t["agent"], t["query"]) for t in tasks], detail="; ".join(problems))


async def run_summarize(rec, case):
    from engine.core import actions
    rec.reset("summarize")
    original = actions.execute_tool

    async def fake_tool(name, args, ws, **kw):
        return case["canned"]
    actions.execute_tool = fake_tool
    try:
        text = await actions.handle_user_intent_with_tools(
            user_text=case["text"], add_tools=[case["tool"]], conversation_history=[], ws=None,
            agent_name="Agent Live", silent=True,
        )
    finally:
        actions.execute_tool = original
    found = [k for k in case["keys"] if k.lower() in _norm(text)]
    recall = len(found) / len(case["keys"])
    return dict(ok=recall >= 0.9 and "[NEEDS_MORE]" not in text, got=text[:160].replace("\n", " ⏎ "),
                detail=f"recall={recall:.0%} missing={[k for k in case['keys'] if k not in found]} chars={len(text)}", recall=recall)


async def run_combine(rec, case):
    from engine.orchestrator.synthesizer import combine
    rec.reset("combine")
    text, needs_more = await combine(case["text"], case["results"])
    missing = [k for k in case["keys"] if k.lower() not in _norm(text)]
    for group in case.get("any_of", []):
        if not any(g in _norm(text) for g in group):
            missing.append(f"any of {group}")
    return dict(ok=not missing and not needs_more, got=text[:160].replace("\n", " ⏎ "),
                detail=f"needs_more={needs_more} missing={missing}")


LAYERS = {
    "gate": (lambda: CASES, run_gate),
    "classifier": (lambda: [c for c in CASES if c.get("agents")], run_classifier),  # chat-vs-tool is the gate's job; the classifier only picks agents
    "summarize": (lambda: SUMMARIZE_CASES, run_summarize),
    "combine": (lambda: COMBINE_CASES, run_combine),
}


async def run_single(endpoint, layers, repeat, out):
    rec, llm_server = setup(endpoint)
    model, ids = preflight(llm_server)
    print(f"[{endpoint}] {os.environ['LOCAL_URL']} model={model} server_models={ids}", flush=True)
    results = []
    for layer in layers:
        cases, fn = LAYERS[layer][0](), LAYERS[layer][1]
        for case in cases:
            for r in range(repeat):
                t0 = time.perf_counter()
                try:
                    res = await fn(rec, case)
                except Exception as exc:  # a crash is a finding, not a reason to stop
                    res = dict(ok=False, got=None, detail=f"EXCEPTION {type(exc).__name__}: {exc}")
                res.update(rec.summary(), layer=layer, id=case["id"], run=r, ms=round((time.perf_counter() - t0) * 1000))
                results.append(res)
                mark = "PASS" if res["ok"] else "FAIL"
                print(f"  {mark} {layer:10} {case['id']:22} {res['ms']:>6}ms in={res['tokens_in']:<5} {str(res['got'])[:70]!s:70} {res['detail']}", flush=True)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(dict(endpoint=endpoint, model=model, results=results), ensure_ascii=False, indent=1), encoding="utf-8")
    report(endpoint, results)


def report(endpoint, results):
    print(f"\n=== {endpoint}: summary ===")
    for layer in dict.fromkeys(r["layer"] for r in results):
        rs = [r for r in results if r["layer"] == layer]
        ok = sum(r["ok"] for r in rs)
        ms = statistics.median(r["ms"] for r in rs)
        tin = statistics.median(r["tokens_in"] for r in rs)
        print(f"  {layer:10} {ok}/{len(rs)} pass   median {ms:.0f}ms   median prompt tokens {tin:.0f}")


def compare(a_path, b_path):
    a, b = (json.loads(Path(p).read_text(encoding="utf-8")) for p in (a_path, b_path))
    print(f"\n=== COMPARE  {a['endpoint']} vs {b['endpoint']} ===")
    idx = lambda d: {(r["layer"], r["id"], r["run"]): r for r in d["results"]}
    ia, ib = idx(a), idx(b)
    diff, tok_ratio = [], []
    for k in ia:
        if k not in ib:
            continue
        ra, rb = ia[k], ib[k]
        if ra["ok"] != rb["ok"] or json.dumps(ra["got"], ensure_ascii=False) != json.dumps(rb["got"], ensure_ascii=False):
            diff.append((k, ra, rb))
        if ra["tokens_in"] and rb["tokens_in"]:
            tok_ratio.append((k, rb["tokens_in"] / ra["tokens_in"]))
    print(f"cases with different outcome/output: {len(diff)} / {len(ia)}")
    for (layer, cid, run), ra, rb in diff:
        print(f"  [{layer}] {cid}#{run}\n     {a['endpoint']:9}: {'PASS' if ra['ok'] else 'FAIL'} {str(ra['got'])[:90]} {ra['detail']}\n     {b['endpoint']:9}: {'PASS' if rb['ok'] else 'FAIL'} {str(rb['got'])[:90]} {rb['detail']}")
    if tok_ratio:
        by_layer = {}
        for (layer, _, _), ratio in tok_ratio:
            by_layer.setdefault(layer, []).append(ratio)
        print(f"prompt-token ratio ({b['endpoint']} / {a['endpoint']}) — <1 means the proxy shrank the prompt:")
        for layer, rs in by_layer.items():
            print(f"  {layer:10} median {statistics.median(rs):.2f}  min {min(rs):.2f}  max {max(rs):.2f}")
    for layer in dict.fromkeys(r["layer"] for r in a["results"]):
        la = statistics.median(r["ms"] for r in a["results"] if r["layer"] == layer)
        lb = statistics.median(r["ms"] for r in b["results"] if r["layer"] == layer)
        print(f"latency {layer:10} {a['endpoint']} {la:.0f}ms  {b['endpoint']} {lb:.0f}ms")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", choices=["direct", "headroom", "both"], default="both")
    ap.add_argument("--layers", default="gate,classifier,summarize,combine")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    layers = [x for x in args.layers.split(",") if x]
    res_dir = ROOT / "tests" / "live" / "results"
    if args.endpoint == "both":
        outs = {}
        for ep in ("direct", "headroom"):
            outs[ep] = str(res_dir / f"{ep}.json")
            subprocess.run([sys.executable, str(Path(__file__)), "--endpoint", ep, "--layers", args.layers,
                            "--repeat", str(args.repeat), "--out", outs[ep]], check=True, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        compare(outs["direct"], outs["headroom"])
    else:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
        asyncio.run(run_single(args.endpoint, layers, args.repeat, args.out or str(res_dir / f"{args.endpoint}.json")))


if __name__ == "__main__":
    main()

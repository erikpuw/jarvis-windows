"""Dùng skill (ngài 2026-10-20): câu giống câu mẫu của skill learned (embedding) → vòng i bị grammar ép đúng tool
bước i, model chỉ điền tham số; xong bước cuối → vòng trả lời. Câu không khớp đi đường cũ."""
import asyncio

import pytest

from engine.tools import skill_manager as SM
from engine.turn import skills as S

SKILL = """---
name: bao-cao-sang
description: Báo cáo buổi sáng. Dùng khi ngài hỏi hôm nay có gì.
category: learned
enabled: true
---

Câu mẫu: Báo cáo sáng nay.; Hôm nay có gì?

1. market_price — giá vàng hôm nay | kiểm chứng: có giá mua và giá bán
2. bay_len_troi — bước lạ | kiểm chứng: có x
3. news — tin thời sự | kiểm chứng: có ít nhất 1 tin kèm nguồn

Tổng hợp: có đủ giá vàng và tin tức
"""
OLD = SKILL.replace(" | kiểm chứng: có giá mua và giá bán", "").replace("\n\nTổng hợp: có đủ giá vàng và tin tức", "")
VEC = {"báo cáo sáng nay": [1, 0, 0], "hôm nay có gì": [0.9, 0.1, 0], "sáng nay có gì mới không": [0.95, 0.05, 0],
       "giá vàng hôm nay": [0, 1, 0]}


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    for name, body in (("bao-cao-sang", SKILL), ("writing-skills", SKILL.replace("learned", "system")
                                                                        .replace("bao-cao-sang", "writing-skills"))):
        (tmp_path / name).mkdir()
        (tmp_path / name / "SKILL.md").write_text(body, encoding="utf-8")
    monkeypatch.setattr(SM, "SKILLS_DIR", tmp_path)
    monkeypatch.setattr(SM, "_skill_manager", None, raising=False)
    monkeypatch.setattr(S, "_embed", lambda t: VEC.get(t))
    S._VECS.clear()
    return tmp_path


def test_match_by_meaning_keeps_only_known_tools(skills_dir):
    hit = S.match("sáng nay có gì mới không", {"market_price", "news"})
    assert hit["name"] == "bao-cao-sang"
    assert hit["steps"] == [("market_price", "giá vàng hôm nay", "có giá mua và giá bán"),
                            ("news", "tin thời sự", "có ít nhất 1 tin kèm nguồn")]
    assert hit["tong_hop"] == "có đủ giá vàng và tin tức"


def test_skill_without_verification_is_not_run(skills_dir):
    """Ngài 2026-10-20: skill phải có kiểm chứng hẳn hoi; bước thiếu tiêu chí hoặc thiếu tổng hợp → không chạy skill."""
    (skills_dir / "bao-cao-sang" / "SKILL.md").write_text(OLD, encoding="utf-8")
    assert S.match("Báo cáo sáng nay", {"market_price", "news"}) is None


def test_no_match_for_other_sentences_or_system_skills(skills_dir):
    assert S.match("giá vàng hôm nay", {"market_price", "news"}) is None
    assert S.match("câu chưa có vector", {"market_price", "news"}) is None       # embedder lỗi → đường cũ


def test_block_lists_steps_and_marks_the_current_one():
    """Ngài 2026-10-20: vòng chọn tool biết đang chạy skill và đang ở bước nào; câu báo bước sau ngắn, không nhắc kết quả."""
    sk = {"name": "bao-cao-sang", "steps": [("market_price", "giá vàng", "có giá"), ("news", "tin", "có tin")],
          "tong_hop": "có đủ"}
    first, second = S.block(sk, 1), S.block(sk, 2)
    assert first.startswith("<skill") and "1. market_price — giá vàng\n2. news — tin" in first
    assert "bước 1/2: market_price — giá vàng" in first and "bước 2/2: news — tin" in second
    assert first != second and '"say"' in first and '"say"' not in second       # câu báo bước 2+ do loop viết


def test_verify_asks_model_with_grammar(monkeypatch):
    import json
    from types import SimpleNamespace
    seen = {}

    async def call_llm(**kw):
        seen.update(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps({"dat": False, "ly_do": "thiếu giá bán"})))])
    monkeypatch.setattr("engine.server.llm_server.call_llm", call_llm)
    ok, why = asyncio.run(S.verify("có giá mua và giá bán", "| Vàng | Mua 140.100.000 |"))
    assert ok is False and why == "thiếu giá bán"
    assert seen["response_format"]["json_schema"]["schema"]["required"] == ["ly_do", "dat"]   # lý do trước, kết luận sau
    user = seen["messages"][-1]["content"]
    assert "<tieu_chi>\ncó giá mua và giá bán\n</tieu_chi>" in user and "Mua 140.100.000" in user


def test_verify_error_counts_as_not_passed(monkeypatch):
    async def boom(**kw):
        raise RuntimeError("down")
    monkeypatch.setattr("engine.server.llm_server.call_llm", boom)
    ok, why = asyncio.run(S.verify("có x", "y"))
    assert ok is False and "không kiểm chứng được" in why


def _env(monkeypatch, verdicts=None):
    """Fixture env của test_loop; skills.verify giả: verdicts[i] cho lần kiểm chứng thứ i (mặc định đạt)."""
    import tests.turn.test_loop as T
    gen = T.env.__wrapped__(monkeypatch)
    env = next(gen)
    env["checks"] = []

    async def verify(criterion, result):
        env["checks"].append((criterion, result))
        ok = (verdicts or {}).get(len(env["checks"]), True)
        return ok, "đủ" if ok else "thiếu giá bán"
    monkeypatch.setattr(S, "verify", verify)
    return gen, env


SK = {"name": "bao-cao-sang", "steps": [("market_price", "giá vàng hôm nay", "có giá mua và giá bán"),
                                        ("news", "tin thời sự", "có ít nhất 1 tin")], "tong_hop": "có đủ giá vàng và tin"}


def test_each_step_verified_then_one_summary_answer(monkeypatch):
    """Ngài 2026-10-20 (log 02:08-02:10): vòng lặp đã có vòng trả lời tổng hợp riêng → skill không báo cáo từng bước;
    bước có kết quả + đạt kiểm chứng → gọi tool bước sau; xong cả skill → một vòng trả lời, kiểm chứng theo tiêu chí tổng hợp."""
    from tests.turn.test_loop import _ctx, _text
    from engine.turn import loop as L
    gen, env = _env(monkeypatch)
    try:
        env["script"] = [{"tool": "market_price", "say": "Tôi xem giá vàng.", "args": {"item": "vàng"}},
                         {"tool": "news", "say": "Tôi xem tin.", "args": {"topic": "thời sự"}},
                         "Sáng nay vàng 144,8 triệu, lãi suất giữ nguyên."]
        ctx = _ctx(env)
        asyncio.run(L.run_loop("báo cáo sáng nay", ctx, skill=SK))
        kinds = ["tool" if "response_format" in c else "answer" for c in env["calls"]]
        assert kinds == ["tool", "tool", "answer"]                                 # một vòng trả lời, ở cuối
        consts = [c["response_format"]["json_schema"]["schema"]["anyOf"][0]["properties"]["tool"]["const"]
                  for c in env["calls"] if "response_format" in c]
        assert consts == ["market_price", "news"]
        assert "bước 1/2" in env["calls"][0]["messages"][0]["content"]
        assert "bước 2/2" in env["calls"][1]["messages"][0]["content"]                # khối skill ghi bước hiện tại
        # vòng chọn bước 2 không thấy kết quả bước 1: câu báo không kể lại kết quả (probe 2/2 kể lại)
        assert not any("144.800.000" in m["content"] for m in env["calls"][1]["messages"])
        answer = env["calls"][2]["messages"]
        assert sum("<ket_qua" in m["content"] for m in answer) == 2                 # tổng hợp đủ kết quả cả hai bước
        # probe 2026-10-20: vòng trả lời chép câu báo bước ("Đang làm tin tức, đợi…") và chỉ kể bước cuối → không đưa câu
        # báo bước vào; kết quả cuối ghi đây là báo cáo một lần cho cả skill, theo tiêu chí tổng hợp
        assert not any(m["content"] in ("Tôi xem giá vàng.", "Tôi xem tin.") for m in answer)
        assert "có đủ giá vàng và tin" in answer[-1]["content"] and "<tong_hop>" in answer[-1]["content"]
        assert [c for c, _ in env["checks"]] == ["có giá mua và giá bán", "có ít nhất 1 tin", "có đủ giá vàng và tin"]
        assert "144.800.000" in env["checks"][0][1]                                # kiểm chứng kết quả thật của tool
        assert env["checks"][2][1] == "Sáng nay vàng 144,8 triệu, lãi suất giữ nguyên."  # kiểm chứng câu tổng hợp
        t = _text(env)
        # log 2026-10-20 02:29: bảng giá vàng (tool tự hiện bảng) chen giữa lượt skill; bước 3 nói "đang xem thời tiết"
        # → skill không hiện bảng giữa chừng (tổng hợp báo số liệu); câu báo từ bước 2 do code viết đúng việc của bước
        assert "| Vàng | 144.800.000 |" not in t and 'da_hien' not in answer[0]["content"]
        assert "Tôi xem tin." not in t and "Giờ tôi tra tin thời sự, ngài đợi giây lát nha." in t
        assert ctx.ws.last_turn["steps"][1]["say"] == "Giờ tôi tra tin thời sự, ngài đợi giây lát nha."
        assert t.index("Tôi xem giá vàng.") < t.index("Giờ tôi tra tin") < t.index("Sáng nay vàng")
        assert "⚠️" not in t and t.count(L.TOOL_ICON) == 1                           # báo dùng công cụ một lần
        assert ctx.ws.last_turn["final_say"] == "Sáng nay vàng 144,8 triệu, lãi suất giữ nguyên."
        (args, kw), = env["saved"]
        assert args[4] is False                                                    # không lưu thành workflow
    finally:
        gen.close()


def test_step_failing_verification_stops_and_answer_says_so(monkeypatch):
    from tests.turn.test_loop import _ctx
    from engine.turn import loop as L
    gen, env = _env(monkeypatch, verdicts={1: False})
    try:
        env["script"] = [{"tool": "market_price", "say": "Tôi xem giá vàng.", "args": {"item": "vàng"}},
                         "Giá vàng chưa đủ thông tin, tôi dừng ở đây."]
        out = asyncio.run(L.run_loop("báo cáo sáng nay", _ctx(env), skill=SK))
        assert len(env["calls"]) == 2 and env["ran"] == [("market_price", "vàng")]  # bước 2 không chạy
        last = env["calls"][1]["messages"][-1]["content"]
        assert 'trang_thai="failed"' in last and "không đạt kiểm chứng" in last and "thiếu giá bán" in last
        assert "các bước sau không chạy" in last                                   # không hứa "chạy tiếp" (probe 02:13)
        assert len(env["checks"]) == 1 and "tôi dừng ở đây" in out                  # không kiểm chứng tổng hợp
    finally:
        gen.close()


def test_step_without_result_stops(monkeypatch):
    from tests.turn.test_loop import _ctx
    from engine.tools import registry as R
    from engine.turn import loop as L
    gen, env = _env(monkeypatch)
    try:
        async def no_data(name, args, tctx=None):
            env["ran"].append(name)
            return R.ToolResult("Không có dữ liệu giá vàng lúc này.", "no_result")
        monkeypatch.setattr(R, "run", no_data)
        env["script"] = [{"tool": "market_price", "say": "Tôi xem giá vàng.", "args": {"item": "vàng"}},
                         "Chưa lấy được giá vàng, nên tôi dừng báo cáo ở đây."]
        out = asyncio.run(L.run_loop("báo cáo sáng nay", _ctx(env), skill=SK))
        assert env["ran"] == ["market_price"] and len(env["calls"]) == 2 and env["checks"] == []  # lỗi tool: khỏi kiểm chứng
        assert "Chưa lấy được giá vàng" in out
    finally:
        gen.close()


def test_step_with_bad_args_stops(monkeypatch):
    from tests.turn.test_loop import _ctx
    from engine.turn import loop as L
    gen, env = _env(monkeypatch)
    try:
        env["script"] = [{"tool": "open_app", "say": "Mở.", "args": {"app_name": ""}}, "Chưa mở được vì thiếu tên ứng dụng."]
        skill = {"name": "x", "steps": [("open_app", "mở app", "có app mở"), ("market_price", "giá vàng", "có giá")],
                 "tong_hop": "có đủ"}
        out = asyncio.run(L.run_loop("làm x", _ctx(env), skill=skill))
        assert env["ran"] == [] and len(env["calls"]) == 2 and "thiếu tên ứng dụng" in out
        assert 'trang_thai="failed"' in env["calls"][1]["messages"][-1]["content"]
        assert "các bước sau không chạy" in env["calls"][1]["messages"][-1]["content"]
    finally:
        gen.close()


def test_summary_failing_verification_is_flagged(monkeypatch):
    from tests.turn.test_loop import _ctx, _text
    from engine.turn import loop as L
    gen, env = _env(monkeypatch, verdicts={3: False})
    try:
        env["script"] = [{"tool": "market_price", "say": "Giá.", "args": {"item": "vàng"}},
                         {"tool": "news", "say": "Tin.", "args": {"topic": "thời sự"}}, "Chỉ có giá vàng."]
        asyncio.run(L.run_loop("báo cáo sáng nay", _ctx(env), skill=SK))
        assert "⚠️ Tổng hợp chưa đạt kiểm chứng (có đủ giá vàng và tin): thiếu giá bán." in _text(env)
    finally:
        gen.close()


def test_case_and_punctuation_do_not_matter(skills_dir):
    """Live 2026-10-20: câu mẫu JARVIS viết "Báo cáo buổi sáng cho tôi đi." vs "báo cáo sáng nay đi" 0.876 (trượt);
    chuẩn hoá cả hai (normalize_query) 0.919."""
    hit = S.match("Sáng nay có gì mới không?", {"market_price", "news"})
    assert hit and hit["name"] == "bao-cao-sang"


def test_called_by_name_without_embedding(skills_dir, monkeypatch):
    """Ngài 2026-10-20 chọn: câu có đúng cụm tên skill (bỏ dấu) → chạy skill đó, không phụ thuộc embedding."""
    monkeypatch.setattr(S, "_embed", lambda t: None)                              # embedder lỗi vẫn gọi được
    for t in ("Báo cáo sáng giúp tôi", "chạy skill bao-cao-sang"):
        hit = S.match(t, {"market_price", "news"})
        assert hit and hit["name"] == "bao-cao-sang", t
    assert S.match("báo cáo tài chính quý 3", {"market_price", "news"}) is None

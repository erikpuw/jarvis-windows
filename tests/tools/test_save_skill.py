"""JARVIS tự viết skill (ngài 2026-10-20): save_skill nạp skills/writing-skills/SKILL.md làm prompt, một lần gọi LLM
bị grammar ép {ten, mo_ta, cau_mau, buoc[{cong_cu ∈ tool thật, viec}]}, code kiểm tra rồi ghi skills/<ten>/SKILL.md."""
import asyncio
import json
import sqlite3
import time
from types import SimpleNamespace

import pytest

from engine.tools import skill_manager as SM
from engine.tools import skill_writer as W

DRAFT = {"ten": "bao-cao-sang", "mo_ta": "Báo cáo buổi sáng. Dùng khi ngài chào buổi sáng hoặc hỏi hôm nay có gì.",
         "cau_mau": ["báo cáo sáng nay", "hôm nay có gì"],
         "buoc": [{"cong_cu": "weather", "viec": "thời tiết nơi ngài ở", "kiem_chung": "có trạng thái trời và nhiệt độ"},
                  {"cong_cu": "market_price", "viec": "giá vàng hôm nay", "kiem_chung": "có giá mua và giá bán"},
                  {"cong_cu": "search_news", "viec": "tin thời sự", "kiem_chung": "có ít nhất 1 tin kèm nguồn"}],
         "tong_hop": "có đủ thời tiết, giá vàng và tin tức"}


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(SM, "SKILLS_DIR", tmp_path)
    return tmp_path


def _fake_llm(monkeypatch, draft, seen):
    async def call_llm(**kw):
        seen.update(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(draft)))])
    monkeypatch.setattr("engine.server.llm_server.call_llm", call_llm)


def test_writes_skill_file_from_draft(skills_dir, monkeypatch):
    seen = {}
    _fake_llm(monkeypatch, DRAFT, seen)
    out = asyncio.run(W.write_skill("tạo skill báo cáo buổi sáng", last_run=[]))
    text = (skills_dir / "bao-cao-sang" / "SKILL.md").read_text(encoding="utf-8")
    assert "Đã tạo skill bao-cao-sang" in out
    assert "name: bao-cao-sang" in text and "description: Báo cáo buổi sáng." in text
    assert "Câu mẫu: báo cáo sáng nay; hôm nay có gì" in text
    assert ("1. weather — thời tiết nơi ngài ở | kiểm chứng: có trạng thái trời và nhiệt độ\n"
            "2. market_price — giá vàng hôm nay | kiểm chứng: có giá mua và giá bán\n"
            "3. search_news — tin thời sự | kiểm chứng: có ít nhất 1 tin kèm nguồn") in text
    assert "Tổng hợp: có đủ thời tiết, giá vàng và tin tức" in text


def test_prompt_is_the_writing_skills_guide_with_inputs(skills_dir, monkeypatch):
    seen = {}
    _fake_llm(monkeypatch, DRAFT, seen)
    asyncio.run(W.write_skill("nhớ cách làm này", last_run=[{"tool": "weather", "args": {"location": "Huế"}}]))
    system, user = seen["messages"][0]["content"], seen["messages"][1]["content"]
    assert "<quy_tac>" in system and "name: writing-skills" not in system      # thân hướng dẫn, không frontmatter
    assert "<yeu_cau>\nnhớ cách làm này\n</yeu_cau>" in user
    assert '1. weather {"location": "Huế"}' in user and "<cong_cu>" in user and "- search_news:" in user
    enum = seen["response_format"]["json_schema"]["schema"]["properties"]["buoc"]["items"]["properties"]["cong_cu"]["enum"]
    assert "weather" in enum and "save_skill" not in enum and "save_note" in enum
    sch = seen["response_format"]["json_schema"]["schema"]
    assert "tong_hop" in sch["required"] and "kiem_chung" in sch["properties"]["buoc"]["items"]["required"]
    assert "<kiem_chung>" in system                                                # hướng dẫn dạy viết tiêu chí


def test_unknown_tools_dropped_and_empty_skill_refused(skills_dir, monkeypatch):
    _fake_llm(monkeypatch, {**DRAFT, "buoc": [{"cong_cu": "bay_len_troi", "viec": "x", "kiem_chung": "y"}]}, {})
    out = asyncio.run(W.write_skill("tạo skill bay", last_run=[]))
    assert "Chưa tạo được skill" in out and not list(skills_dir.iterdir())


def test_existing_name_not_overwritten(skills_dir, monkeypatch):
    (skills_dir / "bao-cao-sang").mkdir()
    (skills_dir / "bao-cao-sang" / "SKILL.md").write_text("cũ", encoding="utf-8")
    _fake_llm(monkeypatch, DRAFT, {})
    out = asyncio.run(W.write_skill("tạo skill báo cáo buổi sáng", last_run=[]))
    assert "đã có" in out and (skills_dir / "bao-cao-sang" / "SKILL.md").read_text(encoding="utf-8") == "cũ"


def test_last_run_takes_latest_successful_tool_chain(tmp_path, monkeypatch):
    from engine.tools.catalog import files as F
    db = tmp_path / "j.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE outcomes (tools TEXT, query TEXT, status TEXT, traces TEXT, created_at REAL)")
    now = time.time()
    rows = [("weather+market_price", "success", [{"tool": "weather", "args": {"location": "Huế"}}, {"tool": "market_price", "args": {"item": "vàng"}}], now - 60),
            ("save_note", "success", [{"tool": "save_note", "args": {}}], now - 30),
            ("search_news", "failed", [{"tool": "search_news", "args": {}}], now - 10)]
    for tools, status, traces, t in rows:
        c.execute("INSERT INTO outcomes VALUES (?,?,?,?,?)", (tools, "q", status, json.dumps(traces), t))
    c.commit(); c.close()
    monkeypatch.setattr(F, "DB_PATH", db)
    assert F._last_run() == [{"tool": "weather", "args": {"location": "Huế"}}, {"tool": "market_price", "args": {"item": "vàng"}}]


def test_save_skill_needs_skill_word():
    from engine.turn import loop as L
    for t in ("tạo skill báo cáo buổi sáng", "nhớ cách làm vừa rồi thành kỹ năng"):
        assert not L._off_target("save_skill", t), t
    for t in ("ghi nhớ là tôi thích cà phê", "nhớ cách làm này"):
        assert L._off_target("save_skill", t), t


def test_skill_request_routes_straight_to_save_skill():
    from engine.turn.entry import skill_request
    for t in ("tạo skill báo cáo buổi sáng gồm thời tiết, giá vàng và tin thời sự", "nhớ cách làm vừa rồi thành skill",
              "lưu thành kỹ năng giúp tôi", "tạo một kỹ năng tra giá vàng"):
        assert skill_request(t), t
    for t in ("giá vàng hôm nay", "skill này là gì", "kỹ năng nấu ăn của tôi tốt không"):
        assert not skill_request(t), t

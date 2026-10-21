"""Dream + self-healing theo grammar JSON + think 128 (2026-10-14): model không trả sai kiểu ("trivial": "false"
→ bool True → xoá nhầm), self-healing không lấy chữ thô có "CODE_BUG" làm lỗi code; Errors.md do code ghép."""
import asyncio
import json
from types import SimpleNamespace

from engine.core import dream, self_healing


def _fake_llm(payload, calls):
    async def call_llm(**kw):
        calls.append(kw)
        content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")])
    return call_llm


def _grammar(kw):
    assert kw["thinking"] is True and kw["thinking_budget"] == 128
    return kw["response_format"]["json_schema"]["schema"]


CHUNK = [{"role": "user", "content": "tôi chuyển nhà sang Thủ Đức rồi"}, {"role": "assistant", "content": "Dạ ngài."}]


def test_dream_message_uses_grammar_with_boolean_trivial(monkeypatch):
    calls = []
    monkeypatch.setattr(dream, "call_llm", _fake_llm({"trivial": False, "summary": "Ngài đã chuyển nhà sang Thủ Đức."}, calls))
    out = asyncio.run(dream._summarize_message_chunk(CHUNK))
    assert out == {"trivial": False, "summary": "Ngài đã chuyển nhà sang Thủ Đức."}
    schema = _grammar(calls[0])
    assert schema["properties"]["trivial"]["type"] == "boolean"
    assert "<hoi_thoai>" in calls[0]["messages"][0]["content"]


def test_dream_message_bad_json_retries_next_cycle(monkeypatch):
    monkeypatch.setattr(dream, "call_llm", _fake_llm("không phải json", []))
    assert asyncio.run(dream._summarize_message_chunk(CHUNK)) is None


def test_dream_wiki_uses_grammar(monkeypatch):
    calls = []
    monkeypatch.setattr(dream, "call_llm", _fake_llm({"bullets": ["Ngài mua xe mới.", "Ngài muốn biết thêm không?"]}, calls))
    out = asyncio.run(dream._summarize_wiki_note("…nội dung…", "2026-09-01"))
    assert out == "- Ngài mua xe mới."  # câu mời/hỏi vẫn bị _is_junk_bullet bỏ
    assert _grammar(calls[0])["properties"]["bullets"]["maxItems"] == 3
    assert "<ghi_chu>" in calls[0]["messages"][0]["content"]


def test_self_healing_enum_and_code_built_entry(monkeypatch, tmp_path):
    calls = []
    errors = tmp_path / "Errors.md"
    monkeypatch.setattr(self_healing, "ERRORS_FILE", errors)
    monkeypatch.setattr(self_healing, "call_llm", _fake_llm(
        {"classification": "CODE_BUG", "summary": "Biến chưa khai báo", "action": "Khai báo biến trước khi dùng"}, calls))
    err = 'Traceback...\n  File "x.py", line 3\nNameError: name \'foo\' is not defined'
    assert asyncio.run(self_healing._assess_and_log_error(err, "engine/x.py")) is True
    schema = _grammar(calls[0])
    assert schema["properties"]["classification"]["enum"] == ["CODE_BUG", "TRANSIENT", "CONFIG", "DEPENDENCY", "OTHER"]
    text = errors.read_text(encoding="utf-8")
    assert "Biến chưa khai báo" in text and "- Classification: CODE_BUG" in text and "- File: engine/x.py" in text
    assert "NameError" in text and "- Suggested action: Khai báo biến trước khi dùng" in text


def test_self_healing_raw_text_with_code_bug_word_is_not_a_bug(monkeypatch, tmp_path):
    """Trước: JSON hỏng → lấy chữ thô, có "CODE_BUG" (model liệt kê 5 loại) là hỏi ngài gửi Goose."""
    monkeypatch.setattr(self_healing, "ERRORS_FILE", tmp_path / "Errors.md")
    monkeypatch.setattr(self_healing, "call_llm", _fake_llm("CODE_BUG | TRANSIENT | CONFIG", []))
    assert asyncio.run(self_healing._assess_and_log_error("boom", "engine/x.py")) is False
    assert not (tmp_path / "Errors.md").exists()


def test_startup_info_lines_are_not_errors_nor_skip_notices(caplog):
    """log 2026-10-14 22:15: 2 dòng khởi động bình thường có chữ "stream_tts/port 8082" bị khớp bộ lọc lỗi tạm thời
    → in "skipped transient Telegram polling timeout" dù không có lỗi nào. Chỉ dòng lỗi mới được xét."""
    entries = ["2026-10-14 22:15:00 [jarvis] stream_tts (VieNeu) is already running independently on port 8082\n",
               "2026-10-14 22:15:01 [jarvis] [vieneu] stream_tts đã sẵn sàng trên port 8082\n",
               "2026-10-14 22:16:00 [tg] Telegram polling request failed; retrying: TimeoutError\n",
               "2026-10-14 22:17:00 [x] ERROR boom\nTraceback (most recent call last):\n"]
    with caplog.at_level("INFO", logger="jarvis.self_healing"):
        blocks = self_healing._error_blocks(entries)
    assert blocks == [entries[3]]
    skipped = [r.getMessage() for r in caplog.records if "skipped" in r.getMessage()]
    assert len(skipped) == 1 and "Telegram polling request failed" in skipped[0]

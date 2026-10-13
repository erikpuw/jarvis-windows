"""Ô 'Cách JARVIS xưng hô' (HONORIFIC) và USER_NAME trong Settings phải có tác dụng lên prompt, chữ hiển thị và TTS."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.prompts import honorific as h, load


def _env(monkeypatch, honorific="ngài", name="erikpuw"):
    monkeypatch.setenv("HONORIFIC", honorific)
    monkeypatch.setenv("USER_NAME", name)


def test_default_is_noop(monkeypatch):
    _env(monkeypatch)
    s = "Thưa ngài, trợ lý của ngài erikpuw. Ngài có muốn không? Bạn là JARVIS."
    assert h.personalize(s) == s


def test_custom_pronoun_and_name(monkeypatch):
    _env(monkeypatch, "Anh", "Hòa")
    out = h.personalize('trợ lý của ngài erikpuw. Ngài có muốn không? gọi là “ngài”, thưa ngài. Bạn là JARVIS.')
    assert out == 'trợ lý của anh Hòa. Anh có muốn không? gọi là “anh”, thưa anh. Bạn là JARVIS.'


def test_thua_prefix_is_accepted(monkeypatch):
    _env(monkeypatch, "thưa anh")
    assert h.personalize("Thưa ngài, ngài ơi") == "Thưa anh, anh ơi"


def test_ban_drops_the_clause_that_forbids_ban(monkeypatch):
    _env(monkeypatch, "bạn")
    s1 = 'xưng “tôi”, gọi người dùng là “ngài”, không dùng “bạn”; chỉ nói “thưa ngài” đúng một lần'
    assert h.personalize(s1) == 'xưng “tôi”, gọi người dùng là “bạn”; chỉ nói “thưa bạn” đúng một lần'
    s2 = 'gọi người dùng là "ngài" (KHÔNG dùng "bạn", "you"), "thưa ngài" chỉ'
    assert h.personalize(s2) == 'gọi người dùng là "bạn", "thưa bạn" chỉ'


def test_load_applies_to_real_prompt(monkeypatch):
    _env(monkeypatch, "Anh", "Hòa")
    from pathlib import Path
    from engine.prompts.honorific import personalize
    text = personalize((Path(__file__).resolve().parents[1] / "prompt" / "jarvis.md").read_text(encoding="utf-8"))
    assert "anh Hòa" in text and '"anh"' in text
    assert "ngài" not in text.lower() and "erikpuw" not in text


def test_trailing_regex_strips_old_and_new_honorific(monkeypatch):
    _env(monkeypatch, "anh")
    rx = h.trailing_honorific_re()
    assert rx.sub("", "Xong.\nThưa anh.") == "Xong."
    assert rx.sub("", "Xong.\nthưa ngài") == "Xong."


def test_payload_and_tts_are_personalized(monkeypatch):
    _env(monkeypatch, "Anh")
    assert h.personalize_payload({"type": "text_chunk", "text": "Chào ngài"}) == {"type": "text_chunk", "text": "Chào anh"}
    other = {"type": "status", "text": "ngài"}
    assert h.personalize_payload(other) is other
    from engine.server.tts_engine import prepare_tts_text
    assert "ngài" not in prepare_tts_text("Xin chào ngài.").lower()

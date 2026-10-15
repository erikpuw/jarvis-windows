"""Mọi test ghi wiki vào thư mục tạm (2026-10-13: hai lần test ghi đè data/wiki thật — hub Workflows rồi Learning.md,
vì đường dẫn wiki tính sẵn lúc import). Test cần đường dẫn riêng vẫn tự monkeypatch đè lên được."""
import pytest

from engine.core import evolution, learning, self_healing


@pytest.fixture(autouse=True)
def _wiki_in_tmp(tmp_path, monkeypatch):
    system = tmp_path / "_wiki" / "System"
    wf = system / "Workflows"
    for name, path in (("WORKFLOWS_WIKI_DIR", wf), ("WORKFLOWS_HUB_WIKI_PATH", wf / "Công cụ.md"),
                       ("PREFERENCES_WIKI_PATH", system / "Preferences.md"),
                       ("LESSONS_WIKI_PATH", system / "Learning.md"),
                       ("LEARNING_HUB_WIKI_PATH", system / "Học hỏi.md")):
        monkeypatch.setattr(learning, name, path)
    monkeypatch.setattr(evolution, "EVOLUTION_LOG", system / "Evolution.md")
    monkeypatch.setattr(self_healing, "ERRORS_FILE", system / "Errors.md")
    monkeypatch.setattr(evolution, "STYLE_FILE", tmp_path / "_skills" / "STYLE.md")


@pytest.fixture(autouse=True)
def _default_honorific(monkeypatch):
    """`import server` nạp .env thật (HONORIFIC=bro, 2026-10-15) vào os.environ → test TTS/prompt chạy sau đổi "ngài".
    Mặc định xưng hô gốc; test cần xưng hô khác tự setenv."""
    monkeypatch.delenv("HONORIFIC", raising=False)
    monkeypatch.delenv("USER_NAME", raising=False)

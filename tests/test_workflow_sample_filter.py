import asyncio
import json
import sqlite3
import sys
import time
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.core import learning
from engine.core.learning import LearningEngine


@pytest.fixture
def test_engine(tmp_path, monkeypatch):
    db_file = tmp_path / "jarvis.db"
    monkeypatch.setattr(learning, "MEMORY_DB_PATH", db_file)
    monkeypatch.setattr(learning, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(learning, "WORKFLOWS_WIKI_DIR", tmp_path / "workflows")
    monkeypatch.setattr(learning, "LEARNING_HUB_WIKI_PATH", tmp_path / "hub.md")
    engine = LearningEngine()
    return engine


def test_is_explicit_complaint_detects_user_criticisms():
    complaints = [
        "sai rồi bạn ơi",
        "không phải vậy đâu",
        "đừng có mở lung tung",
        "không được gọi vision nữa",
        "lại nữa rồi chán quá",
        "loạn rồi",
        "sao lại gọi goose",
        "tại sao lại làm thế",
        "nhầm rồi",
        "bậy bạ quá",
        "vô lý vậy",
        "đâu có kêu mày mở steam",
        "không có bảo làm việc này",
    ]
    for c in complaints:
        assert LearningEngine._is_explicit_complaint(c) is True, f"Expected '{c}' to be detected as complaint"

    not_complaints = [
        "chào jarvis",
        "mở steam giùm tôi",
        "hôm nay thời tiết thế nào",
        "tôi đang xem lại code",
        "chỉ là kiểm tra giao diện thôi",
    ]
    for nc in not_complaints:
        assert LearningEngine._is_explicit_complaint(nc) is False, f"Expected '{nc}' NOT to be detected as complaint"


def test_has_explicit_signal_accepts_only_valid_intents(test_engine):
    # 1. Yêu cầu học tường minh
    assert test_engine._has_explicit_signal("nhớ là tôi thích uống cà phê đen nhé", "cà phê đen", "preference") is True
    assert test_engine._has_explicit_signal("từ nay hãy trả lời ngắn gọn", "trả lời ngắn gọn", "behaviour_lesson") is True

    # 2. Phàn nàn / cấm đoán tường minh
    assert test_engine._has_explicit_signal("sai rồi đừng mở terminal nữa", "đừng mở terminal", "behaviour_lesson") is True
    assert test_engine._has_explicit_signal("sao lại gọi agent win_control", "sao lại gọi", "behaviour_lesson") is True

    # 3. Sở thích / sự thật cá nhân lâu dài
    assert test_engine._has_explicit_signal("sở thích của tôi là nghe nhạc", "nghe nhạc", "user_fact") is True
    assert test_engine._has_explicit_signal("tôi thích ăn cơm tấm", "cơm tấm", "preference") is True

    # 4. Trò chuyện, trần thuật bình thường -> PHẢI BỊ TỪ CHỐI
    assert test_engine._has_explicit_signal("tôi đang xem lại giao diện webui", "giao diện webui", "behaviour_lesson") is False
    assert test_engine._has_explicit_signal("chỉ là kiểm tra chút thôi", "kiểm tra", "behaviour_lesson") is False
    assert test_engine._has_explicit_signal("hôm nay trời đẹp quá", "trời đẹp", "user_fact") is False
    assert test_engine._has_explicit_signal("mở giúp tôi ứng dụng edge", "mở ứng dụng edge", "behaviour_lesson") is False




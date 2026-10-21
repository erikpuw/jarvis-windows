"""Test get_behaviour_rules() và integration vào chat system prompt."""
import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from engine.core.learning import LearningEngine


@pytest.fixture
def temp_db_path():
    """Tạo DB tạm cho test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        yield db_path


@pytest.fixture
def engine(temp_db_path):
    """Tạo LearningEngine với DB tạm (không dùng data/jarvis.db thật)."""
    # Patch đường dẫn DB
    with patch("engine.core.learning.MEMORY_DB_PATH", temp_db_path):
        eng = LearningEngine()
        yield eng


def test_propose_prompt_routes_how_jarvis_behaves_to_behaviour_lesson():
    """Review Task E: 'hạn chế gợi ý' từng bị phân loại thành preference (vào <about_user>, không phải <style>);
    prompt đề xuất phải nói rõ yêu cầu về CÁCH Jarvis cư xử là behaviour_lesson."""
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "prompt" / "learning_propose.md").read_text(encoding="utf-8")
    assert "lesson: cách Jarvis nói, trả lời, cư xử" in text  # prompt 2026-10-14: chỉ học điều ngài dạy
    assert "preference / user_fact: sở thích hoặc sự thật lâu dài về chính ngài" in text

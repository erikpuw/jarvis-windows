"""Luồng tiến hóa hai lượt (spec 2026-10-13 §3.3): lượt 1 model đề xuất gỡ/gộp bài học trùng, lượt 2 viết STYLE.md
từ bài học còn lại. Model được giả (`ev._ask`), bài học lấy từ một LearningEngine giả, STYLE/Evolution ghi vào thư mục tạm."""
import asyncio
import tempfile
import time
from pathlib import Path

import engine.core.evolution as ev

EMOJI = "🤵✨😊"
NOW = time.time()
ITEMS = [
    {"id": 1, "type": "lesson", "content": "gọi agent điều khiển bằng control", "created_at": NOW - 100, "embedding": None},
    {"id": 2, "type": "preference", "content": "giữ giọng thân thiện hài hước", "created_at": NOW - 50, "embedding": None},
]


class FakeLearning:
    def __init__(self):
        self.deleted = []

    def evolution_items(self):
        return [dict(i) for i in ITEMS if i["id"] not in self.deleted]  # như DB: bài đã gỡ không còn

    def delete_learning_control_record(self, kind, rid):
        self.deleted.append(rid)
        return True

    def update_learning_control_record(self, kind, rid, fields):
        return True


def _isolate(root: Path, monkeypatch, styled: list[str]):
    """Trỏ evolution.py vào thư mục tạm; `calls` ghi lại các lượt gọi model."""
    import engine.core.learning as learning
    fake = FakeLearning()
    calls = []

    async def fake_ask(prompt, name, schema):
        calls.append(name)
        return {"remove": [], "merge": []} if name == "evolution" else {"style": styled}

    monkeypatch.setattr(learning, "get_learning_engine", lambda: fake)
    monkeypatch.setattr(ev, "STYLE_FILE", root / "skills" / "self_evolution" / "STYLE.md")
    monkeypatch.setattr(ev, "EVOLUTION_LOG", root / "data" / "wiki" / "System" / "Evolution.md")
    monkeypatch.setattr(ev, "_ask", fake_ask)
    monkeypatch.setattr(ev, "_last_inputs", None)
    return fake, calls


def test_full_run_drops_invented_rules_and_skips_unchanged_inputs(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        fake, calls = _isolate(Path(tmp), monkeypatch, [
            "Giữ giọng thân thiện hài hước.",
            "Hãy báo giá vàng mỗi sáng lúc 6 giờ.",      # bịa: không có bài học nào làm căn cứ
            "Dùng tool để gọi điện, nhắn tin.",           # nói về tool: không phải giọng điệu
        ])
        first = asyncio.run(ev._run_cognitive_evolution())
        assert first["success"], first
        style = ev.STYLE_FILE.read_text(encoding="utf-8")
        assert "hài hước" in style and "báo giá vàng" not in style and "gọi điện" not in style
        assert not ev.STYLE_FILE.with_suffix(".md.bak").exists(), "Không được sinh ra file .bak"
        # bài học nhắc "agent" là lỗi thời (agent đã gỡ khỏi Jarvis): gỡ và ghi vào Evolution.md để khôi phục
        assert fake.deleted == [1]
        assert "gọi agent điều khiển bằng control" in ev.EVOLUTION_LOG.read_text(encoding="utf-8")
        assert calls == ["evolution", "evolution_style"]

        second = asyncio.run(ev._run_cognitive_evolution())
        assert second["success"] and calls == ["evolution", "evolution_style"], "Đầu vào không đổi thì không gọi model"


def test_emoji_stripped_from_style(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        _isolate(Path(tmp), monkeypatch, [f"Giữ giọng thân thiện hài hước. {EMOJI}"])
        result = asyncio.run(ev._run_cognitive_evolution())
        assert result["success"]
        style = ev.STYLE_FILE.read_text(encoding="utf-8")
        assert EMOJI not in style, style
        assert "hài hước" in style

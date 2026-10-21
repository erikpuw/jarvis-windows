import tempfile
from pathlib import Path

import engine.core.evolution as ev

HEAD = '---\nversion: "1.0.0"\n---\n\n# Self Evolution Style Rules\n'
OLD = HEAD + "- a\n- b\n- c\n- d\n"


LESSON = "gọi agent điều khiển bằng control"


def test_rule_without_supporting_lesson_is_rejected():
    line = "- Gửi email, gọi điện, nhắn tin → `agent_weather`."
    assert ev._bad_rule(line, [LESSON]) == "không có bài học nào làm căn cứ"


def test_supported_rule_passes_with_lexical_grounding():
    """Luật phong cách có căn cứ từ vựng trong bài học (2026-10-13: nhánh routing đã bỏ, luật công cụ bị chặn)."""
    line = "- Trả lời ngắn gọn khi ngài đang bận."
    lesson = "ngài muốn Jarvis trả lời ngắn gọn khi ngài bận"
    assert ev._bad_rule(line, [lesson]) is None
    assert ev._bad_rule("- Dùng control để mở Windows Update.", ["gọi control để mở cửa sổ"]) is not None


# Task B2: Tests for lexical grounding (Jaccard) instead of cosine
def test_grounding_uses_lexical_jaccard_not_cosine():
    """Luật 'Luôn thêm sự hài hước và dí dỏm vào các cuộc hội thoại.' có căn cứ từ bài
    'Thêm sự hài hước và dí dỏm vào các cuộc hội thoại.' bằng Jaccard."""
    line = "- Luôn thêm sự hài hước và dí dỏm vào các cuộc hội thoại."
    lesson = "Thêm sự hài hước và dí dỏm vào các cuộc hội thoại."
    # embedder not called (None result), but lexical match should allow it
    assert ev._bad_rule(line, [lesson]) is None


def test_grounding_rejects_unrelated_rule_without_lexical_match():
    """Luật bịa 'Hãy báo giá vàng mỗi sáng lúc 6 giờ.' không có từ vựng chung với 3 bài học
    không liên quan, nên bị reject."""
    line = "- Hãy báo giá vàng mỗi sáng lúc 6 giờ."
    lessons = [
        "Luôn thêm sự hài hước vào các cuộc hội thoại.",
        "Gọi agent điều khiển bằng control.",
        "Giữ giọng thân thiện và chân thành.",
    ]
    assert ev._bad_rule(line, lessons) == "không có bài học nào làm căn cứ"


def test_forbidden_keywords_only_protocol_tags():
    """Luật STYLE 'Hạn chế gợi ý khi ngài chưa yêu cầu.' KHÔNG bị chặn vì 'hạn chế'
    đã bị xoá khỏi danh sách từ cấm. Chỉ `<ask_user>`, `<action_run>`, `<offer_protocol>` bị chặn."""
    line = "- Hạn chế gợi ý khi ngài chưa yêu cầu."
    assert ev._bad_rule(line, ["Hạn chế gợi ý khi ngài chưa yêu cầu."]) is None


def test_forbidden_protocol_tags_still_blocked():
    """Luật chứa `<ask_user>` vẫn bị chặn."""
    line = "- Luôn dùng <ask_user> để hỏi người dùng."
    assert "<ask_user>" in ev._bad_rule(line, ["Dùng ask_user"])


def test_grounding_never_calls_the_embedder(monkeypatch):
    """_bad_rule() chỉ dùng chữ (trùng từ), không gọi embedder."""
    from engine.core.learning import LearningEngine

    def boom(*a, **k):
        raise RuntimeError("embedder must not be called")
    monkeypatch.setattr(LearningEngine, "_embed_text", staticmethod(boom))
    ev._bad_rule("Luôn thêm sự hài hước và dí dỏm.", ["Thêm sự hài hước và dí dỏm vào cuộc hội thoại."])
    ev._bad_rule("Hãy báo giá vàng.", ["Người dùng thích cơm tấm."])


def test_invented_style_rule_is_rejected_and_grounded_one_passes():
    """Regression B2: luật STYLE cũng phải có bài học làm căn cứ (không chỉ luật routing)."""
    sources = ["Thêm sự hài hước và dí dỏm vào các cuộc hội thoại.", "Người dùng thích cơm tấm, bò né."]
    assert ev._bad_rule("Hãy báo giá vàng mỗi sáng lúc 6 giờ.", sources) == "không có bài học nào làm căn cứ"
    assert ev._bad_rule("Luôn thêm sự hài hước và dí dỏm vào các cuộc hội thoại.", sources) is None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")


def test_evolution_log_keeps_only_cleaned_entries():
    """Evolution.md (2026-10-14): chỉ ghi mục đã gỡ/gộp để khôi phục; luật đang áp dụng đã nằm ở STYLE.md,
    vùng "Giao tiếp" cũ bị bỏ khi ghi lại."""
    saved = ev.EVOLUTION_LOG
    try:
        with tempfile.TemporaryDirectory() as tmp:
            ev.EVOLUTION_LOG = Path(tmp) / "Evolution.md"
            ev.EVOLUTION_LOG.write_text("# Log\n\n## Giao tiếp\n- Dùng emoji.\n\n## Đã dọn\n- [gỡ #1, trùng] A.\n",
                                        encoding="utf-8")
            ev._write_evolution_log(["- [gỡ #3, lỗi thời] Danh sách agent."])
            ev._write_evolution_log(["- [gộp #4 → #5] Cũ."])
            text = ev.EVOLUTION_LOG.read_text(encoding="utf-8")
    finally:
        ev.EVOLUTION_LOG = saved
    assert "Giao tiếp" not in text and "emoji" not in text
    assert "## Đã dọn" in text and "[gỡ #1, trùng] A." in text
    assert "Danh sách agent" in text and "[gộp #4 → #5]" in text

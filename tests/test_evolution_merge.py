import tempfile
from pathlib import Path

import engine.core.evolution as ev
from engine.core.evolution import _merge_rules

HEAD = '---\nversion: "1.0.0"\n---\n\n# Self Evolution Style Rules\n'
OLD = HEAD + "- a\n- b\n- c\n- d\n"


def test_same_bullets_is_noop():
    assert _merge_rules(HEAD + "- d\n- c\n- b\n- a\n", OLD) is None


def test_partial_block_merges_instead_of_clobbering():
    out = _merge_rules(HEAD + "- new\n", OLD)
    assert out is not None and "- new" in out and "- a" in out and "- d" in out


def test_new_rules_come_first_and_old_rules_are_kept():
    """Thiết kế hiện tại: luôn gộp (không còn "viết lại toàn bộ"), luật mới đứng trước, luật cũ giữ lại,
    kết quả không còn front matter version."""
    out = _merge_rules(HEAD + "- x\n- y\n- z\n", OLD)
    assert out == "# Self Evolution Style Rules\n- x\n- y\n- z\n- a\n- b\n- c\n- d\n"


def test_reworded_rule_replaces_the_old_wording_instead_of_duplicating():
    old = HEAD + "- Chỉ dùng xưng hô thưa ngài ở cuối đoạn hội thoại.\n"
    out = _merge_rules(HEAD + "- Chỉ sử dụng xưng hô thưa ngài ở cuối đoạn hội thoại.\n", old)
    assert out == "# Self Evolution Style Rules\n- Chỉ sử dụng xưng hô thưa ngài ở cuối đoạn hội thoại.\n"


def test_evolution_log_has_no_dates_and_only_new_rules():
    saved = ev.EVOLUTION_LOG
    try:
        with tempfile.TemporaryDirectory() as tmp:
            ev.EVOLUTION_LOG = Path(tmp) / "Evolution.md"
            ev._write_evolution_log(["- Chỉ dùng xưng hô thưa ngài ở cuối đoạn hội thoại."], ["- Luật hoàn toàn mới về emoji."])
            ev._write_evolution_log(["- Chỉ sử dụng xưng hô thưa ngài ở cuối đoạn hội thoại."], ["- Luật hoàn toàn mới về emoji.", "- Thêm luật khác nữa."])
            text = ev.EVOLUTION_LOG.read_text(encoding="utf-8")
    finally:
        ev.EVOLUTION_LOG = saved
    assert "## Routing" in text and "## Giao tiếp" in text
    assert text.count("thưa ngài") == 1 and text.count("emoji") == 1 and "Thêm luật khác" in text
    assert "20" not in text.split("-->")[1]  # no dates in the body


LESSON = "gọi agent điều khiển bằng control"


def test_similar_not_used_for_paraphrase_without_shared_words():
    """_similar() uses only difflib + Jaccard word overlap, not embedding.
    Two paraphrases with no shared words are correctly NOT similar (embedding removed)."""
    assert not ev._similar("Giữ giọng thân thiện", "Duy trì tông vui vẻ")


def test_similar_ignores_embedder_availability():
    """_similar() does not depend on embedder. Diff topics that embedder would have separated
    are now correctly NOT similar via text-only checks."""
    assert not ev._similar("luật về tin tức", "luật về giá cả")
    assert not ev._similar("luật về tin tức", "luật về vàng")


def test_control_before_other_agent_is_rejected_even_if_supported():
    line = "- Tìm giá → `@control agent_search`."
    assert ev._bad_rule(line, [LESSON], True) == "@control chỉ dành cho agent_control"


def test_control_with_agent_control_is_allowed():
    line = "- Dùng `@control` để gọi `agent_control`."
    assert ev._bad_rule(line, [LESSON], True) is None


def test_unknown_agent_is_rejected():
    assert "không tồn tại" in ev._bad_rule("- Gọi `agent_phone` khi cần.", [LESSON], True)


def test_rule_without_supporting_lesson_is_rejected():
    line = "- Gửi email, gọi điện, nhắn tin → `agent_weather`."
    assert ev._bad_rule(line, [LESSON], True) == "không có bài học nào làm căn cứ"


def test_supported_rule_passes_with_lexical_grounding():
    """Luật 'Dùng control để mở Windows Update.' có được hỗ trợ bằng Jaccard lexical
    từ bài 'gọi agent control để mở bất kỳ cửa sổ nào.'"""
    line = "- Dùng control để mở Windows Update."
    lesson = "gọi agent control để mở bất kỳ cửa sổ nào"
    # Shared tokens: control, để, mở (3 out of 6 in line = 0.5 >= 0.4)
    assert ev._bad_rule(line, [lesson], True) is None


def test_prepare_rules_keeps_only_grounded_bullets():
    """_prepare_rules filters out rules without lexical grounding (Jaccard >= 0.4).
    'Dùng control để mở Windows Update.' matches lesson (control, để, mở = 3/6=0.5).
    'Gửi email...' does not match any lesson (no shared tokens)."""
    lesson = "gọi agent control để mở bất kỳ cửa sổ nào"  # supports the first rule
    new = HEAD + "- Dùng control để mở Windows Update.\n- Gửi email, gọi điện, nhắn tin → `agent_email`.\n"
    out = ev._prepare_rules(new, HEAD, [lesson], True)
    assert out is not None and "Windows Update" in out and "gọi điện" not in out


# Task B2: Tests for lexical grounding (Jaccard) instead of cosine
def test_grounding_uses_lexical_jaccard_not_cosine():
    """Luật 'Luôn thêm sự hài hước và dí dỏm vào các cuộc hội thoại.' có căn cứ từ bài
    'Thêm sự hài hước và dí dỏm vào các cuộc hội thoại.' bằng Jaccard."""
    line = "- Luôn thêm sự hài hước và dí dỏm vào các cuộc hội thoại."
    lesson = "Thêm sự hài hước và dí dỏm vào các cuộc hội thoại."
    # embedder not called (None result), but lexical match should allow it
    assert ev._bad_rule(line, [lesson], True) is None


def test_grounding_rejects_unrelated_rule_without_lexical_match():
    """Luật bịa 'Hãy báo giá vàng mỗi sáng lúc 6 giờ.' không có từ vựng chung với 3 bài học
    không liên quan, nên bị reject."""
    line = "- Hãy báo giá vàng mỗi sáng lúc 6 giờ."
    lessons = [
        "Luôn thêm sự hài hước vào các cuộc hội thoại.",
        "Gọi agent điều khiển bằng control.",
        "Giữ giọng thân thiện và chân thành.",
    ]
    assert ev._bad_rule(line, lessons, True) == "không có bài học nào làm căn cứ"


def test_forbidden_keywords_only_protocol_tags():
    """Luật STYLE 'Hạn chế gợi ý khi ngài chưa yêu cầu.' KHÔNG bị chặn vì 'hạn chế'
    đã bị xoá khỏi danh sách từ cấm. Chỉ `<ask_user>`, `<action_run>`, `<offer_protocol>` bị chặn."""
    line = "- Hạn chế gợi ý khi ngài chưa yêu cầu."
    assert ev._bad_rule(line, ["Hạn chế gợi ý khi ngài chưa yêu cầu."], False) is None


def test_forbidden_protocol_tags_still_blocked():
    """Luật chứa `<ask_user>` vẫn bị chặn."""
    line = "- Luôn dùng <ask_user> để hỏi người dùng."
    assert "<ask_user>" in ev._bad_rule(line, ["Dùng ask_user"], False)


def test_similar_and_grounding_never_call_the_embedder(monkeypatch):
    """_similar() và _bad_rule() chỉ dùng chữ (difflib/trùng từ), không gọi embedder (e5-small không phân biệt chủ đề)."""
    from engine.core.learning import LearningEngine

    def boom(*a, **k):
        raise RuntimeError("embedder must not be called")
    monkeypatch.setattr(LearningEngine, "_embed_text", staticmethod(boom))
    assert not ev._similar("Luôn ghi nhớ", "Hãy báo giá vàng")
    assert ev._similar("Luôn ghi nhớ", "Luôn ghi nhớ")
    ev._bad_rule("Luôn thêm sự hài hước và dí dỏm.", ["Thêm sự hài hước và dí dỏm vào cuộc hội thoại."], False)
    ev._bad_rule("Hãy báo giá vàng.", ["Người dùng thích cơm tấm."], True)


def test_invented_style_rule_is_rejected_and_grounded_one_passes():
    """Regression B2: luật STYLE cũng phải có bài học làm căn cứ (không chỉ luật routing)."""
    sources = ["Thêm sự hài hước và dí dỏm vào các cuộc hội thoại.", "Người dùng thích cơm tấm, bò né."]
    assert ev._bad_rule("Hãy báo giá vàng mỗi sáng lúc 6 giờ.", sources, False) == "không có bài học nào làm căn cứ"
    assert ev._bad_rule("Luôn thêm sự hài hước và dí dỏm vào các cuộc hội thoại.", sources, False) is None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")

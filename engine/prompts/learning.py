"""Quản lý các prompt learning, evolution, dream, self-healing (spec 2026-09-25 mục 2)."""
from engine.prompts import load


def build_learning_propose_prompt(context: str, just_learned: str = "") -> str:
    """Xây dựng prompt đề xuất bài học tự phản tư vòng 1."""
    return load(
        "learning_propose",
        context=context,
        just_learned=just_learned or "(không có)",
    )


def build_learning_critique_prompt(proposal: str, existing_item: str = "") -> str:
    """Xây dựng prompt phản biện bài học vòng 2."""
    return load("learning_critique", proposal=proposal, existing_item=existing_item or "Không có mục nào tương tự.")


def build_evolution_prompt(
    pref_content: str,
    learning_content: str,
    current_routing_proposals: str,
    current_style: str,
) -> str:
    """Xây dựng prompt tự tiến hóa (self-evolution)."""
    return load(
        "evolution",
        pref_content=pref_content,
        learning_content=learning_content,
        current_routing_proposals=current_routing_proposals,
        current_style=current_style,
    )


def build_dream_message_prompt(transcript: str) -> str:
    """Dream: đánh giá một đoạn hội thoại cũ có đáng giữ không."""
    return load("dream_message", transcript=transcript).rstrip("\n")


def build_dream_wiki_prompt(title: str, content: str) -> str:
    """Dream: nén một ghi chú Obsidian cũ."""
    return load("dream_wiki", title=title, content=content).rstrip("\n")


def build_self_healing_prompt(project_file: str, err_snippet: str) -> str:
    """Phân loại lỗi từ log và viết entry cho Errors.md."""
    return load("self_healing", project_file=project_file, err_snippet=err_snippet).rstrip("\n")

"""Ngài từng sửa chọn tool (bảng corrections, spec 2026-10-13 §2): ví dụ cho vòng chọn tool; sửa ≥ 2 lần mà model vẫn
chọn đúng tool sai thì ép tool đúng. Ngưỡng đo bằng tests/live/probes/embed_probe.py (EmbeddingGemma 2)."""
import logging

from engine.core import learning

log = logging.getLogger("jarvis.turn")

EXAMPLE_SIM = 0.85
FORCE_SIM = 0.95   # cao hơn cặp khác tool cao nhất đo được: "giá iphone 16" ~ "tin tức iphone 16" = 0.934
FORCE_COUNT = 2
MAX_EXAMPLES = 3


def lookup(text: str) -> list[dict]:
    try:
        return learning.get_learning_engine().similar_corrections(text, EXAMPLE_SIM, MAX_EXAMPLES)
    except Exception as exc:  # embedder/DB lỗi: lượt vẫn chạy như chưa có corrections
        log.warning("[TURN] không tra được corrections: %s", exc)
        return []


def examples_block(fixes: list[dict]) -> str:
    if not fixes:
        return ""
    lines = [f'Ngài từng sửa: "{f["query"]}" → không dùng {f["wrong_tool"]}, dùng {f["right_tool"]}' for f in fixes]
    return "<vi_du>\n" + "\n".join(lines) + "\n</vi_du>"


def forced_tool(fixes: list[dict], chosen: str, names) -> dict | None:
    for f in fixes:
        if (f["wrong_tool"] == chosen and f["count"] >= FORCE_COUNT and f["sim"] >= FORCE_SIM
                and f["right_tool"] in names):
            return f
    return None

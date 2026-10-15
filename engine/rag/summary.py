"""Tổng hợp một tài liệu (2026-10-14): lưu vào kho xong hoặc hỏi "tóm tắt" tệp đính kèm → tài liệu nói về gì.
Đọc các đoạn rải đều cả tài liệu (truy hồi 5 đoạn theo câu hỏi bỏ sót phần lớn tài liệu); grammar JSON + think 128."""
import json
import logging

log = logging.getLogger("jarvis.rag.summary")

EXCERPT_CHARS = 6000
_SEP = "\n\n---\n\n"
_TEXT = {"type": "string", "minLength": 1}
SCHEMA = {"type": "object", "properties": {
    "chu_de": _TEXT, "tom_tat": _TEXT, "muc_chinh": {"type": "array", "minItems": 1, "maxItems": 6, "items": _TEXT}},
    "required": ["chu_de", "tom_tat", "muc_chinh"], "additionalProperties": False}


# Câu trả lời hỏi đáp tài liệu là chữ thường (không grammar); think 128 như mọi bước của model nhỏ
ANSWER_KW = {"thinking": True, "thinking_budget": 128, "temperature": 0.0}


def answer_messages(question: str, evidence: str, source: str) -> list[dict]:
    """Prompt hỏi đáp RAG dùng chung cho kho (@rag, search_documents) và tệp đính kèm (rag_ask)."""
    from engine.prompts import load
    return [{"role": "system", "content": load("rag_answer", source=source)},
            {"role": "user", "content": f"<nguon>\n{source}\n</nguon>\n\n<cau_hoi>\n{question}\n</cau_hoi>\n\n"
                                        f"<bang_chung>\n{evidence}\n</bang_chung>"}]


def excerpt(chunks: list[dict], budget: int = EXCERPT_CHARS) -> str:
    """Các đoạn theo thứ tự tài liệu, lấy rải đều đầu → cuối cho vừa `budget` ký tự."""
    texts = [str(c.get("content") or "").strip() for c in chunks]
    texts = [t for t in texts if t]
    if not texts:
        return ""
    if sum(len(t) for t in texts) + len(_SEP) * (len(texts) - 1) <= budget:
        return _SEP.join(texts)
    k = max(2, budget // (sum(len(t) for t in texts) // len(texts) + len(_SEP)))
    while k >= 1:
        idx = sorted({round(i * (len(texts) - 1) / max(k - 1, 1)) for i in range(k)})
        out = _SEP.join(texts[i] for i in idx)
        if len(out) <= budget:
            return out
        k -= 1
    return texts[0][:budget]


async def summarize(filename: str, chunks: list[dict]) -> str | None:
    """Markdown "**tệp**: chủ đề / tóm tắt / mục chính"; None khi không có đoạn hoặc model không trả JSON dùng được."""
    text = excerpt(chunks)
    if not text:
        return None
    from engine.prompts import load
    from engine.prompts.learning import json_format
    from engine.server import llm_server
    try:
        r = await llm_server.call_llm(
            messages=[{"role": "user", "content": load("rag_summary", filename=filename, excerpt=text)}],
            stream=False, temperature=0.0, thinking=True, thinking_budget=128, max_tokens=900,
            response_format=json_format("rag_summary", SCHEMA))
        data = json.loads((r.choices[0].message.content or "").strip())
        items = "\n".join(f"- {str(m).strip()}" for m in data["muc_chinh"] if str(m).strip())
        return f"**{filename}**: {data['chu_de'].strip()}\n\n{data['tom_tat'].strip()}" + (f"\n\n{items}" if items else "")
    except Exception as exc:
        log.warning("[RAG] tổng hợp %s lỗi: %s", filename, exc)
        return None

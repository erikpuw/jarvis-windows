# engine/turn/history.py
"""Lịch sử cho model (spec mục 3.3): dựng lại đúng định dạng giao kèo JSON để model chỉ thấy chính cách nó trả lời
(log 2026-10-12 03:20: chữ "[đã gọi …]" trong lịch sử làm Gemma chép chữ thay vì gọi tool)."""
import json

MAX_TURNS = 3
SHORT = 300
LAST = 3000  # lượt gần nhất (ngài 2026-10-13: hỏi tiếp "nói thêm bài 2" mà chỉ còn 300 ký tự → hết nội dung)


def step_record(say: str, tool: str, args: dict, result: str, outcome: str) -> dict:
    return {"say": say, "tool": tool, "args": dict(args or {}), "result": (result or "")[:LAST], "outcome": outcome}


def assistant_message(say: str, tool: str = "none", args: dict | None = None) -> dict:
    body = {"tool": tool, "say": say}
    if tool != "none":
        body["args"] = args or {}
    return {"role": "assistant", "content": json.dumps(body, ensure_ascii=False)}


def result_message(tool: str, text: str, outcome: str, displayed: bool, answer: str, limit: int) -> dict:
    # e2e 2026-10-12 18:34: dòng "(đã hiển thị cho ngài)" cuối kết quả bị chép nguyên văn cùng bảng → chỉ dẫn ở tiêu đề
    note = " — ngài đã thấy bảng này trên màn hình: chỉ nhận xét 1 đến 3 câu, không chép lại bảng" if displayed else ""
    content = f"[kết quả {tool} ({outcome}){note}]\n{(text or '')[:limit]}"
    if answer:
        content += f"\nLưu ý khi trả lời: {answer}"
    return {"role": "user", "content": content}


def for_model(conversation_history: list[dict], plain: bool = False) -> list[dict]:
    """plain = vòng trả lời bằng chữ thường: trợ lý là câu trả lời cuối, không JSON, không bước tool."""
    items = [m for m in (conversation_history or []) if m.get("role") in ("user", "assistant")]
    while items and items[-1]["role"] == "user":  # câu đang hỏi / câu chưa có trả lời: không phải lịch sử
        items.pop()
    out, turns, carry = [], 0, ""
    for m in reversed(items):
        limit = LAST if not out else SHORT  # out rỗng = câu trả lời của lượt gần nhất
        if m["role"] == "user":
            content = str(m.get("content") or "")
            out.append({"role": "user", "content": f"{content}\n\n{carry}" if carry else content})
            carry = ""
            turns += 1
            if turns >= MAX_TURNS:
                break
            continue
        steps = m.get("steps") if isinstance(m.get("steps"), list) else []
        if plain:  # câu trả lời cuối, không câu báo gọi tool (log 19:10: bị chép lại như vừa chạy tool)
            text = m.get("final_say") if steps and m.get("final_say") else m.get("content")
            out.append({"role": "assistant", "content": str(text or "")[:limit]})
            if limit == LAST and steps:  # kết quả tool lượt gần nhất đi kèm câu hỏi của lượt đó: vẫn xen kẽ vai
                carry = "\n".join(result_message(s["tool"], s.get("result", ""), s.get("outcome", ""), False, "",
                                                 LAST)["content"] for s in steps)
            continue
        block = []
        for s in steps:
            block += [assistant_message(s.get("say", ""), s["tool"], s.get("args")),
                      result_message(s["tool"], s.get("result", ""), s.get("outcome", ""), False, "", limit)]
        final = m.get("final_say") if steps else None
        block.append(assistant_message(str(final or m.get("content") or "")[:limit]))
        out.extend(reversed(block))
    out.reverse()
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out

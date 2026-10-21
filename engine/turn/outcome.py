"""Sau mỗi lượt có tool (spec 2026-10-13 mục 2-3): ghi một dòng outcomes; lượt thành công mà mọi tham số lấy từ
lời ngài thì lưu workflow để lần sau câu trùng nguyên văn được phát lại."""
from engine.core import learning
from engine.tools import registry


def status_of(steps: list[dict]) -> str:
    ok = [s.get("outcome") == "success" for s in steps]
    return "success" if all(ok) else "failed" if not any(ok) else "partial"


def _leaves(value):
    if isinstance(value, dict):
        for v in value.values():
            yield from _leaves(v)
    elif isinstance(value, list):
        for v in value:
            yield from _leaves(v)
    else:
        yield value


def from_user(tool: str, args: dict, text: str) -> bool:
    """Mọi tham số không-enum phải có trong câu ngài: ngày/số model tự suy ra mà phát lại hôm khác sẽ sai."""
    props = registry.parameters(tool).get("properties", {})
    q = learning.normalize_query(text)
    for key, value in (args or {}).items():
        if props.get(key, {}).get("enum"):
            continue
        for leaf in _leaves(value):
            if leaf is None or isinstance(leaf, bool):
                continue
            if isinstance(leaf, float) and leaf.is_integer():
                leaf = int(leaf)
            if learning.normalize_query(str(leaf)) not in q:
                return False
    return True


def save_turn(text: str, steps: list[dict], final_say: str, replay_id: int | None = None,
              workflow: bool = True) -> None:
    le = learning.get_learning_engine()
    status = status_of(steps)
    traces = []
    for s in steps:
        t = {"tool": s["tool"], "args": s.get("args", {}), "outcome": s.get("outcome", ""), "result": s.get("result", "")}
        if s.get("cua_steps"):
            t["cua_steps"] = s["cua_steps"]
        traces.append(t)
    if replay_id is not None:
        traces[0]["replay"] = replay_id
    le.record_outcome("+".join(s["tool"] for s in steps), text, status, (final_say or "")[:500], traces)
    if workflow and status == "success" and all(from_user(s["tool"], s.get("args", {}), text) for s in steps):
        chain = []
        for s in steps:
            c = {"tool": s["tool"], "args": s.get("args", {}), "say": s.get("say", "")}
            if s.get("cua_steps"):
                c["cua_steps"] = s["cua_steps"]
            chain.append(c)
        le.save_workflow(text, chain, (final_say or "")[:300])

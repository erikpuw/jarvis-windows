"""Ghi outcome thực thi; tạm dừng tự học và tăng xác nhận workflow."""
from engine.core import learning


def status_of(steps: list[dict]) -> str:
    ok = [s.get("outcome") == "success" for s in steps]
    return "success" if all(ok) else "failed" if not any(ok) else "partial"


def save_turn(text: str, steps: list[dict], final_say: str, replay_id: int | None = None,
              workflow: bool = True) -> None:
    # Giữ tham số workflow cho caller hiện có; tạm chặn học kể cả khi True.
    if not steps:
        return
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
    le.record_outcome("+".join(s["tool"] for s in steps), text, status,
                      (final_say or "")[:500], traces)

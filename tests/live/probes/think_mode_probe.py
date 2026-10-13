"""Live probe (chỉ gọi llama-server): vòng 1 production của engine.turn với thinking=False và thinking=True trên
held-out. Đo bằng client gốc (wrapper call_llm xoá reasoning_content): độ dài suy nghĩ, tool/tham số đúng, JSON hợp lệ,
thời gian, câu nói chat (để đọc độ tự nhiên).
Đo 2026-10-12: enable_thinking=False mà Gemma vẫn tự nghĩ ~300 delta với câu phê bình; bộ chặn _THINK_LIMIT=300 cắt mất.
Run: PYTHONIOENCODING=utf-8 python tests/live/probes/think_mode_probe.py [held_out|tuning] [temperature] [on|off] [budget]
"""
import asyncio, json, statistics, sys, time
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")

EXTRA_CHAT = [  # câu thật trong log 2026-10-12 15:45-15:49
    "chào Jarvis hôm nay bạn thế nào", "bạn có ổn không vậy", "sao thấy bạn trả lời không tự nhiên",
    "Cứ thấy bạn hoạt động sao đó vẫn cứng ngắt khô khan", "nói nhiều hơn đi chứ thấy câu trả lời nào cũng ngắn ngủi, sơ sài",
]


async def one(text, hist, thinking, temperature):
    from engine.server import llm_server as L
    from engine.tools import registry
    from engine.turn import loop, schema
    from engine.turn.say import parse_turn
    msgs = loop._messages(text, hist, None, [], registry.chat_names(None))
    client = L.get_llm_client()
    sp = L.sampling_params(thinking, temperature)
    t0 = time.time()
    r = await client.chat.completions.create(
        model=client.model, messages=msgs, temperature=sp["temperature"], top_p=sp["top_p"], max_tokens=3000,
        presence_penalty=sp["presence_penalty"], stream=False,
        extra_body={**sp["extra_body"], **L.reasoning_controls(thinking),
                    **({"thinking_budget_tokens": BUDGET} if thinking and BUDGET else {})},
        response_format=schema.response_format(schema.build(None)))
    m = r.choices[0].message
    think = (getattr(m, "model_extra", None) or {}).get("reasoning_content") or getattr(m, "reasoning_content", None) or ""
    content = m.content or ""
    try:
        json.loads(content)
        valid = True
    except ValueError:
        valid = False
    return parse_turn(content), len(think), valid, time.time() - t0, r.choices[0].finish_reason


async def main(name, temperature):
    items = json.loads((ROOT / f"tests/live/eval/{name}.json").read_text(encoding="utf-8"))
    items = [i for i in items if i["kind"] != "multi"] + [{"text": t, "history": [], "kind": "chat"} for t in EXTRA_CHAT]
    for thinking in MODES:
        c, lat, think_len, says = Counter(), [], [], []
        for it in items:
            d, tl, valid, sec, fin = await one(it["text"], it.get("history") or [], thinking, temperature)
            lat.append(sec); think_len.append(tl)
            c["valid"] += valid; c["tot"] += 1; c["thought"] += tl > 0
            kind, tool = it["kind"], d["tool"]
            if kind == "act":
                ok = tool == it["tool"]
                oka = ok and all(any(v in str(d["args"].get(k, "")).lower() for v in vals) for k, vals in it["args"].items())
                c["act_tot"] += 1; c["act_ok"] += ok; c["args_ok"] += oka
            else:
                ok = oka = tool == "none" or (kind == "know" and tool == "lookup_knowledge")
                c[kind + "_tot"] += 1; c[kind + "_ok"] += ok
            if not (ok and oka and valid):
                says.append(f"   SAI [{fin}, {tl} ký tự nghĩ, {sec:.1f}s] {it['text'][:45]!r} → {tool} {d['args']} say={d['say'][:60]!r}")
            if it["text"] in EXTRA_CHAT:
                says.append(f"   [{tl:4d} ký tự nghĩ, {sec:.1f}s] {it['text'][:40]!r} → {d['say'][:150]!r}")
        lat.sort()
        print(f"=== thinking={thinking} budget={BUDGET} temp={temperature} | JSON hợp lệ {c['valid']}/{c['tot']} | có nghĩ {c['thought']}/{c['tot']}"
              f" (median {statistics.median(think_len):.0f}, max {max(think_len)} ký tự) | tool {c['act_ok']}/{c['act_tot']}"
              f" | args {c['args_ok']}/{c['act_tot']} | chat {c['chat_ok']}/{c['chat_tot']} | kiến thức {c['know_ok']}/{c['know_tot']}"
              f" | median {lat[len(lat) // 2]:.1f}s, p90 {lat[int(len(lat) * .9)]:.1f}s")
        print("\n".join(says))


MODES = (False, True)
BUDGET = None  # token suy nghĩ tối đa mỗi lượt (thinking_budget_tokens theo request, đo 2026-10-12: 64 → ~250 ký tự)

if __name__ == "__main__":
    if len(sys.argv) > 3:
        MODES = (sys.argv[3] == "on",)
    if len(sys.argv) > 4:
        BUDGET = int(sys.argv[4])
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "held_out",
                     float(sys.argv[2]) if len(sys.argv) > 2 else 0.0))

"""Live probe CỔNG CHẶN (spec 2026-10-12 mục 2.3): vòng 1 production của engine.turn trên bộ held-out / tuning.
Ngưỡng held-out: tool ≥ 95%, tham số ≥ 93%, chat không gọi tool ≥ 96%, say có chữ khi gọi tool 100%,
say khi gọi tool không nói "đã xong" 100%, nhiều bước ≥ 5/6.
Run: PYTHONIOENCODING=utf-8 python tests/live/probes/turn_probe.py held_out|tuning
"""
import asyncio, json, re, sys, time
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")

DONE = re.compile(r"\bđã (mở|tắt|đóng|xong|kiểm tra|chụp|phát)\b|thành công", re.I)


async def main(name: str):
    from engine.turn import history, loop
    items = json.loads((ROOT / f"tests/live/eval/{name}.json").read_text(encoding="utf-8"))
    c, bad, lat = Counter(), [], []
    for it in items:
        if it["kind"] == "multi":
            msgs, got = [], []
            for _ in range(3):
                d = await loop.step(it["text"], it["history"], turn_msgs=msgs)
                if d["tool"] == "none":
                    break
                got.append(d["tool"])
                msgs += [history.assistant_message(d["say"], d["tool"], d["args"]),
                         history.result_message(d["tool"], "Thành công.", "success", False, "", 300)]
            c["multi_tot"] += 1
            c["multi_ok"] += got == it["multi"]
            if got != it["multi"]:
                bad.append(f"[multi] {it['text']!r}: {got}")
            continue
        t0 = time.time()
        d = await loop.step(it["text"], it["history"])
        if loop._off_target(d["tool"], it["text"]):  # cùng cổng chặn code như run_loop (ngài kể việc đang xem/theo dõi)
            d = {"tool": "none", "say": "", "args": {}}
        lat.append((time.time() - t0) * 1000)
        kind, tool = it["kind"], d["tool"]
        if kind == "chat":
            ok, oka = tool == "none", True
        elif kind == "know":
            ok, oka = tool in ("none", "lookup_knowledge"), True
        else:
            ok = tool == it["tool"]
            oka = ok and all(any(v in str(d["args"].get(k, "")).lower() for v in vals) for k, vals in it["args"].items())
            if tool != "none":
                c["say_tot"] += 1
                c["say_ok"] += bool(d["say"].strip())
                c["nodone_ok"] += not DONE.search(d["say"])
        c[kind + "_tot"] += 1
        c[kind + "_ok"] += ok
        if kind == "act":
            c["args_ok"] += oka
        if not (ok and oka):
            bad.append(f"{it['text']!r}: {tool} {d['args']} | say={d['say'][:70]!r}")
    pct = lambda a, b: c[a] / max(c[b], 1)
    lat.sort()
    print(f"[{name}] tool {c['act_ok']}/{c['act_tot']} | args {c['args_ok']}/{c['act_tot']} | "
          f"kiến thức {c['know_ok']}/{c['know_tot']} | chat {c['chat_ok']}/{c['chat_tot']} | "
          f"say {c['say_ok']}/{c['say_tot']} | không-nói-đã {c['nodone_ok']}/{c['say_tot']} | "
          f"nhiều bước {c['multi_ok']}/{c['multi_tot']} | median {lat[len(lat) // 2]:.0f}ms")
    for b in bad:
        print("   sai", b)
    passed = (pct("act_ok", "act_tot") >= .95 and pct("args_ok", "act_tot") >= .93 and pct("chat_ok", "chat_tot") >= .96
              and c["say_ok"] == c["say_tot"] and c["nodone_ok"] == c["say_tot"] and c["multi_ok"] >= 5)
    print("PASS" if passed else "FAIL")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "held_out"))

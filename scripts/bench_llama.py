"""Đo tốc độ llama-server đang chạy: prefill tok/s, gen tok/s, tỉ lệ nhận draft, VRAM.

    python scripts/bench_llama.py [--url http://127.0.0.1:8080] [--runs 3] [--label q4kv]
API key lấy từ biến môi trường LLAMA_API_KEY (không ghi vào file).
Đổi tham số server -> chạy lại với --label khác -> so sánh các dòng trong logs/bench_llama.jsonl.
"""
import argparse
import json
import os
import statistics
import subprocess
import time
import urllib.request

LONG_CTX = ("Nhật ký hệ thống: " + "dịch vụ khởi động, kiểm tra kết nối, ghi log thành công. " * 400)

CASES = {
    # tên: (messages, max_tokens, cache_prompt)
    "chat_ngan": ([{"role": "user", "content": "Chào bạn, hôm nay thời tiết Hà Nội thế nào?"}], 128, False),
    "sinh_dai": ([{"role": "user", "content": "Viết một bài giải thích chi tiết về cách hoạt động của bộ nhớ đệm KV trong mô hình transformer."}], 512, False),
    "json_router": ([{"role": "system", "content": "Chỉ trả về JSON dạng {\"agent\": str, \"task\": str, \"args\": object}."},
                     {"role": "user", "content": "Mở file báo cáo quý 3 trong Excel rồi tính tổng cột doanh thu."}], 256, False),
    "prefill_4k": ([{"role": "user", "content": LONG_CTX + "\nTóm tắt nhật ký trên trong một câu."}], 64, False),
}


def vram_mib():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout
        used, total = (int(x) for x in out.split(",")[:2])
        return used, total
    except Exception:
        return None, None


def call(url, key, messages, max_tokens, cache_prompt):
    body = json.dumps({"messages": messages, "max_tokens": max_tokens, "temperature": 0, "seed": 1,
                       "cache_prompt": cache_prompt, "stream": False}).encode()
    req = urllib.request.Request(url + "/v1/chat/completions", body, {"Content-Type": "application/json",
                                                                      "Authorization": f"Bearer {key}"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=600) as r:
        data = json.load(r)
    wall = time.perf_counter() - t0
    t = data.get("timings", {})
    return {
        "prompt_n": t.get("prompt_n"), "prefill_tps": t.get("prompt_per_second"),
        "gen_n": t.get("predicted_n"), "gen_tps": t.get("predicted_per_second"),
        "draft_n": t.get("draft_n"), "draft_ok": t.get("draft_n_accepted"), "wall_s": wall,
    }


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 1) if xs else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--label", default="hien_tai")
    a = ap.parse_args()
    key = os.environ.get("LLAMA_API_KEY", "")

    call(a.url, key, [{"role": "user", "content": "hi"}], 8, False)  # warmup
    peak = 0
    rows = []
    print(f"{'case':<12}{'prompt':>7}{'pp tok/s':>10}{'gen':>6}{'tg tok/s':>10}{'draft%':>8}{'wall s':>8}")
    for name, (msgs, mt, cp) in CASES.items():
        rs = []
        for _ in range(a.runs):
            rs.append(call(a.url, key, msgs, mt, cp))
            used, total = vram_mib()
            peak = max(peak, used or 0)
        dn, dok = sum(r["draft_n"] or 0 for r in rs), sum(r["draft_ok"] or 0 for r in rs)
        row = {"case": name, "prompt_n": rs[0]["prompt_n"], "prefill_tps": med(r["prefill_tps"] for r in rs),
               "gen_n": med(r["gen_n"] for r in rs), "gen_tps": med(r["gen_tps"] for r in rs),
               "draft_accept": round(100 * dok / dn, 1) if dn else None, "wall_s": med(r["wall_s"] for r in rs)}
        rows.append(row)
        print(f"{name:<12}{row['prompt_n'] or '-':>7}{row['prefill_tps'] or '-':>10}{row['gen_n'] or '-':>6}"
              f"{row['gen_tps'] or '-':>10}{row['draft_accept'] if row['draft_accept'] is not None else '-':>8}{row['wall_s']:>8}")
    _, total = vram_mib()
    print(f"VRAM đỉnh: {peak} / {total} MiB")

    os.makedirs("logs", exist_ok=True)
    with open("logs/bench_llama.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"label": a.label, "ts": time.strftime("%Y-%m-%d %H:%M"), "vram_peak": peak,
                            "rows": rows}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()

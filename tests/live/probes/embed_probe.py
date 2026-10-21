"""Đo embedder cho 2 việc của learning (2026-10-13): tra corrections ở vòng chọn tool, lọc bài học trùng.
So: đếm từ trùng (Jaccard) / embedding không tiền tố / embedding có tiền tố. Tiêu chí: AUC (1.0 = tách hoàn toàn
cặp cùng ý khỏi cặp khác ý), độ đúng ở ngưỡng tốt nhất, khoảng hở (min điểm cặp 1 − max điểm cặp 0, > 0 là tách sạch).
Run (embedder trong .env, e5 cần "query: "):
  PYTHONIOENCODING=utf-8 python tests/live/probes/embed_probe.py --prefix "query: "
  PYTHONIOENCODING=utf-8 python tests/live/probes/embed_probe.py --url http://127.0.0.1:8082/v1 --model embeddinggemma-2 \
      --prefix "task: sentence similarity | query: "
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")


def jaccard(a: str, b: str) -> float:
    wa, wb = (set(re.findall(r"\w+", s.lower())) for s in (a, b))
    return len(wa & wb) / max(len(wa | wb), 1)


def auc(scores, labels) -> float:
    pos = [s for s, y in zip(scores, labels) if y]
    neg = [s for s, y in zip(scores, labels) if not y]
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def best_acc(scores, labels) -> tuple[float, float]:
    best = (0.0, 0.0)
    for t in sorted(set(scores)):
        acc = sum((s >= t) == bool(y) for s, y in zip(scores, labels)) / len(labels)
        best = max(best, (acc, t))
    return best


def report(name, scores, labels, pairs, show_bad):
    pos = [s for s, y in zip(scores, labels) if y]
    neg = [s for s, y in zip(scores, labels) if not y]
    acc, thr = best_acc(scores, labels)
    print(f"  {name:22} AUC {auc(scores, labels):.2f} | đúng {acc:.0%} @ngưỡng {thr:.3f} | "
          f"khoảng hở {min(pos) - max(neg):+.3f} (cặp1 min {min(pos):.3f}, cặp0 max {max(neg):.3f})")
    if show_bad:
        for (a, b, y), s in zip(pairs, scores):
            if (s >= thr) != bool(y):
                print(f"      sai: [{y}] {s:.3f}  {a!r} ~ {b!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.getenv("LOCAL_EMBED_URL"))
    ap.add_argument("--model", default=os.getenv("LOCAL_EMBED_MODEL"))
    ap.add_argument("--key-env", default="LOCAL_EMBED_API", help="tên biến môi trường chứa API key (không in ra)")
    ap.add_argument("--prefix", default="", help='tiền tố cho mỗi câu, vd "query: " (e5)')
    ap.add_argument("--dims", type=int, default=0, help="cắt vector (MRL), 0 = giữ nguyên")
    args = ap.parse_args()
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv(args.key_env) or "none", base_url=args.url)
    data = json.loads((ROOT / "tests/live/eval/embed_pairs.json").read_text(encoding="utf-8"))
    cache: dict[str, np.ndarray] = {}

    def emb(text: str) -> np.ndarray:
        if text not in cache:
            v = np.array(client.embeddings.create(input=[text], model=args.model).data[0].embedding, dtype=np.float32)
            v = v[:args.dims] if args.dims else v
            cache[text] = v / np.linalg.norm(v)
        return cache[text]

    t0 = time.time()
    print(f"embedder {args.model} @ {args.url} | prefix {args.prefix!r}")
    for task, block in data.items():
        pairs = block["pairs"]
        labels = [p[2] for p in pairs]
        print(f"[{task}] {sum(labels)} cặp cùng ý / {len(labels) - sum(labels)} cặp khác ý")
        report("từ trùng (Jaccard)", [jaccard(a, b) for a, b, _ in pairs], labels, pairs, False)
        raw = [float(emb(a) @ emb(b)) for a, b, _ in pairs]
        report("embed không tiền tố", raw, labels, pairs, not args.prefix)
        if args.prefix:
            pre = [float(emb(args.prefix + a) @ emb(args.prefix + b)) for a, b, _ in pairs]
            report("embed có tiền tố", pre, labels, pairs, True)
    dim = len(next(iter(cache.values())))
    print(f"vector {dim}d | {len(cache)} lần nhúng, {(time.time() - t0) / len(cache) * 1000:.0f}ms/lần")


if __name__ == "__main__":
    main()

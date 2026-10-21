"""Đo truy xuất RAG trên kho thật (2026-10-17: nguồn sai tùm lum). Chỉ đọc index, không ghi gì.
top1 = đoạn đầu thuộc tệp đúng; top3 = có tệp đúng trong 3 đoạn đầu; rác = số đoạn khác tệp đúng mà _ask đưa
vào prompt và dòng "Nguồn"; nguồn sai = số tên tệp sai trong dòng "Nguồn".
Run: PYTHONIOENCODING=utf-8 python tests/live/probes/rag_probe.py [-v]
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
logging.disable(logging.CRITICAL)

from engine.core.rag_engine import get_rag_engine  # noqa: E402
from engine.rag.runner import retrieve_for_answer  # noqa: E402
from engine.server.llm_server import get_embed_client  # noqa: E402


async def main(verbose: bool):
    cases = json.loads((ROOT / "tests/live/eval/rag_retrieval.json").read_text(encoding="utf-8"))["cases"]
    rag = get_rag_engine()
    rag.embed_client = get_embed_client()
    top1 = top3 = junk = bad_src = 0
    for c in cases:
        chunks = await retrieve_for_answer(rag, c["q"])
        files = [ch.get("filename", "") for ch in chunks]
        ok1 = bool(files) and files[0] in c["files"]
        ok3 = any(f in c["files"] for f in files[:3])
        j = sum(f not in c["files"] for f in files)
        b = len({f for f in files if f not in c["files"]})
        top1 += ok1; top3 += ok3; junk += j; bad_src += b
        print(f"{'✓' if ok1 else ('~' if ok3 else '✗')} {c['q'][:40]:40s} giữ={len(files)} rác={j} nguồn_sai={b}")
        if verbose:
            for ch in chunks:
                print(f"      {ch.get('score', ch.get('hybrid_score', 0)):.3f} {ch.get('filename', '')[:28]:28s} "
                      f"| {' '.join(ch['content'].split())[:70]}")
    n = len(cases)
    print(f"\ntop1 {top1}/{n}  top3 {top3}/{n}  rác {junk}  nguồn_sai {bad_src}")


asyncio.run(main("-v" in sys.argv))

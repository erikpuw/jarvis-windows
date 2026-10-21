"""Live probe (chỉ gọi llama-server 127.0.0.1:8080, bỏ qua nếu server tắt): điều khiển reasoning đúng tài liệu llama.cpp.

4 tổ hợp thinking x stream qua engine.server.llm_server._call_llm_inner (đúng request JARVIS gửi):
- thinking=False: content sạch, KHÔNG có reasoning_content.
- thinking=True (không stream): content sạch VÀ reasoning_content > 0 (thinking thật sự bật, không lọt vào content).
- stream: content sạch (stream_wrapper chủ động bỏ delta.reasoning_content nên không đo được độ dài thought).
Thoát mã 1 nếu có tổ hợp sai.
Run: PYTHONIOENCODING=utf-8 python tests/live/probes/thinking_probe.py
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from engine.server import llm_server  # noqa: E402

QUESTION = "Một cửa hàng bán 12 quả cam giá 5000đ mỗi quả và 7 quả táo giá 8000đ mỗi quả. Tổng tiền là bao nhiêu?"
LEAK = ("<|channel>", "<channel|>", "Thinking Process")


async def run(thinking: bool, stream: bool) -> tuple[str, int]:
    response = await llm_server._call_llm_inner(
        [{"role": "system", "content": "Bạn là trợ lý, trả lời tiếng Việt ngắn gọn."}, {"role": "user", "content": QUESTION}],
        thinking=thinking, stream=stream, max_tokens=900,
    )
    if not stream:
        message = response.choices[0].message
        return message.content or "", len(getattr(message, "reasoning_content", None) or "")
    content = ""
    async for chunk in response:
        if chunk.choices and chunk.choices[0].delta.content:
            content += chunk.choices[0].delta.content
    return content, -1  # không đo được: stream_wrapper bỏ reasoning_content


async def main() -> int:
    bad = 0
    for thinking in (False, True):
        for stream in (False, True):
            name = f"thinking={thinking!s:5} stream={stream!s:5}"
            try:
                content, reasoning_len = await run(thinking, stream)
            except Exception as exc:  # server tắt: không tính là lỗi
                if any(w in str(exc) for w in ("Connection", "refused", "Timeout")):
                    print(f"{name} SKIP: server không trả lời")
                    return 0
                raise
            problems = []
            if any(w in content for w in LEAK):
                problems.append("thought lọt vào content")
            if not content.strip():
                problems.append("content rỗng")
            if not stream and thinking and reasoning_len <= 0:
                problems.append("thinking=True mà không có reasoning_content (thinking không bật?)")
            if not stream and not thinking and reasoning_len > 0:
                problems.append("thinking=False mà vẫn có reasoning_content")
            print(f"{name} | content[:60]={content[:60]!r} | reasoning_content={reasoning_len if reasoning_len >= 0 else 'n/a'} | "
                  f"{'FAIL: ' + '; '.join(problems) if problems else 'OK'}")
            bad += bool(problems)
    print("PASS" if not bad else f"FAIL ({bad}/4)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

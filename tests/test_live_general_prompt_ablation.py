"""LIVE ablation — real chat model, real production system prompt, NO production code touched.

Question: which block of the general-chat system prompt makes Jarvis (a) claim it is
doing/did a tool action it cannot do in chat mode, (b) leak agent names, (c) offer
tool actions. Each variant removes one block; everything else is identical.
Prompts are ones the REAL gate routes to "general" (checked live 2026-09-23).

Run: python tests/test_live_general_prompt_ablation.py
"""
import asyncio
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

PROMPTS = [
    "máy tôi chậm quá", "tôi mệt quá", "tôi muốn làm việc", "tôi đang buồn", "máy tính kêu to quá",
    "tôi quên lịch họp chiều nay rồi", "tôi muốn học tiếng Anh", "tôi hay quên uống nước",
    "giọng bạn nghe hay đó", "hôm nay tôi code bị bug hoài", "cảm ơn nhé", "tôi định cuối tuần đi Đà Lạt",
]

_VERB = r"(kiểm tra|mở|bật|chạy|tra|tìm|xem|quét|ghi|dọn|chụp|phát|đóng|tắt)"
CLAIM = re.compile(rf"(tôi|mình) (sẽ|đang|đã)( \w+)? {_VERB}|để tôi( \w+)? {_VERB}|đã ghi chú|đang bật", re.I)
LEAK = re.compile(r"\b(desktop|media|vision|webcam|search|notes|security|project|dream|win_control|goose|"
                  r"vietlott|history|legal|rag|office|agent)\b|công cụ", re.I)
RUNS = 2
# Self-awareness must survive the card rewrite: Jarvis still knows what it can do.
CAPABILITY_QUESTIONS = [
    "bạn làm được những gì?", "jarvis có mở được ứng dụng không?", "bạn có xem được email của tôi không?",
    "bạn tra thời tiết được không?",
]
OFFER = re.compile(rf"(muốn|cần|để) tôi[^.?!]{{0,40}}{_VERB}", re.I)


def _drop_block(prompt: str, tag: str) -> str:
    # Opening tag must start a line: identity.md/soul.md MENTION "<style_rules>"/"<capabilities>"
    # mid-sentence, and a naive match deleted everything from that mention onward.
    out = re.sub(rf"(?ms)^<{tag}>\n.*?^</{tag}>\s*", "", prompt)
    assert len(prompt) - len(out) < 3500, f"{tag}: removed too much"
    return out


def _drop_soul_rule1(prompt: str) -> str:
    return re.sub(r"1\. \*\*Hệ thống của bạn\.\*\*.*?\n(?=2\.)", "", prompt, flags=re.S)


def _variants(full: str) -> dict:
    return {
        "full": full,
        "-capabilities": _drop_block(full, "capabilities"),
        "-soul_rule1": _drop_soul_rule1(full),
        "-cap-rule1": _drop_soul_rule1(_drop_block(full, "capabilities")),
        "-preferences": _drop_block(full, "user_preferences"),
        "-style_rules": _drop_block(full, "style_rules"),
    }


async def main_async():
    from engine.prompts.chat import build_chat_messages, build_chat_system_prompt
    from engine.server.llm_server import call_llm
    full = build_chat_system_prompt()
    if "--full" in sys.argv:
        variants = {"full": full}
        for q in CAPABILITY_QUESTIONS:
            resp = await call_llm(messages=[{"role": "system", "content": full}, {"role": "user", "content": q}],
                                  stream=False, thinking=False)
            print(f"[CAP] {q}\n      {' '.join((resp.choices[0].message.content or '').split())[:400]}", flush=True)
    else:
        variants = _variants(full)
        assert variants["-capabilities"] != full and variants["-soul_rule1"] != full, "block removal did not apply"
    print("Prompt sizes (chars):", {k: len(v) for k, v in variants.items()})
    summary = {}
    for name, system in variants.items():
        counts = {"claim": 0, "leak": 0, "offer": 0}
        print("=" * 100 + f"\n{name}", flush=True)
        for p in PROMPTS * RUNS:
            # load_dynamic_context đã bị gỡ ở v9.9.5: dùng bố cục 5 khối của production
            # (history rỗng, không đụng DB), chỉ thay system prompt bằng biến thể đang đo.
            msgs = build_chat_messages(p, conversation_history=[], route="general")
            msgs[0] = {"role": "system", "content": system}
            # Production chat (server.py generate_response_stream) passes no temperature: same here.
            resp = await call_llm(messages=msgs, stream=False, thinking=False)
            reply = " ".join((resp.choices[0].message.content or "").split())
            hits = {k: rx.search(reply) for k, rx in (("claim", CLAIM), ("leak", LEAK), ("offer", OFFER))}
            for k, h in hits.items():
                counts[k] += bool(h)
            flags = " ".join(f"{k.upper()}[{h.group(0)}]" for k, h in hits.items() if h)
            print(f"  {p!r:36} {flags or '-'}", flush=True)
            if flags:
                print(f"      …{reply[-220:]}")
        summary[name] = counts
    print("=" * 100)
    print(f"{'variant':16} claim leak offer   (trên {len(PROMPTS) * RUNS} lượt)")
    for name, c in summary.items():
        print(f"{name:16} {c['claim']:5} {c['leak']:4} {c['offer']:5}")


def main():
    try:
        urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=2)
    except Exception:
        print("LLM server (127.0.0.1:8080) không chạy -- bỏ qua.")
        return
    asyncio.run(main_async())


if __name__ == "__main__":
    main()

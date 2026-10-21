"""Model chat và model vision phải đổi song song khi chuyển profile (qwen / gemma / bonsai).
Run: python tests/test_llm_profiles.py"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.server import llm_server

_KEYS = ("CHANG_MODEL", "BONSAI_MODEL", "LOCAL_MODEL", "LOCAL_GEMMA_MODEL", "LOCAL_BONSAI_MODEL", "VISION_MODEL")


def _with_env(**env):
    saved = {k: os.environ.get(k) for k in _KEYS}
    for k in _KEYS:
        os.environ.pop(k, None)
    os.environ.update(env)
    return saved


def _restore(saved):
    for k, v in saved.items():
        os.environ.pop(k, None)
        if v is not None:
            os.environ[k] = v


BASE = dict(LOCAL_MODEL="qwen-m", LOCAL_GEMMA_MODEL="gemma-m", LOCAL_BONSAI_MODEL="bonsai-m")


def test_vision_follows_active_model_when_unset():
    for flags, expected in (({}, "qwen-m"), ({"CHANG_MODEL": "true"}, "gemma-m"),
                            ({"CHANG_MODEL": "true", "BONSAI_MODEL": "true"}, "bonsai-m")):
        saved = _with_env(**BASE, **flags)
        try:
            assert llm_server.active_model_name() == expected
            assert llm_server.vision_model_name() == expected, flags
        finally:
            _restore(saved)


def test_vision_auto_and_explicit_override():
    saved = _with_env(**BASE, VISION_MODEL="auto")
    try:
        assert llm_server.vision_model_name() == "qwen-m"
        os.environ["VISION_MODEL"] = "fixed-v"
        assert llm_server.vision_model_name() == "fixed-v"
    finally:
        _restore(saved)


def test_vision_request_disables_thinking_for_every_profile():
    for flags in ({}, {"CHANG_MODEL": "true"}, {"BONSAI_MODEL": "true"}):
        saved = _with_env(**BASE, **flags)
        try:
            kw = llm_server.vision_request_kwargs()
            assert kw["extra_body"]["chat_template_kwargs"] == {"enable_thinking": False}, flags
        finally:
            _restore(saved)
    saved = _with_env(**BASE, CHANG_MODEL="true")
    try:
        assert llm_server.vision_request_kwargs()["presence_penalty"] == 0.0
    finally:
        _restore(saved)


def test_screen_uses_active_model_and_strips_think():
    import asyncio
    from engine.tools import screen

    seen = {}

    class _Msg:
        content = ""

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    class _Comp:
        async def create(self, **kw):
            seen.update(kw)
            return _Resp()

    class _Chat:
        completions = _Comp()

    class _Client:
        chat = _Chat()

    profiles = (
        ({}, "qwen-m", "<think>nghĩ thử</think>Có cửa sổ Chrome"),
        ({"CHANG_MODEL": "true"}, "gemma-m", "<|channel>thought nghĩ thử<channel|>Có cửa sổ Chrome"),
    )
    for flags, model, raw in profiles:
        _Msg.content = raw
        saved = _with_env(**BASE, **flags)
        try:
            out = asyncio.run(screen.analyze_screenshot("abc", llm_client=_Client(), stream=False))
        finally:
            _restore(saved)
        assert seen["model"] == model, (flags, seen["model"])
        assert seen["extra_body"]["chat_template_kwargs"] == {"enable_thinking": False}
        assert out == "Có cửa sổ Chrome", out
        # 2026-10-13: mô tả vision hiện nguyên văn (display) → không được chào/xưng "bạn" (e2e: xưng sai: bạn)
        assert screen.NO_ADDRESS in seen["messages"][0]["content"][1]["text"]


def test_strip_think_gemma_keeps_gt_characters():
    saved = _with_env(**BASE, CHANG_MODEL="true")
    try:
        out = llm_server.strip_think("Chuyển A -> B, x => y, > 5<|channel>thought" + chr(10) + "nghĩ<channel|> Xong")
    finally:
        _restore(saved)
    # strip_think xoá tag và lạt khoảng trắng thừa, giữ ký tự > thường
    assert out == "Chuyển A -> B, x => y, > 5 Xong", out


class _FakeCompletions:
    def __init__(self, seen):
        self.seen = seen

    async def create(self, **kw):
        self.seen.update(kw)
        from types import SimpleNamespace
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="general"))],
            usage=None,
        )


class _FakeClient:
    model = "test-model"

    def __init__(self, seen):
        self.chat = SimpleNamespace(completions=_FakeCompletions(seen))


def _call_params(monkeypatch, messages, thinking=False):
    import asyncio
    from types import SimpleNamespace
    seen = {}
    monkeypatch.setattr(llm_server, "get_llm_client", lambda: _FakeClient(seen))
    asyncio.run(llm_server._call_llm_inner(
        messages, thinking=thinking, stream=False, temperature=None))
    return seen


def test_adapter_params_match_legacy_matrix(monkeypatch):
    """Adapter parameters theo từng profile: temp/top_p/top_k/min_p/
    presence/max_tokens/enable_thinking/reasoning_format/reasoning_effort theo từng hãng.
    Gemma cập nhật: temp=1.0 (chuẩn Google), top_p=0.95, top_k=64, min_p=0.0."""
    msgs = [{"role": "user", "content": "hi"}]
    cases = [
        # (env flags, thinking, temp, top_p, top_k, min_p, presence, max_tok, enable_think, rep?)
        ({}, False, 0.7, 0.8, 20, 0.0, 1.5, 8192, False, 1.0),
        ({}, True, 1.0, 0.95, 20, 0.5, 1.5, 16384, True, 1.0),
        ({"BONSAI_MODEL": "true"}, True, 1.0, 0.95, 20, 0.0, 0.0, 16384, True, 1.0),
        ({"BONSAI_MODEL": "true"}, False, 0.7, 0.8, 20, 0.0, 1.5, 8192, False, 1.0),
        ({"CHANG_MODEL": "true"}, False, 1.0, 0.95, 64, 0.0, 0.0, 8192, False, None),
        ({"CHANG_MODEL": "true"}, True, 1.0, 0.95, 64, 0.0, 0.0, 16384, True, None),
    ]
    for flags, thinking, temp, top_p, top_k, min_p, presence, max_tok, enable, rep in cases:
        saved = _with_env(**BASE, **flags)
        try:
            seen = _call_params(monkeypatch, msgs, thinking=thinking)
        finally:
            _restore(saved)
        eb = seen["extra_body"]
        assert (seen["temperature"], seen["top_p"], seen["max_tokens"],
                seen["presence_penalty"]) == (temp, top_p, max_tok, presence), flags
        assert (eb["top_k"], eb["min_p"],
                eb["chat_template_kwargs"]) == (
            top_k, min_p, {"enable_thinking": enable}), flags
        # Kiểm tra reasoning_format (không kiểm tra reasoning_effort vì nó chỉ có khi thinking=False)
        assert eb.get("reasoning_format") == "deepseek", f"reasoning_format mismatch: {flags}"
        assert eb.get("repetition_penalty") == rep, flags


def test_adapter_system_merge_and_think_inject(monkeypatch):
    """Mọi model gộp system về một system turn ở đầu (Gemma 4 từ 2026-10-08); Gemma không chèn <|think|>
    (template Gemma tự bật thinking via enable_thinking=true)."""
    msgs = [{"role": "user", "content": "a"},
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "b"}]
    saved = _with_env(**BASE)
    try:
        seen = _call_params(monkeypatch, msgs)
    finally:
        _restore(saved)
    assert seen["messages"][0] == {"role": "system", "content": "SYS"}

    saved = _with_env(**BASE, CHANG_MODEL="true")
    try:
        seen = _call_params(monkeypatch, msgs)
        seen_think = _call_params(monkeypatch, [{"role": "user", "content": "a"}], thinking=True)
    finally:
        _restore(saved)
    # Gemma 4: một system turn duy nhất ở đầu (ai.google.dev, đo 2026-10-08)
    assert seen["messages"][0] == {"role": "system", "content": "SYS"}
    # Gemma không chèn <|think|> nữa - reasoning_format="deepseek" + enable_thinking=true xử lý
    assert not any(msg.get("content", "").startswith("<|think|>") for msg in seen_think["messages"]), \
        "Gemma should not inject <|think|>"


if __name__ == "__main__":
    test_vision_follows_active_model_when_unset()
    test_vision_auto_and_explicit_override()
    test_vision_request_disables_thinking_for_every_profile()
    test_screen_uses_active_model_and_strips_think()
    test_strip_think_gemma_keeps_gt_characters()
    print("ok")


def test_closing_stream_early_closes_the_server_connection(monkeypatch):
    """Log 2026-10-13 16:10: dừng đọc giữa chừng (kẹt lặp) mà không đóng kết nối thì llama-server vẫn sinh tới
    max_tokens, chiếm slot lượt sau."""
    import asyncio
    from types import SimpleNamespace
    closed = []

    class _Stream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="hết "))])

        async def close(self):
            closed.append(True)

    class _Completions:
        async def create(self, **kw):
            return _Stream()

    class _Client:
        model = "test-model"
        chat = SimpleNamespace(completions=_Completions())
    monkeypatch.setattr(llm_server, "get_llm_client", lambda: _Client())

    async def run():
        gen = await llm_server._call_llm_inner([{"role": "user", "content": "x"}], stream=True, temperature=0.0)
        async for _ in gen:
            break
        await gen.aclose()
    asyncio.run(run())
    assert closed == [True]

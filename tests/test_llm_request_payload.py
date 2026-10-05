"""Task A Test: kiểm tra request payload, reasoning controls, sampling params.
Run: python -m pytest tests/test_llm_request_payload.py -xvs"""
import os
import sys
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.server import llm_server


_KEYS = ("CHANG_MODEL", "BONSAI_MODEL", "LOCAL_MODEL", "LOCAL_GEMMA_MODEL", "LOCAL_BONSAI_MODEL")


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


class _FakeCompletions:
    def __init__(self, seen):
        self.seen = seen

    async def create(self, **kw):
        self.seen.update(kw)
        return SimpleNamespace(
            choices=[SimpleNamespace(
                delta=SimpleNamespace(content="response", reasoning_content=None),
                message=SimpleNamespace(content="response")
            )],
            usage=None,
        )


class _FakeClient:
    model = "test-model"

    def __init__(self, seen):
        self.chat = SimpleNamespace(completions=_FakeCompletions(seen))


async def _call_params(messages, thinking=False, temperature=None, monkeypatch=None):
    seen = {}

    def fake_get_client():
        return _FakeClient(seen)

    if monkeypatch:
        monkeypatch.setattr(llm_server, "get_llm_client", fake_get_client)
    else:
        # For non-pytest usage
        llm_server.get_llm_client = fake_get_client

    try:
        await llm_server._call_llm_inner(
            messages, thinking=thinking, stream=False, temperature=temperature
        )
    except Exception:
        pass  # Don't care about response, only params
    finally:
        if not monkeypatch:
            del llm_server.get_llm_client

    return seen


# ============================================================================
# Task A tests: A2 reasoning_controls, A3 sampling_params, A1 no think_inject
# ============================================================================

def test_a2_gemma_thinking_false_reasoning_controls(monkeypatch):
    """A2: reasoning_controls(False) → extra_body có reasoning_effort="none",
    reasoning_format="deepseek", enable_thinking=False, không có khoá "reasoning"."""
    saved = _with_env(**BASE, CHANG_MODEL="true")
    try:
        seen = asyncio.run(_call_params([{"role": "user", "content": "hi"}],
                                       thinking=False, monkeypatch=monkeypatch))
        eb = seen["extra_body"]

        # Không được có "reasoning" key (tham số cũ)
        assert "reasoning" not in eb, f"reasoning key should not exist, got {eb}"

        # chat_template_kwargs phải có enable_thinking: False
        assert eb["chat_template_kwargs"] == {"enable_thinking": False}

        # reasoning_effort phải là "none"
        assert eb["reasoning_effort"] == "none", f"Expected 'none', got {eb.get('reasoning_effort')}"

        # reasoning_format phải là "deepseek"
        assert eb["reasoning_format"] == "deepseek", f"Expected 'deepseek', got {eb.get('reasoning_format')}"
    finally:
        _restore(saved)


def test_a2_gemma_thinking_true_reasoning_controls(monkeypatch):
    """A2: reasoning_controls(True) → extra_body có enable_thinking=True,
    reasoning_format="deepseek", không có reasoning_effort."""
    saved = _with_env(**BASE, CHANG_MODEL="true")
    try:
        seen = asyncio.run(_call_params([{"role": "user", "content": "hi"}],
                                       thinking=True, monkeypatch=monkeypatch))
        eb = seen["extra_body"]

        # Không được có "reasoning" key
        assert "reasoning" not in eb, f"reasoning key should not exist, got {eb}"

        # enable_thinking phải là True
        assert eb["chat_template_kwargs"] == {"enable_thinking": True}

        # reasoning_effort không được tồn tại
        assert "reasoning_effort" not in eb, f"reasoning_effort should not exist when thinking=True, got {eb}"

        # reasoning_format phải là "deepseek"
        assert eb["reasoning_format"] == "deepseek"
    finally:
        _restore(saved)


def test_a3_gemma_sampling_params_default(monkeypatch):
    """A3: Gemma default (Số Google): temp_instruct=1.0, top_p_instruct=0.95, top_k=64, min_p=0.0."""
    saved = _with_env(**BASE, CHANG_MODEL="true")
    try:
        seen = asyncio.run(_call_params([{"role": "user", "content": "hi"}],
                                       thinking=False, monkeypatch=monkeypatch))

        assert seen["temperature"] == 1.0, f"Expected temp 1.0, got {seen['temperature']}"
        assert seen["top_p"] == 0.95, f"Expected top_p 0.95, got {seen['top_p']}"
        assert seen["extra_body"]["top_k"] == 64, f"Expected top_k 64, got {seen['extra_body']['top_k']}"
        assert seen["extra_body"]["min_p"] == 0.0, f"Expected min_p 0.0, got {seen['extra_body']['min_p']}"
    finally:
        _restore(saved)


def test_a3_temperature_explicit_override(monkeypatch):
    """A3: temperature=0.0 tường minh ⇒ params temperature==0.0 (không bị thay bằng mặc định)."""
    # Test with Gemma
    saved = _with_env(**BASE, CHANG_MODEL="true")
    try:
        seen = asyncio.run(_call_params([{"role": "user", "content": "hi"}],
                                       thinking=False, temperature=0.0, monkeypatch=monkeypatch))
        assert seen["temperature"] == 0.0, f"Expected temp 0.0, got {seen['temperature']}"
        assert seen["extra_body"]["top_k"] == 64  # Still from profile
    finally:
        _restore(saved)

    # Test with Qwen
    saved = _with_env(**BASE)
    try:
        seen = asyncio.run(_call_params([{"role": "user", "content": "hi"}],
                                       thinking=False, temperature=0.0, monkeypatch=monkeypatch))
        assert seen["temperature"] == 0.0
        assert seen["extra_body"]["top_k"] == 20  # Qwen top_k
    finally:
        _restore(saved)


def test_a1_no_think_inject_in_messages(monkeypatch):
    """A1: Không được chèn <|think|> vào messages (bỏ khối think_inject),
    và không có khoá think_inject trong profile."""
    saved = _with_env(**BASE, CHANG_MODEL="true")
    try:
        seen = asyncio.run(_call_params([{"role": "user", "content": "hi"}],
                                       thinking=True, monkeypatch=monkeypatch))

        # Không message nào được bắt đầu bằng <|think|>
        for msg in seen["messages"]:
            content = msg.get("content", "")
            if isinstance(content, str):
                assert not content.startswith("<|think|>"), \
                    f"Message should not start with <|think|>, got: {content[:50]}"

        # Khoá think_inject đã bị xoá hẳn khỏi profile (template tự thêm <|think|>)
        assert "think_inject" not in llm_server.active_model_profile()
    finally:
        _restore(saved)


def test_a5_vision_request_kwargs(monkeypatch):
    """A5 (part 5): vision_request_kwargs() phải khớp sampling_params(False) + reasoning_controls(False)."""
    saved = _with_env(**BASE, CHANG_MODEL="true")
    try:
        vkw = llm_server.vision_request_kwargs()

        # Phải có các key
        assert "temperature" in vkw
        assert "top_p" in vkw
        assert "presence_penalty" in vkw
        assert "extra_body" in vkw

        # extra_body phải có reasoning_format, reasoning_effort, enable_thinking
        eb = vkw["extra_body"]
        assert eb["reasoning_format"] == "deepseek"
        assert eb["reasoning_effort"] == "none"
        assert eb["chat_template_kwargs"]["enable_thinking"] == False

        # Vision/OCR đọc chữ trong ảnh nên phải tất định: temp 0 (đo thực tế: temp 1.0 làm Gemma E4B
        # đọc sai số/giờ hoặc trả rỗng) và không phạt lặp token (làm hỏng số/ký tự lặp trong văn bản gốc).
        # top_p/top_k/min_p vẫn lấy từ profile (không có tác dụng khi temp=0).
        assert vkw["temperature"] == 0.0
        assert vkw["presence_penalty"] == 0.0
        assert vkw["top_p"] == 0.95
        assert eb["top_k"] == 64
        assert eb["min_p"] == 0.0
    finally:
        _restore(saved)


def test_a4_strip_think_gemma_complete_tags(monkeypatch):
    """A4 (part 6a): strip_think trên Gemma với thẻ đóng đủ: bỏ khối thought, KHÔNG gộp khoảng trắng của phần còn lại."""
    saved = _with_env(**BASE, CHANG_MODEL="true")
    try:
        result = llm_server.strip_think("Hôm nay <|channel>thought\nNghĩ sâu sắc<channel|> tôi yêu Việt Nam")
        assert result == "Hôm nay  tôi yêu Việt Nam", f"Got: {result}"
    finally:
        _restore(saved)


def test_a4_strip_think_gemma_keeps_gt(monkeypatch):
    """A4 (part 6b): strip_think giữ ký tự > thông thường trong câu."""
    saved = _with_env(**BASE, CHANG_MODEL="true")
    try:
        result = llm_server.strip_think("Chuyển A -> B, x => y, > 5<|channel>thought" + chr(10) + "nghĩ<channel|> Xong")
        assert ">" in result and "=>" in result, f"Lost > or =>, got: {result}"
        assert "thought" not in result
        assert "Xong" in result
    finally:
        _restore(saved)


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])


def test_strip_think_keeps_markdown_newlines_and_tables():
    """Review Task A: strip_think chạy trên MỌI câu trả lời không-stream (agent, synthesizer, OCR);
    không được gộp khoảng trắng — bảng Markdown và xuống dòng phải còn nguyên."""
    for env in ({"CHANG_MODEL": "true"}, {}):
        saved = {k: os.environ.get(k) for k in ("CHANG_MODEL", "BONSAI_MODEL")}
        for k in saved:
            os.environ.pop(k, None)
        os.environ.update(env)
        try:
            text = "### Giá vàng\n\n| Loại | Giá |\n|---|---|\n| SJC | 80 |\n\nHết."
            assert llm_server.strip_think(text) == text, env
            assert llm_server.strip_think("<|channel>thought\nnghĩ<channel|>\nDòng 1\nDòng 2") == "Dòng 1\nDòng 2" if env else True
        finally:
            for k, v in saved.items():
                os.environ.pop(k, None)
                if v is not None:
                    os.environ[k] = v

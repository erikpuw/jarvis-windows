"""Prompt nằm ở prompt/*.md và code chạy thật đọc từ đó; golden files chốt nội dung được gửi."""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.orchestrator import classifier
from engine.prompts import router as router_prompts
from engine.router import gate
from engine.router.types import TurnContext
from engine.server import llm_server

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "golden"
ATT = SimpleNamespace(router_metadata=lambda: {"filename": "a.docx"})


def _golden(name: str) -> str:
    return (GOLDEN / name).read_text(encoding="utf-8")  # CRLF do autocrlf được đổi về LF, như prompts.load


def _gate_system(monkeypatch, attachment=None) -> str:
    seen = {}

    async def fake_inner(messages, *a, **k):
        seen["system"] = messages[0]["content"]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="general"))])

    monkeypatch.setattr(llm_server, "_call_llm_inner", fake_inner)
    monkeypatch.setattr(gate, "_routing_history", lambda t, f: [])
    monkeypatch.setattr(gate, "_corrections", lambda: [])
    monkeypatch.setattr(gate, "_read_pref_context", lambda: "")
    asyncio.run(gate.classify_bucket("x", TurnContext(ws=object(), send_json=None, attachment_context=attachment)))
    return seen["system"]


def test_gate_builder_is_byte_identical():
    assert router_prompts.build_gate_system_prompt(False) == _golden("gate_system.txt")
    assert router_prompts.build_gate_system_prompt(True) == _golden("gate_system_attachment.txt")


def test_gate_prompt_loads_all_route_skills_with_or_without_attachment():
    for has_attachment in (False, True):
        prompt = router_prompts.build_gate_system_prompt(has_attachment)
        for name in ("general", "general_knowledge", "orchestrator", "attachment_clarify"):
            skill_path = ROOT / "skills" / "router" / name / "SKILL.md"
            skill = skill_path.read_text(encoding="utf-8").strip()
            assert skill and skill in prompt, f"route skill not loaded: {name}"


def test_gate_runtime_prompt_matches_golden(monkeypatch):
    assert _gate_system(monkeypatch) == _golden("gate_system.txt")
    assert _gate_system(monkeypatch, ATT) == _golden("gate_system_attachment.txt")


def test_classifier_prompt_and_tools_byte_identical():
    assert router_prompts.build_classifier_system_prompt() == _golden("classifier_system.txt")
    tools = json.dumps(classifier._build_tools(), ensure_ascii=False, indent=1)
    assert tools == _golden("classifier_tools.json")


def test_offer_context_byte_identical():
    assert router_prompts.build_offer_context("mở Notepad", "open_app") == _golden("offer_context.txt")


def test_router_code_has_no_inline_prompt_text():
    gate_src = (ROOT / "engine/router/gate.py").read_text(encoding="utf-8")
    cls_src = (ROOT / "engine/orchestrator/classifier.py").read_text(encoding="utf-8")
    dispatch_src = (ROOT / "engine/router/dispatch.py").read_text(encoding="utf-8")
    assert "Phân loại yêu cầu HIỆN TẠI" not in gate_src
    assert "Chọn agent phù hợp" not in cls_src
    assert "- desktop:" not in cls_src  # tiêu chí agent chỉ nằm trong prompt/agents.md
    assert "Lượt trước Jarvis đã đề nghị" not in dispatch_src


def test_result_prompts_have_no_inline_text():
    actions_src = (ROOT / "engine/core/actions.py").read_text(encoding="utf-8")
    synth_src = (ROOT / "engine/orchestrator/synthesizer.py").read_text(encoding="utf-8")
    assert "Hãy dựa vào kết quả công cụ" not in actions_src
    assert "_TOOL_SUMMARY_MODULES" not in actions_src  # một bản duy nhất ở engine/prompts/results.py
    assert "QUY TẮC TỔNG HỢP" not in synth_src


def test_synthesizer_sends_the_md_prompt(monkeypatch):
    from engine.orchestrator import synthesizer
    from engine.prompts import results
    seen = {}

    async def fake(messages, **k):
        seen["system"] = messages[0]["content"]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok thưa ngài"))])

    monkeypatch.setattr(llm_server, "call_llm", fake)
    rs = [{"agent": "search", "query": "a", "status": "success", "result": "x"},
          {"agent": "search", "query": "b", "status": "success", "result": "y"}]
    asyncio.run(synthesizer.combine("hỏi", rs))
    assert seen["system"] == results.build_synthesis_prompt()


def test_background_prompts_byte_identical():
    from engine.prompts import learning as lp
    assert lp.build_dream_message_prompt("user: tôi tên Erik\nassistant: Chào ngài.") == _golden("dream_message.txt")
    assert lp.build_dream_wiki_prompt("Ghi chú A", "Nội dung ghi chú.") == _golden("dream_wiki.txt")
    assert lp.build_self_healing_prompt("engine/x.py", "Traceback: boom") == _golden("self_healing.txt")
    assert lp.build_learning_workflow_prompt(
        "mở notepad", "desktop", '["open_app"]', "Đã mở Notepad.",
        '[{"action_name": "open_app", "args": {"app_name": "notepad"}, "outcome": "success", "timestamp": 1000}]',
    ) == _golden("workflow_distill.txt")


def test_background_code_has_no_inline_prompt_text():
    dream_src = (ROOT / "engine/core/dream.py").read_text(encoding="utf-8")
    heal_src = (ROOT / "engine/core/self_healing.py").read_text(encoding="utf-8")
    learn_src = (ROOT / "engine/core/learning.py").read_text(encoding="utf-8")
    assert "Bạn là bộ nhớ 'Dream'" not in dream_src
    assert "You are a self-healing assistant" not in heal_src
    assert "Distil this completed Jarvis workflow" not in learn_src
    # Chưng cất fact vào bảng memories là code chết và trái spec (không ghi bản sao vào memories)
    assert "extract_semantic_memory_from_conversation" not in learn_src
    assert not (ROOT / "prompt/learning_fact.md").exists()
    assert not (ROOT / "prompt/history_summary.md").exists()  # summarize_history không gọi LLM


def test_prompt_modules_import_in_any_order():
    """catalog → orchestrator → classifier không được vòng lại catalog (probe live đã vỡ vì thứ tự import)."""
    import subprocess
    for first in ("engine.prompts.catalog", "engine.prompts.chat", "engine.orchestrator.classifier", "engine.router.gate"):
        r = subprocess.run([sys.executable, "-c", f"import {first}"], cwd=ROOT, capture_output=True, text=True)
        assert r.returncode == 0, f"import {first} first:\n{r.stderr[-800:]}"


def test_dead_context_manager_is_gone():
    """context_manager (nén/cắt tỉa ngữ cảnh cũ), budgeting và token_juice không còn ai gọi từ khi chat ghép
    5 khối (2026-09-25); cắt tỉa cũ còn cắt mất <offer_protocol>/<about_user> — gỡ hẳn để không ai nối lại."""
    assert not list((ROOT / "engine" / "context").glob("*.py"))  # __pycache__ cũ có thể còn, không import được
    assert not (ROOT / "engine" / "core" / "token_juice.py").exists()
    srcs = [p for p in (ROOT / "engine").rglob("*.py")] + [ROOT / "server.py"]
    for p in srcs:
        text = p.read_text(encoding="utf-8", errors="ignore")
        assert "from engine.context" not in text and "engine.core.token_juice" not in text, p

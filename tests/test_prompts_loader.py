import pytest
from engine import prompts
from engine.prompts import persona, router

# Gate/classifier giống từng ký tự bản cũ: xem tests/test_prompts_wired.py (so với tests/golden/).


def test_load_missing_placeholder_raises_key_error():
    with pytest.raises(KeyError):
        prompts.load("dream_wiki")


def test_fallback_prompt_loads_without_persona_placeholders():
    fallback = prompts.load("fallback", current_time="now")
    assert "JARVIS" in fallback
    assert "Không bịa" in fallback


def test_cache_mechanism():
    prompts.clear_cache()
    c1 = prompts.load("classifier")
    c2 = prompts.load("classifier")
    assert c1 is c2


def test_persona_methods():
    identity = persona.get_identity()
    assert "JARVIS" in identity
    soul = persona.get_soul()
    assert "<offer_protocol>" not in soul  # 2026-09-27: luật cứng không đẩy đề nghị (xem test_offer_prompt)
    user = persona.get_user_profile()
    assert len(user) > 0
    short_p = persona.short()
    assert "ngài erikpuw" in short_p
    full = persona.load_full_persona()
    assert set(full.keys()) == {"identity", "soul", "user"}


def test_results_prompts():
    from engine.prompts import results
    summary_prompt = results.build_tool_summary_prompt("weather_search")
    assert "ngài erikpuw" in summary_prompt
    assert "emoji" in summary_prompt

    synth_prompt = results.build_synthesis_prompt()
    assert "QUY TẮC TỔNG HỢP BẮT BUỘC" in synth_prompt

    turn_status = results.build_turn_status(action_declined=False, route="general_knowledge")
    assert "<turn_status>" in turn_status
    assert "<answer_policy>" in turn_status
    assert "<tool_status>" not in turn_status  # nhánh tra cứu có dữ liệu Wikipedia (2026-09-26)


def test_learning_prompts():
    from engine.prompts import learning
    propose = learning.build_learning_propose_prompt(context="user: mệt quá", agent_outcomes="")
    assert "mệt quá" in propose

    critique = learning.build_learning_critique_prompt(proposal="learn X", existing_item="item Y")
    assert "learn X" in critique
    assert "item Y" in critique


def test_prompt_loader_compatibility():
    # engine/core/prompt_loader.py đã xoá (2026-09-28, code chết); prompt thật là build_chat_system_prompt.
    from engine.prompts.chat import build_chat_system_prompt
    sys_prompt = build_chat_system_prompt()
    assert "<identity>" in sys_prompt
    assert "<capabilities>" in sys_prompt
    assert "<offer_protocol>" in sys_prompt

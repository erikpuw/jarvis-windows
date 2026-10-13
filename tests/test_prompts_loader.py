import pytest
from engine import prompts

# Gate/classifier giống từng ký tự bản cũ: xem tests/test_prompts_wired.py (so với tests/golden/).


def test_load_missing_placeholder_raises_key_error():
    with pytest.raises(KeyError):
        prompts.load("dream_wiki")


def test_cache_mechanism():
    prompts.clear_cache()
    c1 = prompts.load("voice_cues")
    c2 = prompts.load("voice_cues")
    assert c1 is c2


def test_learning_prompts():
    from engine.prompts import learning
    propose = learning.build_learning_propose_prompt(context="user: mệt quá")
    assert "mệt quá" in propose

    critique = learning.build_learning_critique_prompt(proposal="learn X", existing_item="item Y")
    assert "learn X" in critique
    assert "item Y" in critique



import asyncio
import tempfile
import types
from pathlib import Path

import engine.core.evolution as ev

RESPONSE = """DECISION_JSON:
{"need_evolution": true, "reason": "test"}

ROUTING_RULES:
---
name: self_evolution
version: "5.4.0"
---

# Self Evolution Routing Rules
- Dùng control để gọi agent_control.
- Gửi email, gọi điện, nhắn tin → `@control agent_email`.
- Gửi email, gọi điện, nhắn tin.

STYLE_RULES:
---
name: self_evolution_style
version: "1.0.0"
---

# Self Evolution Style Rules
- Giữ giọng thân thiện hài hước.
"""

EMOJI = "🤵✨😊"

RESPONSE_WITH_EMOJI = f"""DECISION_JSON:
{{"need_evolution": true, "reason": "test"}}

ROUTING_RULES:
---
name: self_evolution
version: "5.4.0"
---

# Self Evolution Routing Rules
- Dùng control để gọi agent_control. {EMOJI}

STYLE_RULES:
---
name: self_evolution_style
version: "1.0.0"
---

# Self Evolution Style Rules
- Giữ giọng thân thiện hài hước. {EMOJI}
"""


def _isolate(root: Path):
    """Point evolution.py at a throwaway project root: STYLE_FILE/EVOLUTION_LOG only,
    no SKILL_FILE anymore — routing proposals live entirely inside Evolution.md."""
    system = root / "data" / "wiki" / "System"
    system.mkdir(parents=True)
    saved = (ev.PROJECT_ROOT, ev.STYLE_FILE, ev.EVOLUTION_LOG, ev.call_llm, ev._last_inputs)
    ev.PROJECT_ROOT = root
    ev.STYLE_FILE = root / "skills" / "self_evolution" / "STYLE.md"
    ev.EVOLUTION_LOG = system / "Evolution.md"
    return system, saved


def _restore(saved):
    ev.PROJECT_ROOT, ev.STYLE_FILE, ev.EVOLUTION_LOG, ev.call_llm, ev._last_inputs = saved


def test_full_run_drops_invented_rules_and_skips_unchanged_inputs():
    with tempfile.TemporaryDirectory() as tmp:
        system, saved = _isolate(Path(tmp))
        (system / "Learning.md").write_text("- [`k`] gọi agent điều khiển bằng control\n", encoding="utf-8")
        (system / "Preferences.md").write_text("- [`p`] giữ giọng thân thiện hài hước\n", encoding="utf-8")

        calls = []

        async def fake_llm(**kwargs):
            calls.append(1)
            msg = types.SimpleNamespace(content=RESPONSE)
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])

        try:
            ev.call_llm, ev._last_inputs = fake_llm, None

            first = asyncio.run(ev._run_cognitive_evolution())
            style = ev.STYLE_FILE.read_text(encoding="utf-8")
            assert first["success"]
            # Nhóm hài hước/thân thiện được gộp thành một luật chuẩn (_deduplicate_style_bullets)
            assert "hài hước" in style and style.count("hài hước") == 1
            assert not ev.STYLE_FILE.with_suffix(".md.bak").exists(), "Không được sinh ra file .bak"
            log_text = ev.EVOLUTION_LOG.read_text(encoding="utf-8")
            # Routing proposals land in Evolution.md, never in a live-consumed file.
            assert "## Routing" in log_text and "agent_control" in log_text
            assert "## Giao tiếp" in log_text and "gọi điện" not in log_text
            assert "agent_email" not in log_text

            second = asyncio.run(ev._run_cognitive_evolution())
            assert second["success"] and len(calls) == 1
        finally:
            _restore(saved)


def test_emoji_stripped_from_style_and_log():
    with tempfile.TemporaryDirectory() as tmp:
        system, saved = _isolate(Path(tmp))
        (system / "Learning.md").write_text("- [`k`] gọi agent điều khiển bằng control\n", encoding="utf-8")
        (system / "Preferences.md").write_text("- [`p`] giữ giọng thân thiện hài hước\n", encoding="utf-8")

        async def fake_llm(**kwargs):
            msg = types.SimpleNamespace(content=RESPONSE_WITH_EMOJI)
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])

        try:
            ev.call_llm, ev._last_inputs = fake_llm, None

            result = asyncio.run(ev._run_cognitive_evolution())
            assert result["success"]
            style = ev.STYLE_FILE.read_text(encoding="utf-8")
            log_text = ev.EVOLUTION_LOG.read_text(encoding="utf-8")
            assert EMOJI not in style, style
            assert EMOJI not in log_text, log_text
            assert "hài hước" in style and "agent_control" in log_text
        finally:
            _restore(saved)


if __name__ == "__main__":
    test_full_run_drops_invented_rules_and_skips_unchanged_inputs()
    test_emoji_stripped_from_style_and_log()
    print("ok")

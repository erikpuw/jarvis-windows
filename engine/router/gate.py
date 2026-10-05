"""Gate LLM: chat hay cần làm việc (spec §4 bước 6). Chỉ khái niệm, không biết agent (spec 2026-09-21)."""
import asyncio
import json
import logging
import re
from pathlib import Path

from engine.router.types import BUCKETS, TurnContext

log = logging.getLogger("jarvis.router.gate")
_PREF_PATH = Path(__file__).resolve().parents[2] / "data" / "wiki" / "System" / "Preferences.md"


def _read_pref_context() -> str:
    """Đọc sở thích định tuyến từ Obsidian Wiki. Đồng bộ, chặn I/O — gọi qua
    asyncio.to_thread từ route_to_agent_semantic, không tự cache vì nội dung
    được Learning cập nhật liên tục."""
    pref_path = _PREF_PATH
    if not pref_path.exists():
        return ""
    pref_text = pref_path.read_text(encoding="utf-8").strip()
    if not pref_text:
        return ""
    # Chỉ nhặt các sở thích liên quan đến phân biệt tool/hội thoại
    routing_prefs = [
        line.strip() for line in pref_text.splitlines()
        if line.strip().startswith("- ") and any(
            k in line.lower() for k in ["công cụ", "tool", "phân biệt", "định tuyến", "agent"]
        )
    ]
    if not routing_prefs:
        return ""
    return "User Routing Preferences:\n" + "\n".join(routing_prefs[:3]) + "\n\n"


def _routing_history(clean_text: str, fallback: list) -> list:
    try:  # nguyên văn route_agents.py:123-132
        from engine.core.memory import build_unified_routing_history
        return build_unified_routing_history(current_text=clean_text, fallback_history=fallback or [], limit=12)
    except Exception as history_err:
        log.warning("[ROUTER] Unified history fallback failed: %s", history_err)
        return list(fallback or [])[-12:]


def _corrections() -> list:
    from engine.core.learning import get_learning_engine
    return get_learning_engine().get_active_routing_corrections(limit=8)


def _history_context(routing_history: list, pending_ask: str = "") -> str:
    history_context = ""
    if routing_history:
        recent = routing_history[-4:]
        # build_unified_routing_history always ends with the CURRENT user utterance
        # (spec §6), so the pending <ask_user> belongs to the most recent assistant
        # turn in the window, not necessarily the last entry.
        last_assistant_idx = max(
            (i for i, m in enumerate(recent) if m.get("role") == "assistant"), default=-1
        )
        recent_msgs = []
        for i, m in enumerate(recent):
            content = " ".join((m.get("content") or "").split())  # one line per turn
            role = m.get("role", "")
            if not content:
                continue
            if role == "assistant":
                if i == last_assistant_idx and pending_ask:
                    # Spec §6: câu hỏi <ask_user> dở dang phải hiện đủ, không cắt 80 ký tự,
                    # để gate biết lượt sau "ừ/không" đang trả lời cho việc gì.
                    content = f"{content[:80]}... (Jarvis vừa hỏi: {pending_ask})"
                elif len(content) > 100:
                    content = content[:80] + "..."
            else:
                if len(content) > 200:
                    content = content[:200] + "..."
            recent_msgs.append(f"- {role}: {content}")

        if recent_msgs:
            history_context = "Recent User Intent History:\n" + "\n".join(recent_msgs) + "\n\n"
    return history_context


def _correction_context(corrections: list) -> str:
    # Phòng thủ sâu: bỏ correction có expected_route lạ (dòng cũ ghi trước
    # khi learning.py validate whitelist). Gate chỉ hiểu 3 bucket.
    corrections = [
        item for item in corrections
        if isinstance(item, dict)
        and item.get("expected_route") in ("general", "general_knowledge", "orchestrator")
        and item.get("user_query")
    ]
    correction_context = ""
    if corrections:
        lines = [
            "- Treat this prior user utterance as "
            f"{item['expected_route']}, not {item['selected_route']}: "
            f"\"{item['user_query'][:240]}\". "
            f"Correction: {item['correction_text'][:240]}"
            for item in corrections
        ]
        correction_context = (
            "\nVerified routing corrections from the user:\n"
            + "\n".join(lines)
            + "\n"
        )
    return correction_context


async def classify_bucket(clean_text: str, ctx: TurnContext) -> str:
    attachment_context = ctx.attachment_context
    routing_history = await asyncio.to_thread(_routing_history, clean_text, ctx.conversation_history)
    try:
        from engine.core import memory
        pending_ask = await asyncio.to_thread(memory.get_pending_ask)
    except Exception as pending_err:
        log.warning("[ROUTER] get_pending_ask failed: %s", pending_err)
        pending_ask = ""
    history_context = _history_context(routing_history, pending_ask)
    try:
        pref_context = await asyncio.to_thread(_read_pref_context)
    except Exception as pref_err:
        log.warning("[ROUTER] Failed to read Preferences.md for router: %s", pref_err)
        pref_context = ""
    try:
        corrections = await asyncio.to_thread(_corrections)
    except Exception as correction_err:
        log.warning("[ROUTER] Routing corrections unavailable: %s", correction_err)
        corrections = []
    correction_context = _correction_context(corrections)
    try:
        attachment_prompt = ""
        if attachment_context is not None:
            attachment_prompt = (
                "Trusted attachment metadata (the server owns the path):\n"
                f"{json.dumps(attachment_context.router_metadata(), ensure_ascii=False)}\n\n"
            )
        has_att = attachment_context is not None
        buckets = list(BUCKETS[:3]) + (["attachment_clarify"] if has_att else [])
        # Concept-only on purpose (spec 2026-09-21): the gate decides chat vs tool, it does not
        # know agents. No agent list, no example sentences: they bloated this prompt and
        # made the model keyword-match. Which agent runs is the orchestrator's job.
        from engine.prompts.router import build_gate_system_prompt
        system_prompt = build_gate_system_prompt(has_att)
        # Context that only changes when Learning/Evolution rewrite it belongs in
        # the system message, so llama.cpp can reuse its KV cache across turns.
        # It used to follow the per-turn user request, which put it after the
        # first varying token and forced it to be re-evaluated on every call.
        # Evolution's routing output is not injected here: it names agents, which the gate
        # must not know (spec 2026-09-21; measured, injecting them cost 7 of 53 correct
        # routes). Evolution no longer even writes a live routing file (2026-09-22) — its
        # routing output is a proposal in data/wiki/System/Evolution.md for a human to
        # review and fold into prompt/router_gate.md or prompt/agents.md by hand.
        static_context = f"{pref_context}{correction_context}"
        if static_context:
            system_prompt += "\n" + static_context
        user_prompt = (
            f"User request: \"{clean_text}\"\n\n"
            f"{attachment_prompt}"
            f"{history_context}"
            "Bucket:"
        )

        from engine.server.llm_server import call_llm, strip_think
        log.info("[ROUTER] Context source=unified_db history=%d corrections=%d", len(routing_history), len(corrections))
        async with ctx.flow_tracker.step("LLM router..."):
            response = await call_llm(
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                stream=False, thinking=False, temperature=0.0,
            )
        route = strip_think(response.choices[0].message.content or "").lower() if response and getattr(response, "choices", None) else "general"
        found = re.search(r"\b(general_knowledge|orchestrator|attachment_clarify|general)\b", route)
        route = found.group(1) if found else route.replace("`", "").replace("'", "").replace('"', "").strip()
        if route in buckets:
            log.info("[ROUTER] Route source=llm_router route=%s", route)
            return route
        log.warning("[ROUTER] LLM returned invalid route '%s', fallback to 'general'", route)
    except Exception as e:
        log.error("[ROUTER] LLM classification failed: %s, fallback to 'general'", e)
    return "general"

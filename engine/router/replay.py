"""Tái dùng workflow đã học: khớp nguyên văn câu user, chạy lại tool_chain, không qua LLM định tuyến (spec §4 bước 5)."""
import asyncio
import logging
import time

from engine.router.types import RouteDecision, TurnContext

log = logging.getLogger("jarvis.router.replay")

_ATTACHMENT_ONLY = {"office", "rag"}                           # chỉ có nghĩa khi có tệp đính kèm
_LEGACY_NAMES = {"check_project": "project", "learning": "history"}  # tên agent cũ trong DB


def _learning():
    from engine.core.learning import get_learning_engine
    return get_learning_engine()


async def find_replay(clean_text: str, attachment_context) -> dict | None:
    if attachment_context is not None:
        return None
    try:
        # SQLite đồng bộ: qua to_thread để không đóng băng event loop (WebSocket giọng nói).
        cands = await asyncio.to_thread(_learning().get_exact_workflow_candidates, clean_text)
    except Exception as exc:
        log.warning("[ROUTER] Failed to load exact learned workflows: %s", exc)
        return None
    dropped = [c for c in cands if c.get("agent") in _ATTACHMENT_ONLY]
    if dropped:
        log.info("[ROUTER] Ignoring %d office/rag workflow(s) without attachment", len(dropped))
    cands = [c for c in cands if c.get("agent") not in _ATTACHMENT_ONLY]
    if len(cands) != 1:
        if len(cands) > 1:
            log.warning("[ROUTER] Exact learned workflow is ambiguous for '%s'", clean_text[:80])
        return None
    c = cands[0]
    chain = c.get("tool_chain")
    if not (isinstance(chain, list) and chain and all(isinstance(t, str) for t in chain)):
        log.warning("[ROUTER] Invalid learned workflow tool chain id=%s", c.get("id"))
        return None
    agent = _LEGACY_NAMES.get(c["agent"], c["agent"])
    if agent == "search":  # agent search cũ đã tách: mỗi tool một agent (2026-10-03)
        from engine.prompts import catalog
        agent = catalog.tool_to_agent_map().get(chain[0], agent)
    from engine.prompts import catalog
    owners = catalog.tool_to_agent_map()
    if any(owners.get(t, agent) != agent for t in chain):  # workflow cũ gộp tool của agent đã tách (security/system)
        log.info("[ROUTER] Ignoring workflow id=%s: tools %s do not all belong to agent %s", c["id"], chain, agent)
        return None
    return {"id": c["id"], "agent": agent, "tool_chain": chain}


async def run_replay(decision: RouteDecision, ctx: TurnContext) -> str:
    """Nguyên văn route_agents.py:545-570."""
    wf = decision.workflow
    await ctx.send_json(ctx.ws, {"type": "status", "state": "working"})
    from engine.core.actions import handle_user_intent_with_tools
    from engine.orchestrator import dispatcher
    log.info("[ROUTER] Reusing workflow id=%s tools=%s", wf["id"], wf["tool_chain"])
    started_at = int(time.time() * 1000)
    res_text = await handle_user_intent_with_tools(
        user_text=decision.query,
        add_tools=wf["tool_chain"],
        conversation_history=list(ctx.conversation_history),
        ws=ctx.ws,
        agent_name=f"Learned workflow {wf['id']}",
        flow_tracker=ctx.flow_tracker,
        flow_agents=ctx.flow_agents,
    )
    ended_at = int(time.time() * 1000)
    outcome_id, status = dispatcher.record_outcome(wf["agent"], decision.query, res_text, started_at, ended_at)
    setattr(ctx.ws, "last_agent_outcome_id", outcome_id)
    setattr(ctx.ws, "last_agent_outcome_status", status)
    setattr(ctx.ws, "last_agent_outcome_at", time.time())
    return res_text


def recent_outcomes_context(limit: int = 3) -> str:
    """Nguyên văn route_agents.get_session_tool_context (dùng bởi memory.build_memory_context, history_engine)."""
    try:
        outcomes = _learning().get_recent_agent_outcomes(limit=limit)
    except Exception as exc:
        log.warning("[ROUTER] Recent outcomes unavailable: %s", exc)
        return ""
    if not outcomes:
        return ""
    lines = [f"- [{o['agent']}] User: \"{o['query'][:200]}\" → status={o['status']}" for o in reversed(outcomes)]
    return "RECENT VERIFIED AGENT OUTCOMES:\n" + "\n".join(lines)

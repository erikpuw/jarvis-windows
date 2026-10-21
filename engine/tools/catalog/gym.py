"""Tool gym (spec 2026-10-12 mục 4). Tham số lấy từ commands/gym_manage.md cũ."""
import asyncio
from typing import Literal

from engine.tools.registry import tool

_Action = Literal["list_profiles", "create_profile", "select_profile", "search_exercises", "log_workout",
                  "record_bodyweight", "history", "stats", "nutrition_guide", "log_habit", "habit_summary"]


@tool(kind="change")
async def gym(action: _Action, profile_id: str = "", name: str = "", query: str = "", trained_on: str = "",
              exercises: list = None, measured_on: str = "", weight_kg: float = None, goal: str = "",
              habit: str = "", done: bool = None, day: str = "", note: str = "", days: int = None,
              limit: int = None) -> str:
    from engine.tools.gym_engine import run_gym_tool
    given = {"action": action, "profile_id": profile_id, "name": name, "query": query, "trained_on": trained_on,
             "exercises": exercises, "measured_on": measured_on, "weight_kg": weight_kg, "goal": goal,
             "habit": habit, "done": done, "day": day, "note": note, "days": days, "limit": limit}
    from engine.core.session_context import get_current_user_id
    user_id = get_current_user_id()
    return await asyncio.to_thread(run_gym_tool, {k: v for k, v in given.items() if v not in (None, "")}, user_id=user_id)

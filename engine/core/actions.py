"""
JARVIS Core Actions — Điều phối và tự động gọi các tool thông qua LLM.
"""

import json
import logging
import asyncio
import os
import re
from engine.core.json_parser import safe_json_loads
from engine.core.command_registry import KNOWN_TOOL_NAMES, TOOL_REGISTRY

from engine.server.llm_server import call_llm, get_llm_client
from engine.tools.search_engine import handle_news_search
from engine.tools.screen import describe_screen
from engine.tools.desktop_automation import open_application, close_application
from engine.tools.webcam import webcam_analyze

log = logging.getLogger("jarvis.actions")

# LLM vòng 2: prompt tóm tắt kết quả tool nằm ở prompt/tool_summary.md, ghép bởi
# engine.prompts.results (quy tắc định dạng riêng vẫn do từng tool module sở hữu).

# Định nghĩa các tool theo OpenAI Function Calling schema, xem qua ở thư mục commands
async def execute_tool(name: str, arguments: dict, ws=None, safe_ws_send_json=None, conversation_history: list = None, **kwargs) -> str | dict:
    """Thực thi tool và tự động ghi lại Trace JSON phục vụ tự tiến hóa."""
    import time
    from engine.core.trace_logger import TraceLogger
    from engine.core import guardrails

    start_time = time.time()
    outcome = "success"
    error_msg = ""
    result = None

    try:
        result = await _execute_tool_inner(name, arguments, ws, safe_ws_send_json, conversation_history, **kwargs)
        if isinstance(result, str):
            result = guardrails.scrub_untrusted(result)
        elif isinstance(result, dict) and isinstance(result.get("text"), str):
            result = {**result, "text": guardrails.scrub_untrusted(result["text"])}
        if isinstance(result, str) and (
            result.startswith("Lỗi") or result.startswith("Error") or result.startswith("Xin lỗi")
        ):
            outcome = "failed"
            error_msg = result
        elif isinstance(result, str) and result.rstrip(" .!\n").endswith("Thất bại"):
            # e.g. "Mở ứng dụng 'x': Thất bại" — the tool ran but did not do the job;
            # recording it as success taught Learning a bogus validated workflow.
            outcome = "failed"
            error_msg = result
        elif isinstance(result, dict) and "error" in result:
            outcome = "failed"
            error_msg = str(result["error"])
        elif isinstance(result, str) and any(
            result.lower().startswith(marker) for marker in (
                "không tìm thấy", "không có kết quả", "không thể", "no results",
            )
        ):
            outcome = "no_result"
        return result
    except Exception as e:
        outcome = "failed"
        error_msg = str(e)
        raise e
    finally:
        duration = time.time() - start_time
        TraceLogger.log_trace(
            action_name=name,
            args=arguments,
            outcome=outcome,
            output=result,
            duration=duration,
            error_message=error_msg
        )

async def _execute_tool_inner(name: str, arguments: dict, ws=None, safe_ws_send_json=None, conversation_history: list = None, **kwargs) -> str | dict:
    """Thực thi tool dựa trên tên và đối số truyền từ LLM."""
    if ws and safe_ws_send_json is None:
        try:
            from server import safe_ws_send_json as _sws
            safe_ws_send_json = _sws
        except Exception:
            pass

    # Tiền xử lý tham số trước khi qua Guardrail khi bypass LLM
    if name in ("open_app", "close_app") and not arguments.get("app_name"):
        from engine.tools.desktop_automation import extract_app_name
        app_name = extract_app_name(arguments.get("user_text", kwargs.get("user_text", "")))
        if app_name:
            arguments["app_name"] = app_name

    # Chốt chặn bảo mật Output Guardrail
    try:
        from engine.core.guardrails import verify_output
        is_safe, reason = verify_output(name, arguments)
        if not is_safe:
            log.warning(f"Output Guardrail blocked: {reason}")
            return f"Lỗi bảo mật: {reason}"
    except Exception as e:
        # Fail-closed: không kiểm tra được thì không chạy (trước đây ghi log rồi vẫn chạy tool).
        log.error(f"Failed to run Output Guardrail, blocking '{name}': {e}")
        return f"Lỗi bảo mật: không kiểm tra được lệnh gọi '{name}', đã chặn."

    if name == "execute_command":
        cmd_name = arguments.get("command_name")
        args_str = arguments.get("args", "")
        log.info(f"Running command: {cmd_name} with args: {args_str}")
        try:
            # Giải mã args_str nếu nó là JSON string để chuyển cho các tool cũ
            parsed_args = {}
            if args_str:
                try:
                    parsed_args = safe_json_loads(args_str)
                except Exception:
                    parsed_args = {"query": args_str, "app_name": args_str, "instruction": args_str}

            # Tự động chuyển hướng gọi các tool cũ khi LLM gọi qua execute_command.
            # KNOWN_TOOL_NAMES là nguồn sự thật duy nhất (xem command_registry.py)
            # — không tự chép tay danh sách ở đây nữa để tránh lệch với
            # guardrails.py như đã từng xảy ra với mcp_call.
            if cmd_name in KNOWN_TOOL_NAMES:
                return await execute_tool(cmd_name, parsed_args, ws, safe_ws_send_json, conversation_history, **kwargs)


            if cmd_name == "call_remember":
                from engine.core.memory import save_memory
                content = parsed_args.get("content", "")
                mem_type = parsed_args.get("type", "fact")
                source = parsed_args.get("source", "")
                importance = int(parsed_args.get("importance", 5))
                if not content:
                    return "Lỗi: Thiếu nội dung để ghi nhớ."
                await asyncio.to_thread(save_memory, content, mem_type, source, importance)
                if ws and safe_ws_send_json:
                    await safe_ws_send_json(ws, {"type": "memory_updated"})
                return f"Đã ghi nhớ: {content[:80]}"

            from engine.tools.skill_manager import get_skill_manager
            mgr = get_skill_manager()
            cmd = mgr.commands.get(cmd_name)
            if cmd:
                # `Command` chỉ chứa metadata (tên/mô tả/nội dung markdown) —
                # KHÔNG có handler thực thi gắn kèm. Trước đây nhánh này báo
                # "thành công" cho MỌI lệnh không nằm trong KNOWN_TOOL_NAMES dù
                # không làm gì cả — im lặng lừa cả LLM lẫn người dùng. Báo lỗi
                # trung thực thay vì giả vờ đã chạy.
                return (
                    f"Lỗi: Câu lệnh '{cmd_name}' có tài liệu mô tả nhưng chưa có logic thực thi "
                    f"thật trong hệ thống (chưa được đăng ký trong KNOWN_TOOL_NAMES). "
                    f"Mô tả: {cmd.description}"
                )
            return f"Không tìm thấy câu lệnh '{cmd_name}' trong hệ thống."
        except Exception as e:
            return f"Lỗi khi thực thi câu lệnh '{cmd_name}': {e}"

    log.info(f"Executing tool '{name}' with args: {arguments}")

    # Đang tách dần _execute_tool_inner sang TOOL_REGISTRY (xem
    # command_registry.py) — tool nào đã migrate thì dispatch qua đây, tool
    # nào chưa migrate rơi xuống elif chain cũ bên dưới. Cùng 1 định dạng lỗi
    # cho cả 2 nhánh để hành vi không đổi trong lúc chuyển tiếp.
    registry_handler = TOOL_REGISTRY.get(name)
    if registry_handler is not None:
        try:
            return await registry_handler(arguments, ws, safe_ws_send_json, conversation_history, **kwargs)
        except Exception as e:
            log.error(f"Error executing tool '{name}': {e}", exc_info=True)
            return f"Lỗi khi thực thi công cụ '{name}': {str(e)}"

    try:
        if name == "search_news":
            query = arguments.get("query", "")
            res = await handle_news_search(query)
            if isinstance(res, dict):
                return res.get("display", "")
            return str(res)

        elif name == "weather_search":
            location = arguments.get("location", "Hồ Chí Minh")
            from engine.tools.weather_engine import weather_search as _weather
            return await _weather(location, hourly=str(arguments.get("hourly", "")).lower() in ("1", "true", "yes", "có"))

        elif name == "map_route":
            from engine.tools.map_engine import map_route as _map_route
            return await _map_route(
                arguments.get("origin", ""), arguments.get("destination", ""), ws, safe_ws_send_json
            )

        elif name == "map_pois":
            from engine.tools.map_engine import map_pois as _map_pois
            return await _map_pois(
                arguments.get("category", "cafe"), arguments.get("location", "Thành phố Hồ Chí Minh"),
                ws, safe_ws_send_json,
            )

        elif name == "read_screen":
            client = get_llm_client()
            return await describe_screen(llm_client=client)

        elif name == "cap_screen":
            from engine.tools.screen import take_screenshot_file
            media_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "media")
            screenshot_path = os.path.join(media_dir, "screenshot.png")
            
            ok = await take_screenshot_file(screenshot_path)
            
            # 2. Nếu có kết nối websocket, gửi sự kiện thông báo URL về Frontend
            if ok and ws:
                log.info(f"Sending screenshot URL via WebSocket to frontend (cap_screen). ws={ws}")
                try:
                    await safe_ws_send_json(ws, {
                        "type": "screenshot_processed",
                        "url": "/api/media/local/screenshot.png"
                    })
                except Exception as e:
                    log.warning(f"Failed to send screenshot via WebSocket (cap_screen): {e}")
                return "Đã chụp màn hình và gửi về giao diện Frontend thành công, thưa Ngài."
            else:
                log.warning(f"Cannot send screenshot via WS (cap_screen). ok={ok}, ws={ws}")
            
            return "Tôi không thể thực hiện chụp màn hình lúc này."

        elif name == "read_webcam":

            client = get_llm_client()
            prompt = arguments.get("prompt", "What do you see through the webcam?")
            return await webcam_analyze(client=client, prompt=prompt, is_vi=True)

        elif name == "open_app":
            app_name = arguments.get("app_name")
            if not app_name:
                from engine.tools.desktop_automation import extract_app_name
                app_name = extract_app_name(arguments.get("user_text", kwargs.get("user_text", "")))
            if app_name:
                ok = await open_application(app_name)
                return f"Mở ứng dụng '{app_name}': {'Thành công' if ok else 'Thất bại'}"
            return "Lỗi: Không cung cấp tên ứng dụng để mở."
            
        elif name == "close_app":
            app_name = arguments.get("app_name")
            if not app_name:
                from engine.tools.desktop_automation import extract_app_name
                app_name = extract_app_name(arguments.get("user_text", kwargs.get("user_text", "")))
            if app_name:
                ok = await close_application(app_name)
                return f"Đóng ứng dụng '{app_name}': {'Thành công' if ok else 'Thất bại'}"
            return "Lỗi: Không cung cấp tên ứng dụng để đóng."

        elif name == "search_media":
            from engine.tools.media_search import execute_media_search
            return await execute_media_search(arguments, ws, safe_ws_send_json)
            
        elif name == "win_control":
            from engine.tools.windows_control import run_win_control_workflow
            user_text = arguments.get("user_text", kwargs.get("user_text", ""))
            return await run_win_control_workflow(user_text, ws, safe_ws_send_json)

        elif name == "mcp_call":
            server_name = str(arguments.get("server", "")).strip()
            tool_name = str(arguments.get("tool", "")).strip()
            tool_args = arguments.get("arguments") or {}
            if isinstance(tool_args, str):
                try:
                    tool_args = safe_json_loads(tool_args) if tool_args.strip() else {}
                except Exception:
                    return "Lỗi: Tham số 'arguments' của mcp_call phải là JSON hợp lệ."
            if not server_name or not tool_name:
                return "Lỗi: mcp_call cần cả 'server' và 'tool'."

            from engine.server.mcp_server import get_mcp_hub
            try:
                hub = get_mcp_hub()
                result = await hub.call_tool(server_name, tool_name, tool_args)
            except (ValueError, TimeoutError) as e:
                return f"Lỗi: {e}"
            except Exception as e:
                return f"Lỗi khi gọi MCP tool '{tool_name}' trên server '{server_name}': {e}"

            text_parts = []
            if hasattr(result, "content"):
                for item in result.content:
                    if hasattr(item, "text") and item.text:
                        text_parts.append(item.text)
            raw = "\n".join(text_parts) if text_parts else str(result)
            return raw.strip() or f"MCP tool '{tool_name}' trên '{server_name}' không trả về nội dung."

        elif name == "get_skill_stats":
            from engine.tools.skill_manager import get_skill_manager
            mgr = get_skill_manager()
            stats = mgr.get_stats()
            filter_q = arguments.get("filter", "").strip()
            if filter_q:
                matched = mgr.search_skills(filter_q)
                matched_cmds = mgr.search_commands(filter_q)
                lines = [f"Tổng số: {stats['total_skills']} kỹ năng, {stats['total_commands']} câu lệnh."]
                if matched:
                    lines.append(f"\nKỹ năng liên quan '{filter_q}':")
                    for s in matched:
                        lines.append(f"- {s.name}: {s.description}")
                if matched_cmds:
                    lines.append(f"\nCâu lệnh liên quan '{filter_q}':")
                    for c in matched_cmds:
                        lines.append(f"- {c.name}: {c.description}")
                return "\n".join(lines)
            else:
                skills_list = "\n".join(f"- {s.name}: {s.description}" for s in mgr.list_skills(enabled_only=True))
                cmds_list = "\n".join(f"- {c.name}: {c.description}" for c in mgr.list_commands(enabled_only=True))
                return (
                    f"Hệ thống có {stats['total_skills']} kỹ năng ({stats['enabled_skills']} đang bật) "
                    f"và {stats['total_commands']} câu lệnh ({stats['enabled_commands']} đang bật).\n\n"
                    f"KỸ NĂNG:\n{skills_list}\n\n"
                    f"CÂU LỆNH:\n{cmds_list}"
                )
            
        elif name == "get_skill_content":
            from engine.tools.skill_manager import get_skill_manager
            mgr = get_skill_manager()
            skill_name = arguments.get("name", "").strip()
            if not skill_name:
                return "Lỗi: Không cung cấp tên kỹ năng."
            skill = mgr.get_skill(skill_name)
            if not skill:
                cmd = mgr.get_command(skill_name)
                if cmd:
                    return f"Câu lệnh: {cmd.name}\nMô tả: {cmd.description}\nCách dùng: {cmd.usage}\n\nNội dung:\n{cmd.content[:4000]}"
                return f"Không tìm thấy kỹ năng hoặc câu lệnh '{skill_name}'."
            content = skill.content[:4000]
            return f"Kỹ năng: {skill.name}\nMô tả: {skill.description}\nDanh mục: {skill.category}\nTags: {', '.join(skill.tags)}\n\nNội dung:\n{content}"

        elif name == "office_tool":
            from engine.tools.office_tools import handle_office_command
            attachment_context = kwargs.get("attachment_context")
            filepath = arguments.get("filepath", "")
            if attachment_context is not None:
                filepath = str(attachment_context.resolved_path)
            prompt = arguments.get("prompt", "")
            return await handle_office_command(
                filepath=filepath,
                prompt=prompt,
                conversation_history=conversation_history,
                ws=ws
            )

        elif name == "rag_tool":
            from engine.tools.rag_tool import handle_rag_query
            return await handle_rag_query(
                query=arguments.get("query", ""),
                attachment_context=kwargs.get("attachment_context"),
            )

        elif name == "check_project":
            from engine.tools.check_project import check_project as run_goose_check
            user_text_val = kwargs.get("user_text", "")
            user_query = arguments.get("query", "").strip() or user_text_val.strip()
            return await run_goose_check(ws, safe_ws_send_json, user_query)

        elif name == "check_security":
            from engine.security.monitor import run_security_check
            return run_security_check()

        elif name == "check_system":
            from engine.security.system_check import run_system_check
            return await asyncio.to_thread(run_system_check)

        elif name == "dream":
            from engine.core.dream import trigger_dream_cycle_now
            trigger_dream_cycle_now()
            return (
                "Đã kích hoạt 1 chu kỳ Dream ở nền: tôi sẽ tóm tắt hội thoại thừa thải, "
                "gọn bớt log tác vụ cũ và tái tổ chức Obsidian Wiki. Bản gốc luôn được sao lưu "
                "trước khi gộp, không ảnh hưởng đến cuộc trò chuyện hiện tại."
            )

        elif name == "install_extension":
            from engine.tools.extension_installer import install_extension
            return await install_extension(arguments, ws, safe_ws_send_json)

        elif name == "take_note":
            from engine.tools.note_engine import execute_note_action
            return await execute_note_action(
                arguments=arguments,
                conversation_history=conversation_history,
                prev_results=kwargs.get("prev_results", ""),
                user_text=kwargs.get("user_text", "")
            )

        elif name == "read_note":
            from engine.tools.note_engine import get_note_engine
            note_eng = get_note_engine()
            raw_text = arguments.get("user_text", kwargs.get("user_text", ""))
            query = arguments.get("query", "").strip()
            
            # Giải mã số ID từ query hoặc user_text (ví dụ: "đọc ghi chú số 1" -> ID 1)
            nums = re.findall(r'\d+', query or raw_text)
            if nums:
                note_idx = int(nums[0])
                notes = await asyncio.to_thread(note_eng.list_notes, 50)
                if 1 <= note_idx <= len(notes):
                    target_note = notes[note_idx - 1]
                    return f"Nội dung ghi chú [ID: {note_idx}] '{target_note['title']}':\n---\n{target_note['content']}\n---"

            target_query = query or raw_text
            if target_query:
                note = await asyncio.to_thread(note_eng.get_note, target_query)
                if note:
                    return f"Nội dung ghi chú '{note['title']}':\n---\n{note['content']}\n---"
                else:
                    from engine.tools.wiki_retrieval import query_wiki

                    wiki_result = await query_wiki(query, roots=("topics",))
                    if wiki_result:
                        return wiki_result
                    return f"Không tìm thấy ghi chú nào phù hợp với: {query}."
            else:
                return "Ngài vui lòng cung cấp tên hoặc từ khóa ghi chú cần đọc."

        elif name == "query_history":
            from engine.tools.history_engine import (
                _parse_time_range,
                query_conversation_history,
            )
            from engine.tools.wiki_retrieval import query_wiki
            query = arguments.get("query", "").strip()
            limit = int(arguments.get("limit", 20) or 20)
            history_result = query_conversation_history(query, limit)
            since, until = _parse_time_range(query)
            if since is None or until is None:
                wiki_result = await query_wiki(query)
                if wiki_result:
                    history_result = f"{history_result}\n\n{wiki_result}"
            return history_result

        elif name == "upscale_image":
            from engine.tools.image_engine import upscale_image as _upscale
            attachment_context = kwargs.get("attachment_context")
            input_path = arguments.get("input_path", "")
            if attachment_context is not None:
                input_path = str(attachment_context.resolved_path)
            output_path = arguments.get("output_path", "")
            scale = int(arguments.get("scale", 4))
            model_name = arguments.get("model_name", "upscayl-standard-4x")
            output_format = arguments.get("output_format", "png")
            if not input_path:
                return "Lỗi: Thiếu đường dẫn ảnh đầu vào (input_path)."
            result = await _upscale(
                input_path=input_path,
                output_path=output_path or None,
                scale=scale,
                model_name=model_name,
                output_format=output_format,
            )
            return result

        else:
            return f"Lỗi: Không tìm thấy công cụ '{name}'."
    except Exception as e:
        log.error(f"Error executing tool '{name}': {e}", exc_info=True)
        return f"Lỗi khi thực thi công cụ '{name}': {str(e)}"

def clean_and_truncate_news_results(text: str) -> str:
    if not text or "📰" not in text:
        return text
    parts = text.split("📰")
    header = parts[0]
    cleaned_articles = []
    for part in parts[1:]:
        match = re.search(r"(📄\s*)(.*)", part, re.DOTALL)
        if match:
            meta = part[:match.start(2)]
            content = match.group(2).strip()
            content = re.sub(r"\s+", " ", content)
            if len(content) > 5000:
                content = content[:5000] + "\n... (Nội dung được rút gọn để tránh quá tải token) ..."
            cleaned_articles.append("📰" + meta + content)
        else:
            cleaned_articles.append("📰" + part)
    return header + "".join(cleaned_articles)

def clean_query(text: str) -> str:
    t = text.lower().strip()
    t = re.sub(r"^(?:hãy|giúp|vui\s+lòng|làm\s+ơn|cho\s+tôi\s+biết|tìm\s+kiếm|tra\s+cứu|xem|check|search|phát|xem\s+phim|mở\s+nhạc|nghe\s+nhạc)\s+", "", t)
    return t.strip()

async def handle_user_intent_with_tools(user_text: str, add_tools: str, conversation_history: list = None, ws=None, agent_name="Agent", flow_tracker=None, flow_agents=None, silent: bool = False, **kwargs) -> str:
    """Nhận diện intent từ người dùng, tự động chạy tools và phản hồi tối ưu."""
    if not flow_tracker:
        class NoOpFlowTracker:
            def step(self, label):
                class NoOpStepContext:
                    async def __aenter__(self): return self
                    async def __aexit__(self, *args): pass
                return NoOpStepContext()
            async def track(self, *args, **kwargs): pass
            async def fail_all_active(self): pass
        flow_tracker = NoOpFlowTracker()

    # 1. Xác định các công cụ được yêu cầu trong agent này
    tool_names = []
    if add_tools:
        for t in add_tools:
            if isinstance(t, dict) and "function" in t:
                tool_names.append(t["function"]["name"])
            elif isinstance(t, str):
                tool_names.append(t)

    # 2. Định nghĩa các nhóm công cụ tối ưu
    internal_llm_tools = {"read_screen", "read_webcam", "office_tool", "rag_tool"}
    direct_tools = {"open_app", "close_app", "win_control", "search_news", "get_market_data", "search_products", "weather_search", "search_media","cap_screen", "map_route", "map_pois", "get_vannien_data", "get_zodiac_data", "get_cgv_movies", "get_epic_free_games", "take_note", "query_history", "read_note", "check_security", "check_system", "check_project", "upscale_image", "check_mail", "check_calendar", "dream", "web_research"}

    active_internal_llm_tools = []
    active_direct_tools = []
    for name in tool_names:
        if name in internal_llm_tools:
            active_internal_llm_tools.append(name)
        elif name in direct_tools:
            active_direct_tools.append(name)

    results_text = ""

    try:
        # Nếu có công cụ LLM nội bộ (Thường chạy độc lập)
        if active_internal_llm_tools:
            active_tool = active_internal_llm_tools[0]
            log.info(f"Bypassing LLM Vòng 1 for internal LLM tool: {active_tool}")
            
            args = {}
            if active_tool == "read_webcam":
                args["prompt"] = user_text
            elif active_tool == "office_tool":
                args["prompt"] = user_text
            elif active_tool == "rag_tool":
                args["query"] = user_text
            elif active_tool == "check_project":
                pass
            elif active_tool == "win_control":
                args["user_text"] = user_text

            tool_desc = f"Hệ thống → {active_tool}"
            async with flow_tracker.step(tool_desc):
                tool_result = await execute_tool(
                    active_tool,
                    args,
                    ws,
                    conversation_history=conversation_history,
                    attachment_context=kwargs.get("attachment_context"),
                )

            if active_tool == "cap_screen":
                if isinstance(tool_result, dict):
                    tool_result = tool_result.get("text", json.dumps(tool_result))
                results_text = f"Kết quả công cụ cap_screen:\n{tool_result}"
            else:
                import inspect

                final_content = ""
                if inspect.isasyncgen(tool_result) or hasattr(tool_result, "__anext__"):
                    async for chunk in tool_result:
                        if chunk:
                            final_content += chunk
                            if not silent:
                                from server import safe_ws_send_json
                                from engine.server.text_streamer import stream_chunk_smoothly
                                await stream_chunk_smoothly(ws, safe_ws_send_json, chunk, char_delay=0.005)
                else:
                    if isinstance(tool_result, dict):
                        tool_result = tool_result.get("text", json.dumps(tool_result))
                    final_content = str(tool_result)
                    if not silent:
                        from server import safe_ws_send_json
                        from engine.server.text_streamer import stream_text_smoothly
                        await stream_text_smoothly(ws, safe_ws_send_json, final_content, word_delay=0.04)

                if not silent:
                    from server import safe_ws_send_json
                    from engine.server.voice_streamer import VoiceStreamer
                    streamer = VoiceStreamer(ws)
                    streamer.start()
                    await streamer.put(final_content)
                    await streamer.stop()
                    await safe_ws_send_json(ws, {"type": "stream_end"})

                from engine.server.text_streamer import clean_latex_math
                return clean_latex_math(final_content)

        # Nếu có các công cụ chạy trực tiếp (Cho phép chạy tuần tự nhiều công cụ)
        elif active_direct_tools:
            # Chặn xung đột: Nếu có cả read_note và take_note trong hàng đợi direct tools, chọn công cụ phù hợp nhất dựa trên ý định người dùng
            if "read_note" in active_direct_tools and "take_note" in active_direct_tools:
                t_lower = user_text.lower()
                is_read_intent = any(kw in t_lower for kw in ["đọc ghi chú", "đọc lại", "xem lại", "coi lại", "kiểm tra ghi chú", "xem ghi chú", "xem danh sách", "chi tiết ghi chú", "nội dung ghi chú", "danh sách ghi chú", "tìm ghi chú", "tra cứu ghi chú"]) or (any(kw in t_lower for kw in ["đọc", "xem", "chi tiết", "kiểm tra", "coi"]) and any(kw in t_lower for kw in ["ghi chú", "note"]))
                if is_read_intent:
                    active_direct_tools = [t for t in active_direct_tools if t != "take_note"]
                else:
                    active_direct_tools = [t for t in active_direct_tools if t != "read_note"]

            log.info(f"Bypassing LLM Vòng 1 for direct tools: {active_direct_tools}")
            results_list = []

            for active_tool in active_direct_tools:
                args = {"user_text": user_text}
                if active_tool in ("search_news", "get_market_data", "search_products", "weather_search", "search_media", "get_vannien_data", "win_control", "get_zodiac_data", "get_cgv_movies", "get_epic_free_games", "web_research"):
                    args["query"] = clean_query(user_text)
                    if active_tool == "weather_search":
                        args["location"] = args["query"]
                elif active_tool == "query_history":
                    args["query"] = user_text
                elif active_tool == "read_note":
                    args["query"] = user_text

                tool_desc = f"Hệ thống → {active_tool}"
                current_prev_results = "\n\n".join(results_list)
                async with flow_tracker.step(tool_desc):
                    tool_result = await execute_tool(
                        active_tool, 
                        args, 
                        ws, 
                        conversation_history=conversation_history,
                        prev_results=current_prev_results,
                        user_text=user_text,
                        attachment_context=kwargs.get("attachment_context"),
                    )
                
                if isinstance(tool_result, dict):
                    tool_result = tool_result.get("text", json.dumps(tool_result))
                
                results_list.append(f"Kết quả công cụ {active_tool}:\n{tool_result}")

            results_text = "\n\n".join(results_list)

        if flow_agents:
            await flow_agents.complete_all_active()

        # --- Gọi LLM Vòng 2 tổng hợp ---
        results_text = clean_and_truncate_news_results(results_text)
        # Truncate đơn giản nếu quá dài — KHÔNG dùng RTK vì filter 'log' làm mất nội dung tin tức/dữ liệu thực
        MAX_RESULTS_CHARS = 12000
        if len(results_text) > MAX_RESULTS_CHARS:
            log.info(f"[Actions] results_text truncated: {len(results_text)} -> {MAX_RESULTS_CHARS} chars")
            results_text = results_text[:MAX_RESULTS_CHARS] + "\n... (nội dung tiếp theo đã được cắt bớt)"
        # Xác định active_tool cho LLM Vòng 2
        active_tool = "general"
        if active_direct_tools:
            active_tool = list(active_direct_tools)[0]
            
        from engine.prompts.results import build_tool_summary_prompt
        summary_prompt = build_tool_summary_prompt(active_tool, results_text)
            
        messages_v2 = [
            {"role": "system", "content": summary_prompt},
            {"role": "user", "content": f"Câu hỏi của người dùng: {user_text}\n\nKết quả công cụ:\n{results_text}"}
        ]

        log.info("=== [LLM] summarize tool results ===")

        if silent:
            response = await call_llm(
                messages=messages_v2,
                temperature=0.3,
                thinking=False,
                stream=False,
            )
            final_content = ""
            if response and hasattr(response, "choices") and response.choices:
                final_content = response.choices[0].message.content or ""
            if flow_agents:
                await flow_agents.complete_all_active()
            if not final_content.strip():
                final_content = "Đã thực hiện xong."
            from engine.server.text_streamer import clean_latex_math
            return clean_latex_math(final_content)

        from server import safe_ws_send_json

        final_content = ""

        async def run_stream():
            nonlocal final_content
            stream = await call_llm(
                messages=messages_v2,
                temperature=0.3,
                thinking=False,
                stream=True
            )

            from engine.server.voice_streamer import VoiceStreamer
            from engine.server.text_streamer import SentenceSplitter, stream_chunk_smoothly

            weather_sanitizer = None
            if active_tool == "weather_search":
                from engine.tools.weather_engine import sanitize_weather_display_text
                weather_sanitizer = sanitize_weather_display_text

            streamer = VoiceStreamer(ws)
            streamer.start()
            # Cùng bộ cắt câu với luồng chat chính: không tách ở dấu chấm trong tên file
            # (context_manager.py). raw=True để giữ khoảng trắng khi ghép lại phần hiển thị.
            splitter = SentenceSplitter(raw=True)

            async def emit_segment(segment: str):
                nonlocal final_content
                output_segment = segment
                if weather_sanitizer is not None:
                    output_segment = weather_sanitizer(output_segment)
                    final_content += output_segment
                    await stream_chunk_smoothly(
                        ws,
                        safe_ws_send_json,
                        output_segment,
                        char_delay=0.005,
                    )
                sentence = output_segment.strip()
                if sentence:
                    await streamer.put(sentence)

            try:
                async for chunk in stream:
                    if getattr(ws, "cancel_requested", False):
                        log.info("Response generation (vòng 2) cancelled by client request")
                        break
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta.content or ""
                    if delta:
                        if weather_sanitizer is None:
                            final_content += delta
                            await stream_chunk_smoothly(ws, safe_ws_send_json, delta, char_delay=0.005)
                        cancelled_mid_split = False
                        for segment in splitter.push(delta):
                            if getattr(ws, "cancel_requested", False):
                                cancelled_mid_split = True
                                break
                            await emit_segment(segment)
                        if cancelled_mid_split:
                            break

                if getattr(ws, "cancel_requested", False):
                    await streamer.stop(clear_queue=True)
                else:
                    for segment in splitter.flush():
                        await emit_segment(segment)
            except Exception:
                # Stream đứt giữa chừng: dừng worker TTS trước khi ném lỗi lên, tránh treo task + UI kẹt "speaking".
                await streamer.stop(clear_queue=True)
                raise

            await streamer.stop(clear_queue=False)

        async with flow_tracker.step("LLM: tổng hợp phản hồi..."):
            await run_stream()

        if flow_agents:
            await flow_agents.complete_all_active()

        if not getattr(ws, "cancel_requested", False):
            await safe_ws_send_json(ws, {"type": "stream_end"})

        if not final_content.strip():
            final_content = "Đã thực hiện xong."
        from engine.server.text_streamer import clean_latex_math
        final_content = clean_latex_math(final_content)
        return final_content

    except Exception as e:
        log.error(f"Failed to handle user intent with tools: {e}", exc_info=True)
        await flow_tracker.fail_all_active()
        if flow_agents:
            await flow_agents.fail_all_active()
        return f"Xin lỗi, tôi đã gặp lỗi khi xử lý yêu cầu của ngài: {str(e)}"

#----------------------------------------------------------------------------------
#   Đây là mẫu lấy prompt từ thu mục commands qua skill_manager
#----------------------------------------------------------------------------------
def get_agent_context_and_tools(tool_names: list[str]) -> list[dict]:
    """
    Tự động đọc thông tin từ các tệp markdown trong commands/ qua SkillManager
    để sinh OpenAI Tool Schemas cho agent (prompt riêng agent không dùng: LLM chỉ tóm tắt kết quả).
    """
    from engine.tools.skill_manager import get_skill_manager
    mgr = get_skill_manager()
    
    # Quét lại commands nếu cache trống
    if not mgr.commands:
        mgr.scan_commands()
        
    tool_schemas = []
    
    for name in tool_names:
        cmd = mgr.get_command(name)
        if not cmd:
            log.warning(f"get_agent_context_and_tools: Command '{name}' không tồn tại trong hệ thống.")
            continue
            
        
        # Sinh OpenAI Tool Schema từ metadata của Command
        properties = {}
        required = []
        if cmd.usage:
            try:
                # cmd.usage là một chuỗi JSON ví dụ: '{"query": "mô tả..."}'
                usage_dict = json.loads(cmd.usage)
                for k, v in usage_dict.items():
                    properties[k] = {
                        "type": "string",
                        "description": v
                    }
                    required.append(k)
            except Exception as e:
                log.debug(f"Failed to parse usage JSON for command '{name}': {e}")
                
        # Fallback nếu parsing lỗi hoặc trống
        if not properties:
            properties["query"] = {
                "type": "string",
                "description": cmd.description
            }
            required = ["query"]
            
        schema = {
            "type": "function",
            "function": {
                "name": cmd.name,
                "description": cmd.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required
                }
            }
        }
        tool_schemas.append(schema)
        
    return tool_schemas

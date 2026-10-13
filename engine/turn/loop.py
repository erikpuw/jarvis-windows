"""Vòng lặp sinh có ràng buộc (spec 2026-10-12 mục 3.1): vòng chọn tool — grammar ép {"tool","say","args"}, code stream
"say", chạy tool, nối [kết quả …], lặp ≤ MAX_ROUNDS; tool=none → vòng trả lời bằng chữ thường, prompt không giao kèo JSON
(log 2026-10-12 18:08: trả lời trong chuỗi JSON → Gemma chỉ viết câu hứa, không đưa nội dung). Không tool calling gốc."""
import asyncio
import json
import logging
import re

from engine.tools import registry
from engine.turn import history, schema
from engine.turn.say import SayReader, parse_turn

log = logging.getLogger("jarvis.turn")

MAX_ROUNDS = 4
RESULT_CHARS = 8000   # log 2026-10-12 03:29: tin 18k ký tự làm vòng sau chậm
MAX_TOKENS = 1500
# Người dùng chốt 2026-10-12 (think_mode_probe, held-out 89 câu, QAT): think tắt 64/66 tool, p90 3,4s;
# budget 128 65/66, p90 2,8s; 256 66/66, p90 4,2s; không giới hạn 66/66, p90 5,6s.
THINK_BUDGET = 128
_LLM_ERROR = "Xin lỗi ngài, tôi đang gặp lỗi kết nối với mô hình ngôn ngữ."
_NOT_DONE = "Tôi chưa làm được việc này vì thiếu thông tin cần thiết, thưa ngài."
TOOL_ICON = "🛠️ "  # ngài 2026-10-12: câu báo gọi tool có emoji công cụ đứng trước (chỉ hiển thị, TTS không đọc)
_SUMMARY = "Tổng hợp & trả lời"
# Chặn hứa bằng code (prompt chỉ giảm: honesty_probe 0/10 → 9/10). Câu hỏi mời ("…không?") không tính.
# ponytail: theo từ khoá, câu hứa không có các động từ này vẫn lọt; thêm động từ khi probe bắt được.
_SENTENCE_END = re.compile(r"[.!?…]+[\"')\]]*\s+|\n+")
_FUTURE = re.compile(r"(?<!\w)(tôi sẽ|để tôi)\s+(nhắc|theo dõi|báo lại)", re.I)  # không có cơ chế làm sau lượt
_ACT = re.compile(r"(?<!\w)(tôi sẽ|để tôi|tôi đi)\s+(tìm|đặt|gửi|gọi|kiểm tra|tra|lọc|mở|tắt|chạy|cập nhật)", re.I)
_BULLET = re.compile(r"(?:[*-]|\d+\.)\s")
_NO_PROMISE = "Lượt này tôi chưa làm việc đó, thưa ngài: tôi chỉ làm được những việc có công cụ, khi ngài yêu cầu."
_SILENT = "Xin lỗi ngài, tôi chưa trả lời được câu này, ngài thử nói lại giúp tôi."
# temperature 0 đôi khi kẹt lặp một từ/cụm tới max_tokens (log 2026-10-13 16:10: "quên hết hết hết…" 1500 token):
# cụm 1-6 từ lặp liên tiếp ≥ 7 lần ở cuối → giữ một lần, dừng stream.
_REPEAT = re.compile(r"(\S+(?:\s+\S+){0,5}?)(?:\s+\1){6,}\s*$")
_REPEAT_TAIL = 800
# Ngài 2026-10-13: "tôi đang xem…" (ngài kể việc mình làm) bị gọi read_screen/system_status; sửa prompt, nạp bài học
# đều không chặn được (spike tuning 0/2) → code: tool này chỉ chạy khi câu nói tới đúng đối tượng của nó.
# ponytail: theo từ khoá; câu nhờ thật mà không có các từ này ("máy chậm quá, kiểm tra giúp") cũng bị chặn → dùng @tool.
_NEEDS_WORD = {
    "read_screen": re.compile(r"màn hình|screen", re.I),
    "system_status": re.compile(r"\b(cpu|gpu|ram|ổ|disk|tiến trình|process|bộ nhớ|dung lượng|nhiệt độ)\b", re.I),
}
_TOOL_IN_RAW = re.compile(r'"tool"\s*:\s*"(\w+)"')


def _off_target(tool: str, text: str) -> bool:
    rx = _NEEDS_WORD.get(tool)
    return bool(rx) and not rx.search(text or "")
# Phần nghĩ (reasoning_content) không lên UI và không bị cắt (cắt cũ gây "lỗi kết nối", log 15:46); THINK_BUDGET
# giới hạn nó. Nghĩ xong mà không có JSON → say rỗng → _SILENT.


def _user_message(text: str, attachment_context) -> dict:
    if attachment_context is None:
        return {"role": "user", "content": text}
    meta = json.dumps(attachment_context.router_metadata(), ensure_ascii=False)
    return {"role": "user", "content": f"{text}\n\n[tệp đính kèm: {meta}]"}


def _messages(text, conversation_history, attachment_context, turn_msgs, names) -> list[dict]:
    from engine.turn import prompt
    return [{"role": "system", "content": prompt.system_prompt(names)},
            *history.for_model(conversation_history), _user_message(text, attachment_context), *(turn_msgs or [])]


async def _call(messages, sch, stream: bool):
    """sch=None: vòng trả lời bằng chữ thường."""
    from engine.server import llm_server
    fmt = {} if sch is None else {"response_format": schema.response_format(sch)}
    return await llm_server.call_llm(messages=messages, thinking=True, thinking_budget=THINK_BUDGET, stream=stream,
                                     temperature=0.0, max_tokens=MAX_TOKENS, **fmt)


async def step(text, conversation_history, attachment_context=None, turn_msgs=None, only=None) -> dict:
    """Một vòng không stream (probe, vòng 1 khi có tệp)."""
    names = [only] if only else registry.chat_names(attachment_context)
    messages = _messages(text, conversation_history, attachment_context, turn_msgs, names)
    for attempt in (1, 2):
        r = await _call(messages, schema.build(attachment_context, only=only), stream=False)
        content = r.choices[0].message.content or ""
        if content.strip() or getattr(r.choices[0], "finish_reason", "") != "length":
            break
        log.warning("[TURN] suy nghĩ lan man (length, không có JSON), gọi lại lần %d", attempt)
    return parse_turn(content)


class _Output:
    """Chữ hiển thị (text_chunk) + TTS cho cả lượt; bảng display chỉ hiển thị, không đọc."""

    def __init__(self, ctx):
        from engine.server.text_streamer import SentenceSplitter, StreamCueFilter, StreamLatexFilter
        self.ctx, self.streamer, self.shown = ctx, None, ""
        self.splitter, self.latex, self.cue = SentenceSplitter(), StreamLatexFilter(), StreamCueFilter()

    async def _send(self, text: str):
        if text:
            self.shown += text
            await self.ctx.send_json(self.ctx.ws, {"type": "text_chunk", "text": text})

    async def say(self, piece: str):
        if self.streamer is None:
            from engine.server.voice_streamer import VoiceStreamer
            self.streamer = VoiceStreamer(self.ctx.ws)
            task = self.streamer.start()
            if task is not None and self.ctx.background_tasks is not None:
                self.ctx.background_tasks.add(task)
                task.add_done_callback(self.ctx.background_tasks.discard)
        await self._send(self.cue.filter_chunk(self.latex.filter_chunk(piece)))
        for sentence in self.splitter.push(piece):
            await self.streamer.put(sentence)

    async def end_say(self):
        await self._send(self.cue.filter_chunk(self.latex.flush()) + self.cue.flush())
        for sentence in self.splitter.flush():
            await self.streamer.put(sentence)

    async def gap(self):
        if self.shown and not self.shown.endswith("\n\n"):
            await self._send("\n\n")

    async def show(self, text: str):
        await self.gap()
        await self._send(text)

    async def finish(self):
        if self.streamer is not None:
            await self.streamer.stop()
        await self.ctx.send_json(self.ctx.ws, {"type": "stream_end"})

    async def abort(self):
        if self.streamer is not None:
            await self.streamer.stop(clear_queue=True)

    def text(self) -> str:
        from engine.server.text_streamer import clean_latex_math, strip_voice_cues
        return strip_voice_cues(clean_latex_math(self.shown)).strip()


def _cancelled(ctx) -> bool:
    return bool(getattr(ctx.ws, "cancel_requested", False))


async def _stream_round(ctx, out: _Output, messages, sch, text: str = "", gate: bool = False) -> dict | None:
    """Stream một vòng; None = bị huỷ. gate: tool bị _off_target chặn thì không hiện câu báo."""
    stream = await _call(messages, sch, stream=True)
    reader, raw, started, hidden = SayReader(), "", False, False
    await out.gap()
    async for chunk in stream:
        if _cancelled(ctx):
            return None
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content or ""
        raw += delta
        piece = reader.feed(delta)
        if piece:
            if not started:  # chỉ nhánh tool có "say"; "tool" đứng trước "say" nên đã biết tên tool
                started = True
                m = _TOOL_IN_RAW.search(raw)
                hidden = gate and bool(m) and _off_target(m.group(1), text)
                if not hidden:
                    await out.show(TOOL_ICON)
            if not hidden:
                await out.say(piece)
    await out.end_say()
    return parse_turn(raw)


def _breaks_promise(sentence: str, ran_tool: bool) -> bool:
    s = sentence.strip()
    if s.endswith("?"):
        return False
    bullet = bool(_BULLET.match(s))  # danh sách khả năng ("* Bảo mật: tôi sẽ kiểm tra…") không phải lời hứa
    return bool(_FUTURE.search(s) or (not ran_tool and not bullet and _ACT.search(s)))


async def _stream_answer(ctx, out: _Output, text, answer_msgs, names, ran_tool=False) -> str | None:
    """Vòng trả lời bằng chữ thường, từng câu qua _breaks_promise rồi mới hiện + đọc; None = bị huỷ."""
    from engine.turn import prompt
    messages = [{"role": "system", "content": prompt.system_prompt(names, answer=True)},
                *history.for_model(ctx.conversation_history, plain=True),
                _user_message(text, ctx.attachment_context), *answer_msgs]
    stream = await _call(messages, None, stream=True)
    raw, pending, dropped = "", "", False
    await out.gap()

    async def emit(sentence: str):
        nonlocal raw, dropped
        if _breaks_promise(sentence, ran_tool):
            log.info("[TURN] bỏ câu hứa: %r", sentence.strip()[:120])
            dropped = True
            return
        raw += sentence
        await out.say(sentence)
    async for chunk in stream:
        if _cancelled(ctx):
            return None
        if not chunk.choices:
            continue
        pending += chunk.choices[0].delta.content or ""
        cut = max(0, len(pending) - _REPEAT_TAIL)
        if rep := _REPEAT.search(pending, cut):
            log.warning("[TURN] trả lời kẹt lặp %r, cắt và dừng", rep.group(1)[:40])
            pending = pending[:rep.start()] + rep.group(1)
            if hasattr(stream, "aclose"):  # đóng kết nối: llama-server ngừng sinh tiếp
                await stream.aclose()
            break
        while m := _SENTENCE_END.search(pending):
            sentence, pending = pending[:m.end()], pending[m.end():]
            await emit(sentence)
    if pending:
        await emit(pending)
    if dropped:
        note = (" " if raw.strip() else "") + _NO_PROMISE
        raw += note
        await out.say(note)
    await out.end_say()
    return raw.strip()


def _answers_question(conversation_history) -> bool:
    """Lượt trước JARVIS hỏi/mời → câu này ("ừ", "làm đi") chỉ có nghĩa theo ngữ cảnh: không lưu workflow."""
    prev = history.for_model(conversation_history, plain=True)
    return bool(prev) and prev[-1]["role"] == "assistant" and prev[-1]["content"].rstrip().endswith("?")


async def _pick_file_tool(ctx) -> str | None:
    """Có tệp mà model không chọn tool tệp: hỏi ngài chọn cách xử lý (giữ hành vi 2026-09-28)."""
    from engine.main.ask_verifi import ask_user_selection
    att = ctx.attachment_context
    options = [{"id": t, "label": registry.description(t)} for t in registry.file_tools_for(att)]
    options.append({"id": "cancel", "label": "Không xử lý tệp"})
    selected = await ask_user_selection(ctx.ws, ctx.send_json, "attachment_route",
                                        f"Ngài muốn xử lý tệp {att.filename} theo cách nào?", options)
    return None if not selected or selected == "cancel" else selected


async def _run_tool(ctx, out, tool_ctx, tool: str, args: dict, say: str, cua_replay=None) -> tuple[dict, dict] | None:
    """Chạy một tool đã validate: status working → tool → thinking → hiện bảng display. None = bị huỷ."""
    await ctx.send_json(ctx.ws, {"type": "status", "state": "working", "message": f"Đang dùng công cụ {tool}"})
    tool_ctx.trace = [] if tool == "win_control" else None
    tool_ctx.replay_steps = cua_replay if tool == "win_control" else None
    async with ctx.flow_tracker.step(f"Chạy {tool}"):
        res = await registry.run(tool, args, tool_ctx)
    await ctx.send_json(ctx.ws, {"type": "status", "state": "thinking"})
    if _cancelled(ctx):
        return None
    displayed = registry.display(tool) and res.outcome == "success"
    if displayed:
        await out.show(res.text)
    step_rec = history.step_record(say, tool, args, res.text, res.outcome)
    if tool_ctx.trace and None not in tool_ctx.trace:
        step_rec["cua_steps"] = tool_ctx.trace
    result = history.result_message(tool, res.text, res.outcome, displayed, registry.answer_rules(tool), RESULT_CHARS)
    return step_rec, result


async def run_loop(text: str, ctx, only: str | None = None, replay: dict | None = None) -> str:
    att = ctx.attachment_context
    names = [only] if only else registry.chat_names(att)
    out = _Output(ctx)
    steps, turn_msgs, answer_msgs, ran, final_say = [], [], [], set(), ""
    tool_ctx = registry.ToolContext(ws=ctx.ws, send_json=ctx.send_json, attachment_context=att,
                                    conversation_history=list(ctx.conversation_history or []), user_text=text)

    def _stop() -> str:
        ctx.ws.last_turn = {"steps": steps, "final_say": ""}
        return out.text()

    # ngài 2026-10-12: vòng kiểm tra sau tool (thường ra none) không hiện thành "Chọn công cụ" thứ hai — bước
    # "Tổng hợp & trả lời" mở từ vòng đó, kéo dài qua vòng trả lời; chỉ đổi nhãn khi model gọi thêm tool.
    if replay:  # spec 2026-10-13 mục 5: câu trùng workflow đã lưu → chạy thẳng chuỗi tool, không vòng chọn
        log.info("[TURN] replay workflow=#%s tools=%s", replay["id"], replay["tools"])
        await ctx.flow_tracker.track(f"Phát lại workflow #{replay['id']}", "completed")
        for st in replay["tool_chain"]:
            say = st.get("say") or f"Tôi làm lại {st['tool']}."
            await out.gap()
            await out.show(TOOL_ICON)
            await out.say(say)
            await out.end_say()
            args, err = registry.validate(st["tool"], st.get("args") or {}, set(names))
            if err:
                steps.append(history.step_record(say, st["tool"], st.get("args") or {}, f"Lỗi: {err}", "failed"))
                answer_msgs.append(history.result_message(st["tool"], f"Lỗi: {err}", "failed", False, "", RESULT_CHARS))
                break
            ran_step = await _run_tool(ctx, out, tool_ctx, st["tool"], args, say, st.get("cua_steps"))
            if ran_step is None:
                await out.abort()
                return _stop()
            steps.append(ran_step[0])
            answer_msgs += [{"role": "assistant", "content": say}, ran_step[1]]
            if ran_step[0]["outcome"] != "success":
                break
    round_no, answer, summary = 0, True, None
    while not replay and round_no < MAX_ROUNDS and not (only and round_no):  # @tool: chỉ một vòng chọn tool
        round_no += 1
        sch = schema.build(att, only=only if round_no == 1 else None)
        messages = _messages(text, ctx.conversation_history, att, turn_msgs, names)
        flow = ctx.flow_tracker.step("Chọn công cụ" if round_no == 1 else _SUMMARY)
        await flow.__aenter__()
        try:
            if round_no == 1 and att is not None and registry.file_tools_for(att) and not only:
                turn = await step(text, ctx.conversation_history, att)
                if turn["tool"] == "none":
                    picked = await _pick_file_tool(ctx)
                    if picked is None:
                        await flow.__aexit__(None, None, None)
                        await out.show("Đã huỷ xử lý tệp vì chưa có lựa chọn phù hợp.")
                        answer = False
                        break
                    first = registry.params(picked)[:1]
                    turn = {"say": "", "tool": picked, "args": {first[0]: text} if first else {}}
                elif turn["say"]:
                    await out.show(TOOL_ICON + turn["say"])
            else:
                turn = await _stream_round(ctx, out, messages, sch, text, gate=not only)
        except Exception as exc:
            await flow.__aexit__(type(exc), exc, None)
            log.warning("[TURN] LLM failed round=%d: %s", round_no, exc)
            await out.show(_LLM_ERROR)
            answer = False
            break
        if turn is None or _cancelled(ctx):
            await out.abort()
            return _stop()
        log.info("[TURN] round=%d tool=%s args=%s say=%r", round_no, turn["tool"], turn["args"], turn["say"][:80])
        if not only and _off_target(turn["tool"], text):
            log.info("[TURN] chặn %s: câu không nói tới đối tượng của tool → trò chuyện", turn["tool"])
            turn = {"say": "", "tool": "none", "args": {}}
        if turn["tool"] == "none" and round_no > 1:
            summary = flow  # vòng trả lời chạy tiếp trong bước này
            break
        flow.label = f"Chọn công cụ → {'không cần' if turn['tool'] == 'none' else turn['tool']}"
        await flow.__aexit__(None, None, None)
        if turn["tool"] == "none":
            break
        args, err = registry.validate(turn["tool"], turn["args"], set(names))
        if err:
            log.warning("[TURN] invalid call %s %r: %s", turn["tool"], turn["args"], err)
            await out.show(_NOT_DONE)
            answer = False
            break
        key = (turn["tool"], json.dumps(args, sort_keys=True, ensure_ascii=False))
        if key in ran:
            log.info("[TURN] repeated call %s → vòng trả lời", turn["tool"])
            summary = ctx.flow_tracker.step(_SUMMARY)
            await summary.__aenter__()
            break
        ran.add(key)
        ran_step = await _run_tool(ctx, out, tool_ctx, turn["tool"], args, turn["say"])
        if ran_step is None:
            await out.abort()
            return _stop()
        step_rec, result = ran_step
        steps.append(step_rec)
        turn_msgs += [history.assistant_message(turn["say"], turn["tool"], args), result]
        answer_msgs += [{"role": "assistant", "content": turn["say"]}, result] if turn["say"] else [result]
    if answer:
        if summary is None:
            summary = ctx.flow_tracker.step(_SUMMARY if steps else "Trả lời")
            await summary.__aenter__()
        try:
            final_say = await _stream_answer(ctx, out, text, answer_msgs, registry.chat_names(att), bool(steps))
            await summary.__aexit__(None, None, None)
        except Exception as exc:
            await summary.__aexit__(type(exc), exc, None)
            log.warning("[TURN] LLM failed answer: %s", exc)
            await out.show(_LLM_ERROR)
            final_say = ""
        if final_say is None or _cancelled(ctx):
            await out.abort()
            return _stop()
        log.info("[TURN] answer=%r", final_say[:80])
        if not final_say and not steps:  # không bao giờ im lặng (e2e 2026-10-12: "tăng âm lượng" rỗng)
            await out.show(_SILENT)
    # trước khi chờ TTS (out.finish chờ tổng hợp hết): gửi sau thì island đã thu lại rồi bật lên giữa lúc đọc
    await ctx.flow_tracker.track("Hoàn thành", "completed")
    await out.finish()
    ctx.ws.last_turn = {"steps": steps, "final_say": final_say}
    if steps:  # sau stream_end: ngài không phải chờ; lỗi ghi DB không làm hỏng lượt
        from engine.turn import outcome
        try:
            await asyncio.to_thread(outcome.save_turn, text, steps, final_say,
                                    replay["id"] if replay else None,
                                    only is None and att is None and not _answers_question(ctx.conversation_history))
        except Exception as exc:
            log.warning("[TURN] lưu outcome/workflow lỗi: %s", exc)
    return out.text()

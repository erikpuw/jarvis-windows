"""Tests for engine.orchestrator.classifier. Run: python tests/test_orchestrator_classifier.py"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.orchestrator import classifier


def _fake_response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def test_classify_parses_valid_json_task_list():
    async def scenario():
        from engine.server import llm_server

        async def fake_inner(messages, model=None, thinking=False, stream=False,
                              tools=None, tool_choice=None, temperature=None,
                              max_tokens=None, response_format=None):
            return _fake_response('[{"agent": "email", "query": "kiem tra email"}, {"agent": "notes", "query": "ghi lai"}]')

        original = llm_server._call_llm_inner
        llm_server._call_llm_inner = fake_inner
        try:
            return await classifier.classify_tasks("kiem tra email roi ghi note lai", conversation_history=[])
        finally:
            llm_server._call_llm_inner = original

    tasks = asyncio.run(scenario())
    assert tasks == [
        {"agent": "email", "query": "kiem tra email"},
        {"agent": "notes", "query": "ghi lai"},
    ], tasks


def test_classify_strips_markdown_code_fence():
    async def scenario():
        from engine.server import llm_server

        async def fake_inner(messages, model=None, thinking=False, stream=False,
                              tools=None, tool_choice=None, temperature=None,
                              max_tokens=None, response_format=None):
            return _fake_response('```json\n[{"agent": "desktop", "query": "mo word"}]\n```')

        original = llm_server._call_llm_inner
        llm_server._call_llm_inner = fake_inner
        try:
            return await classifier.classify_tasks("mo word", conversation_history=[])
        finally:
            llm_server._call_llm_inner = original

    tasks = asyncio.run(scenario())
    assert tasks == [{"agent": "desktop", "query": "mo word"}], tasks


def test_classify_drops_unregistered_agent():
    async def scenario():
        from engine.server import llm_server

        async def fake_inner(messages, model=None, thinking=False, stream=False,
                              tools=None, tool_choice=None, temperature=None,
                              max_tokens=None, response_format=None):
            return _fake_response('[{"agent": "not_a_real_agent", "query": "x"}, {"agent": "news", "query": "gia vang"}]')

        original = llm_server._call_llm_inner
        llm_server._call_llm_inner = fake_inner
        try:
            return await classifier.classify_tasks("gia vang hom nay", conversation_history=[])
        finally:
            llm_server._call_llm_inner = original

    tasks = asyncio.run(scenario())
    assert tasks == [{"agent": "news", "query": "gia vang"}], tasks  # subset tokens accepted (spec F)


def test_classify_returns_empty_list_on_non_json():
    async def scenario():
        from engine.server import llm_server

        async def fake_inner(messages, model=None, thinking=False, stream=False,
                              tools=None, tool_choice=None, temperature=None,
                              max_tokens=None, response_format=None):
            return _fake_response("khong hieu yeu cau")

        original = llm_server._call_llm_inner
        llm_server._call_llm_inner = fake_inner
        try:
            return await classifier.classify_tasks("???", conversation_history=[])
        finally:
            llm_server._call_llm_inner = original

    tasks = asyncio.run(scenario())
    assert tasks == [], tasks


def test_classify_drops_non_string_agent_without_crashing():
    async def scenario():
        from engine.server import llm_server

        async def fake_inner(messages, model=None, thinking=False, stream=False,
                              tools=None, tool_choice=None, temperature=None,
                              max_tokens=None, response_format=None):
            return _fake_response('[{"agent": ["email"], "query": "x"}, {"agent": "news", "query": "gia vang"}]')

        original = llm_server._call_llm_inner
        llm_server._call_llm_inner = fake_inner
        try:
            return await classifier.classify_tasks("gia vang hom nay", conversation_history=[])
        finally:
            llm_server._call_llm_inner = original

    tasks = asyncio.run(scenario())
    assert tasks == [{"agent": "news", "query": "gia vang"}], tasks  # subset tokens accepted (spec F)


def test_classify_accepts_single_json_object():
    """Live eval: model answered {"agent": "history", ...} without the array."""
    assert classifier._parse_tasks('{"agent": "history", "query": "lịch sử trò chuyện"}') == [
        {"agent": "history", "query": "lịch sử trò chuyện"}
    ]
    assert classifier._parse_tasks('{"agent": "nope", "query": "x"}') == []
    assert classifier._parse_tasks("123") == []


def _run_with_captured_messages(llm_reply: str, user_text: str, history: list, **kwargs):
    """Runs classify_tasks with a fake LLM; returns (tasks, messages sent to the LLM)."""
    async def scenario():
        from engine.server import llm_server
        captured = {}

        async def fake_inner(messages, model=None, thinking=False, stream=False,
                              tools=None, tool_choice=None, temperature=None,
                              max_tokens=None, response_format=None):
            captured["messages"] = messages
            return _fake_response(llm_reply)

        original = llm_server._call_llm_inner
        llm_server._call_llm_inner = fake_inner
        try:
            tasks = await classifier.classify_tasks(user_text, conversation_history=history, **kwargs)
        finally:
            llm_server._call_llm_inner = original
        return tasks, captured["messages"]

    return asyncio.run(scenario())


def test_single_task_query_with_new_words_falls_back_to_user_text():
    """Design rule (user, 2026-09-23 & 2026-09-25 F):
    'mở fcleaner' bị viết lại thành 'mở Fences & Windows Cleaner (FCleaner)' có từ mới -> giữ nguyên.
    """
    tasks, _ = _run_with_captured_messages(
        '[{"agent": "desktop", "query": "mở Fences & Windows Cleaner (FCleaner)"}]', "mở fcleaner", [],
    )
    assert tasks == [{"agent": "desktop", "query": "mở fcleaner"}], tasks
    tasks, _ = _run_native(_native_reply(_tool_call("desktop", '{"query": "mở Fences & Windows Cleaner"}')), "mở fcleaner")
    assert tasks == [{"agent": "desktop", "query": "mở fcleaner"}], tasks


def test_wrapped_chat_command_accepts_model_query_when_subset_tokens():
    """Spec 2026-09-25 (F): Lệnh bọc trong câu chat:
    'tôi lười mở notepad quá, bạn có thể mở giúp tôi được không?'
    model rút gọn thành 'mở notepad' (chỉ bớt từ, không thêm, không dịch) -> nhận 'mở notepad'.
    """
    user = "tôi lười mở notepad quá, bạn có thể mở giúp tôi được không?"
    tasks, _ = _run_with_captured_messages('[{"agent": "desktop", "query": "mở notepad"}]', user, [])
    assert tasks == [{"agent": "desktop", "query": "mở notepad"}], tasks

    user2 = "bạn tìm tin tức về nvidia rtx spark có gì nổi bật không?"
    tasks2, _ = _run_with_captured_messages('[{"agent": "news", "query": "tìm tin tức nvidia rtx spark"}]', user2, [])
    assert tasks2 == [{"agent": "news", "query": "tìm tin tức nvidia rtx spark"}], tasks2


def test_drifted_query_falls_back_to_user_text():
    """Regression: model repeated the previous turn's agent and invented an email query for a price request."""
    user = "bạn tìm giá tổng hợp xem giúp tôi hôm nay có thay đổi không"
    tasks, _ = _run_with_captured_messages(
        '[{"agent": "email", "query": "Kiểm tra 10 email gần nhất"}]', user, [],
    )
    assert tasks == [{"agent": "email", "query": user}], tasks


def test_empty_or_non_string_query_falls_back_to_user_text():
    for bad in ('""', '["x"]', "null", "123"):
        tasks, _ = _run_with_captured_messages(
            '[{"agent": "news", "query": %s}]' % bad, "tìm tin tức bão số 5", [],
        )
        assert tasks == [{"agent": "news", "query": "tìm tin tức bão số 5"}], (bad, tasks)


def test_query_sharing_only_verbs_or_pronouns_is_not_on_topic():
    tasks, _ = _run_with_captured_messages(
        '[{"agent": "news", "query": "tìm giúp tôi thời tiết"}]',
        "bạn tìm giúp tôi tin tức bão", [],
    )
    assert tasks[0]["query"] == "bạn tìm giúp tôi tin tức bão", tasks


def test_confirmation_reply_correctly_resolved_by_model_is_still_clobbered():
    """GAP (2026-09-23, not yet fixed, code untouched): user confirms Jarvis's own
    suggestion with a content-free reply ("ừ"). Even when the model correctly reads
    the history and resolves this to "desktop / mở Notepad", _resolve_query has
    nothing in bare "ừ" to check that resolution against, so it discards the correct
    resolution and hands the agent literal "ừ" -- which agent_desktop's own keyword
    pre-filter (_select_desktop_tools/extract_app_name) will then decline outright,
    since "ừ" contains no open-verb keyword and no app name."""
    history = [
        {"role": "user", "content": "mở giúp tôi ứng dụng ghi chú"},
        {"role": "assistant", "content": "Bạn có muốn tôi mở luôn Notepad không?"},
    ]
    tasks, _ = _run_with_captured_messages(
        '[{"agent": "desktop", "query": "mở Notepad"}]', "ừ", history,
    )
    # Documents today's behavior: the correct resolution is thrown away.
    assert tasks == [{"agent": "desktop", "query": "ừ"}], tasks


def test_confirmation_reply_is_passed_verbatim_too():
    """Consequence of the verbatim rule, accepted 2026-09-23: "mở đi" after a Notepad
    suggestion used to be resolved by the model to "mở Notepad"; now the agent gets the
    user's words and the desktop agent declines (no app named) -> chat."""
    history = [
        {"role": "user", "content": "mở giúp tôi ứng dụng ghi chú"},
        {"role": "assistant", "content": "Bạn có muốn tôi mở luôn Notepad không?"},
    ]
    for reply in ("mở đi", "mở giúp tôi", "ừ mở đi"):
        tasks, _ = _run_with_captured_messages(
            '[{"agent": "desktop", "query": "mở Notepad"}]', reply, history,
        )
        assert tasks == [{"agent": "desktop", "query": reply}], (reply, tasks)


def test_confirmation_reply_guard_also_blocks_a_hallucinated_resolution():
    """Sanity check for why "just trust the model when user_text is content-free"
    is not a safe fix on its own: today, a WRONG resolution (unrelated to what
    Jarvis actually suggested) gets discarded exactly the same way a correct one
    does in the test above -- current code cannot tell them apart, because both
    only ever get compared against content-free "ừ", never against history. A
    fix must check the model's query against conversation history (the real
    source of a confirmation's topic), not against user_text alone or blindly."""
    history = [
        {"role": "user", "content": "mở giúp tôi ứng dụng ghi chú"},
        {"role": "assistant", "content": "Bạn có muốn tôi mở luôn Notepad không?"},
    ]
    tasks, _ = _run_with_captured_messages(
        '[{"agent": "email", "query": "Kiểm tra email mới"}]', "ừ", history,
    )
    assert tasks == [{"agent": "email", "query": "ừ"}], tasks


def test_multi_task_queries_are_left_untouched():
    tasks, _ = _run_with_captured_messages(
        '[{"agent": "email", "query": "kiem tra 10 email gan nhat"}, {"agent": "notes", "query": "ghi note noi dung email"}]',
        "kiem tra email roi ghi note",
        [],
    )
    assert [t["query"] for t in tasks] == ["kiem tra 10 email gan nhat", "ghi note noi dung email"], tasks


def test_follow_up_round_keeps_model_query():
    """With extra_context (round >= 2) the single-task query is a real sub-query."""
    tasks, _ = _run_with_captured_messages(
        '[{"agent": "news", "query": "bo sung gia vang"}]',
        "nghien cuu sau",
        [],
        extra_context="Đã có kết quả các vòng trước: ...",
    )
    assert tasks == [{"agent": "news", "query": "bo sung gia vang"}], tasks


def test_output_wrapped_in_think_block_or_prose_is_still_parsed():
    """Qwen leaks <think>…</think> or wraps the JSON in prose."""
    for reply in (
        '<think>user muốn tin tức</think>[{"agent": "news", "query": "tin tức bão số 5"}]',
        'Kết quả: [{"agent": "news", "query": "tin tức bão số 5"}] Hết.',
        '{"agent": "news", "query": "tin tức bão số 5"}',
    ):
        tasks, _ = _run_with_captured_messages(reply, "tìm tin tức bão số 5", [])
        assert tasks == [{"agent": "news", "query": "tin tức bão số 5"}], (reply, tasks)


def test_use_previous_flag_is_kept_only_when_a_real_true():
    reply = ('[{"agent": "email", "query": "kiểm tra email"}, '
             '{"agent": "notes", "query": "ghi note nội dung email", "use_previous": true}, '
             '{"agent": "news", "query": "tin bão", "use_previous": "yes"}]')
    tasks, _ = _run_with_captured_messages(reply, "kiểm tra email, ghi note, tìm tin bão", [])
    assert [t.get("use_previous") for t in tasks] == [None, True, None], tasks


def test_two_tasks_for_the_same_agent_are_merged_into_one():
    """Live Qwen split one security request into two security tasks."""
    assert classifier._parse_tasks(
        '[{"agent": "security", "query": "kiểm tra an ninh mạng"}, {"agent": "security", "query": "quét cổng"},'
        ' {"agent": "notes", "query": "ghi lại", "use_previous": true}]'
    ) == [
        {"agent": "security", "query": "kiểm tra an ninh mạng và quét cổng"},
        {"agent": "notes", "query": "ghi lại", "use_previous": True},
    ]
    assert classifier._parse_tasks(
        '[{"agent": "news", "query": "tin bão"}, {"agent": "news", "query": "tin bão"}]'
    ) == [{"agent": "news", "query": "tin bão"}]


def _tool_call(name, arguments):
    return SimpleNamespace(function=SimpleNamespace(name=name, arguments=arguments))


def _native_reply(*calls, content=""):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=list(calls)))])


def _run_native(reply, user_text, history=None, **kwargs):
    """classify_tasks against a fake server that answers with native tool_calls; returns (tasks, request kwargs)."""
    async def scenario():
        from engine.server import llm_server
        seen = {}

        async def fake_inner(messages, model=None, thinking=False, stream=False, tools=None,
                             tool_choice=None, temperature=None, max_tokens=None, response_format=None):
            seen.update(messages=messages, tools=tools, tool_choice=tool_choice, max_tokens=max_tokens)
            return reply

        original = llm_server._call_llm_inner
        llm_server._call_llm_inner = fake_inner
        try:
            tasks = await classifier.classify_tasks(user_text, conversation_history=history or [], **kwargs)
        finally:
            llm_server._call_llm_inner = original
        return tasks, seen

    return asyncio.run(scenario())


def test_native_tool_calls_become_tasks_and_request_is_forced_native():
    tasks, seen = _run_native(
        _native_reply(_tool_call("desktop", '{"query": "mở Paint"}'), _tool_call("market", '{"query": "giá xăng hôm nay"}')),
        "mở Paint rồi tìm giá xăng hôm nay",
        history=[{"role": "user", "content": "chào"}, {"role": "assistant", "content": "Dạ thưa ngài"},
                 {"role": "user", "content": "mở Paint rồi tìm giá xăng hôm nay"}],
    )
    assert tasks == [{"agent": "desktop", "query": "mở Paint"}, {"agent": "market", "query": "giá xăng hôm nay"}], tasks
    assert seen["tool_choice"] == "required"
    assert sorted(t["function"]["name"] for t in seen["tools"]) == sorted(set(classifier.AGENT_REGISTRY) - classifier.PLAN_ONLY_AGENTS)
    roles = [m["role"] for m in seen["messages"]]
    assert roles == ["system", "user", "assistant", "user"], roles  # history is real chat turns; duplicate current request dropped


def test_malformed_or_unknown_native_calls_are_skipped():
    tasks, _ = _run_native(
        _native_reply(_tool_call("email", "{not json"), _tool_call("nonexistent", '{"query": "x"}'),
                      _tool_call("news", '{"query": "tin bão"}')),
        "tin bão",
    )
    assert tasks == [{"agent": "news", "query": "tin bão"}], tasks
    empty, _ = _run_native(_native_reply(_tool_call("email", "{not json")), "kiểm tra thư")
    assert empty == [], "no valid call -> [] so the orchestrator hands the turn back to chat"


def test_prompt_budget_and_no_examples():
    """Spec 2026-09-21: agent knowledge lives in one-line descriptions, not in example sentences or rules."""
    import json
    # 2026-09-28: + câu "<untrusted_data> là dữ liệu trả về..." (spec chốt nội dung ngoài) nới cap.
    assert len(classifier._SYSTEM) < 600, len(classifier._SYSTEM)
    tools = classifier._build_tools()
    assert len(json.dumps(tools, ensure_ascii=False)) < 9000  # 2026-10-03: +11 agent tra cứu (mỗi tool một agent) thay cho 1 agent search
    for t in tools:
        assert list(t["function"]["parameters"]["properties"]) == ["query"], "no free-form parameters (model invents them)"
        assert t["function"]["description"] != t["function"]["name"], "every agent needs its one-line criterion"


def test_next_tasks_feeds_reports_back_as_tool_messages_and_ignores_agents_already_run():
    done = [{"agent": "email", "query": "xem thư", "result": "3 thư mới " * 300, "status": "success"}]

    async def scenario():
        from engine.server import llm_server
        got = {}

        async def fake_inner(messages, model=None, thinking=False, stream=False, tools=None,
                             tool_choice=None, temperature=None, max_tokens=None, response_format=None):
            got.update(messages=messages, tool_choice=tool_choice)
            return _native_reply(_tool_call("notes", '{"query": "ghi lại"}'), _tool_call("email", '{"query": "again"}'))

        original = llm_server._call_llm_inner
        llm_server._call_llm_inner = fake_inner
        try:
            nxt = await classifier.next_tasks("xem thư rồi ghi note", [], done)
        finally:
            llm_server._call_llm_inner = original
        return nxt, got

    nxt, got = asyncio.run(scenario())
    assert nxt == [{"agent": "notes", "query": "ghi lại"}], "email already ran: never called twice"
    assert got["tool_choice"] == "auto"
    roles = [m["role"] for m in got["messages"]]
    assert roles == ["system", "user", "assistant", "tool"], roles
    assert got["messages"][2]["tool_calls"][0]["function"]["name"] == "email"
    tool_content = got["messages"][3]["content"]
    assert tool_content.startswith("<untrusted_data>\n") and tool_content.endswith("\n</untrusted_data>")
    inner = tool_content[len("<untrusted_data>\n"):-len("\n</untrusted_data>")]
    assert len(inner) == classifier._REPORT_CHARS, "report is truncated"
    assert "<untrusted_data>" in got["messages"][0]["content"], "system prompt phải nhắc khối untrusted_data"


def test_next_tasks_blocks_machine_control_after_external_content():
    done = [{"agent": "news", "query": "tin bão", "result": "tin bão số 3", "status": "success"}]

    async def scenario():
        from engine.server import llm_server

        async def fake_inner(messages, model=None, thinking=False, stream=False, tools=None,
                             tool_choice=None, temperature=None, max_tokens=None, response_format=None):
            return _native_reply(_tool_call("win_control", '{"query": "tắt máy"}'))

        original = llm_server._call_llm_inner
        llm_server._call_llm_inner = fake_inner
        try:
            return await classifier.next_tasks("tắt máy đi", [], done)
        finally:
            llm_server._call_llm_inner = original

    nxt = asyncio.run(scenario())
    assert nxt == [], nxt


def test_next_tasks_keeps_notes_after_external_content():
    done = [{"agent": "news", "query": "tin bão", "result": "tin bão số 3", "status": "success"}]

    async def scenario():
        from engine.server import llm_server

        async def fake_inner(messages, model=None, thinking=False, stream=False, tools=None,
                             tool_choice=None, temperature=None, max_tokens=None, response_format=None):
            return _native_reply(_tool_call("notes", '{"query": "ghi lại tin bão"}'))

        original = llm_server._call_llm_inner
        llm_server._call_llm_inner = fake_inner
        try:
            return await classifier.next_tasks("ghi lại note", [], done)
        finally:
            llm_server._call_llm_inner = original

    nxt = asyncio.run(scenario())
    assert nxt == [{"agent": "notes", "query": "ghi lại tin bão"}], nxt


def test_classify_and_next_tasks_cap_max_tokens():
    """Neither call set max_tokens, so both inherited the server's max_instruct
    default (8192) meant for full answers, not a 1-2 word classification --
    unbounded headroom for a confused/looping small model. Both calls must pass
    an explicit, small cap."""
    _, seen = _run_native(_native_reply(_tool_call("news", '{"query": "tin bao"}')), "tin bao")
    assert seen["max_tokens"] is not None and seen["max_tokens"] <= 300, seen["max_tokens"]

    async def scenario():
        from engine.server import llm_server
        seen_next = {}

        async def fake_inner(messages, model=None, thinking=False, stream=False, tools=None,
                             tool_choice=None, temperature=None, max_tokens=None, response_format=None):
            seen_next["max_tokens"] = max_tokens
            return _native_reply()

        original = llm_server._call_llm_inner
        llm_server._call_llm_inner = fake_inner
        try:
            await classifier.next_tasks("x", [], [{"agent": "email", "query": "q", "result": "r", "status": "success"}])
        finally:
            llm_server._call_llm_inner = original
        return seen_next

    seen_next = asyncio.run(scenario())
    assert seen_next["max_tokens"] is not None and seen_next["max_tokens"] <= 300, seen_next["max_tokens"]


def test_next_tasks_never_raises():
    async def scenario():
        from engine.server import llm_server

        async def boom(*a, **k):
            raise RuntimeError("server down")

        original = llm_server._call_llm_inner
        llm_server._call_llm_inner = boom
        try:
            return await classifier.next_tasks("x", [], [{"agent": "email", "query": "q", "result": "r", "status": "success"}])
        finally:
            llm_server._call_llm_inner = original

    assert asyncio.run(scenario()) == []


def test_offer_context_with_own_content_takes_user_text():
    """Task 19: offer pending + user says "mở fcleaner", model returns "mở Notepad"
    → query should be "mở fcleaner" (user's own object)."""
    user = "mở fcleaner"
    offer = "Bạn có muốn tôi mở luôn Notepad không?"
    tasks, _ = _run_with_captured_messages(
        '[{"agent": "desktop", "query": "mở Notepad"}]', user, [], offer_context=offer
    )
    # With offer_context, single-task guard runs; user text has "fcleaner" (own content)
    # → should return user's text verbatim, not model's "Notepad"
    assert tasks == [{"agent": "desktop", "query": "mở fcleaner"}], tasks


def test_offer_context_with_affirm_only_takes_model_query():
    """Task 19: offer pending + user says "ừ mở notepad lại cho tôi",
    model returns "mở Notepad" → query should be "mở Notepad" (affirm + trusted)."""
    user = "ừ mở notepad lại cho tôi"
    offer = "Bạn có muốn tôi mở luôn Notepad không?"
    tasks, _ = _run_with_captured_messages(
        '[{"agent": "desktop", "query": "mở Notepad"}]', user, [], offer_context=offer
    )
    # With offer_context, user text contains only affirm words + model query words
    # → should return model's query (trusted because it matches offer topic)
    assert tasks == [{"agent": "desktop", "query": "mở Notepad"}], tasks


def test_offer_reply_query_sharing_only_verbs_is_not_trusted():
    """Live 2026-09-25: offer 'mở Notepad', user 'ừ mở lại cho tôi', model 'mở lại' — chỉ trùng động từ
    với lời đề nghị → không tin; và không bao giờ đưa nguyên đoạn offer_context xuống agent."""
    user = "ừ mở lại cho tôi"
    offer = "Lượt trước Jarvis đã đề nghị (chưa làm): Ngài có muốn tôi mở ứng dụng Notepad không? [công cụ: open_app]."
    tasks, _ = _run_with_captured_messages(
        '[{"agent": "desktop", "query": "mở lại"}]', user, [], offer_context=offer
    )
    assert tasks == [{"agent": "desktop", "query": user}], tasks


def test_offer_context_does_not_affect_extra_context_guard():
    """Task 19: offer_context should not disable the round-1 guard.
    Only extra_context (round >= 2) should disable it."""
    user = "tra giá vàng"
    tasks, _ = _run_with_captured_messages(
        '[{"agent": "news", "query": "tra giá vàng hôm nay"}]', user, [],
        offer_context="Offer text", extra_context=""
    )
    # Round 1: extra_context is empty, so guard is active
    # Single task: should return user's verbatim text
    assert tasks == [{"agent": "news", "query": "tra giá vàng"}], tasks


if __name__ == "__main__":
    test_single_task_query_with_new_words_falls_back_to_user_text()
    test_wrapped_chat_command_accepts_model_query_when_subset_tokens()
    test_drifted_query_falls_back_to_user_text()
    test_empty_or_non_string_query_falls_back_to_user_text()
    test_query_sharing_only_verbs_or_pronouns_is_not_on_topic()
    test_confirmation_reply_correctly_resolved_by_model_is_still_clobbered()
    test_confirmation_reply_is_passed_verbatim_too()
    test_confirmation_reply_guard_also_blocks_a_hallucinated_resolution()
    test_multi_task_queries_are_left_untouched()
    test_follow_up_round_keeps_model_query()
    test_native_tool_calls_become_tasks_and_request_is_forced_native()
    test_malformed_or_unknown_native_calls_are_skipped()
    test_prompt_budget_and_no_examples()
    test_classify_and_next_tasks_cap_max_tokens()
    test_classify_parses_valid_json_task_list()
    test_classify_strips_markdown_code_fence()
    test_classify_drops_unregistered_agent()
    test_classify_returns_empty_list_on_non_json()
    test_classify_drops_non_string_agent_without_crashing()
    test_classify_accepts_single_json_object()
    test_output_wrapped_in_think_block_or_prose_is_still_parsed()
    test_use_previous_flag_is_kept_only_when_a_real_true()
    test_two_tasks_for_the_same_agent_are_merged_into_one()
    test_next_tasks_feeds_reports_back_as_tool_messages_and_ignores_agents_already_run()
    test_next_tasks_never_raises()
    test_offer_context_with_own_content_takes_user_text()
    test_offer_context_with_affirm_only_takes_model_query()
    test_offer_context_does_not_affect_extra_context_guard()
    print("OK: all orchestrator classifier tests passed")


def test_hyphenated_name_counts_as_one_token():
    """Model viết 'Sơn Tùng M-TP' khi ngài gõ 'mtp': vẫn chỉ là bớt từ, phải nhận bản rút gọn (log 2026-09-25 15:23)."""
    from engine.orchestrator.classifier import _content_tokens
    q = _content_tokens("nghe Making My Way Sơn Tùng M-TP")
    assert q <= _content_tokens("tôi muốn nghe nhạc making my way của sơn tùng mtp")

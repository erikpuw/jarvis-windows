"""Gmail chỉ đọc (ngài đồng ý 2026-10-13): hub chặn bằng code mọi tool gmail ngoài search_emails/read_email,
search_emails tối đa 10 mail; tool check_mail chỉ gọi hai tool đó.
Run: python -m pytest tests/test_gmail_readonly.py -q"""
import asyncio
from types import SimpleNamespace

import pytest

from engine.server.mcp_server import MCPHub
from engine.tools import registry as R


class _Session:
    def __init__(self):
        self.calls = []

    async def call_tool(self, tool, args):
        self.calls.append((tool, dict(args)))
        return SimpleNamespace(content=[], isError=False, structuredContent={})


def _hub():
    hub = MCPHub.__new__(MCPHub)
    hub.sessions = {"gmail": _Session(), "wikipedia-vi": _Session()}
    return hub


@pytest.mark.parametrize("tool", ["send_email", "draft_email", "modify_email", "delete_email", "batch_modify_emails",
                                  "batch_delete_emails", "create_label", "delete_label", "create_filter",
                                  "download_attachment"])
def test_gmail_tools_outside_allowlist_are_blocked(tool):
    hub = _hub()
    with pytest.raises(PermissionError):
        asyncio.run(hub.call_tool("gmail", tool, {"to": ["x@y.z"]}))
    assert hub.sessions["gmail"].calls == []


def test_search_emails_capped_at_10_and_read_allowed():
    hub = _hub()
    asyncio.run(hub.call_tool("gmail", "search_emails", {"query": "in:inbox", "maxResults": 500}))
    asyncio.run(hub.call_tool("gmail", "search_emails", {"query": "in:inbox"}))
    asyncio.run(hub.call_tool("gmail", "read_email", {"messageId": "abc"}))
    asyncio.run(hub.call_tool("wikipedia-vi", "get_summary", {"title": "x"}))  # server khác không bị ảnh hưởng
    assert hub.sessions["gmail"].calls == [("search_emails", {"query": "in:inbox", "maxResults": 10}),
                                           ("search_emails", {"query": "in:inbox", "maxResults": 10}),
                                           ("read_email", {"messageId": "abc"})]
    assert hub.sessions["wikipedia-vi"].calls == [("get_summary", {"title": "x"})]


def _text_result(text):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], isError=False, structuredContent=None)


def test_check_mail_lists_inbox_by_default_and_reads_one(monkeypatch):
    calls = []

    class _Hub:
        def get_stats(self):
            return {"servers": {"gmail": "connected"}}

        async def call_tool(self, srv, tool, args):
            calls.append((srv, tool, dict(args)))
            return _text_result("ID: 1\nSubject: Chào\nFrom: a@b.c")
    monkeypatch.setattr("engine.server.mcp_server.get_mcp_hub", lambda: _Hub())
    assert R.kind("check_mail") == "read"
    res = asyncio.run(R.run("check_mail", {}))
    assert res.outcome == "success" and "Subject: Chào" in res.text
    asyncio.run(R.run("check_mail", {"message_id": "1"}))
    assert calls == [("gmail", "search_emails", {"query": "in:inbox", "maxResults": 10}),
                     ("gmail", "read_email", {"messageId": "1"})]


def test_check_mail_when_gmail_not_connected(monkeypatch):
    class _Hub:
        def get_stats(self):
            return {"servers": {}}
    monkeypatch.setattr("engine.server.mcp_server.get_mcp_hub", lambda: _Hub())
    res = asyncio.run(R.run("check_mail", {}))
    assert res.outcome == "failed" and "Gmail" in res.text

def test_check_mail_permission_isolation_for_member():
    from engine.core.session_context import set_current_user_id
    from engine.server.slash_commands import resolve_slash_command, format_tools_help

    try:
        # 1. Member user
        set_current_user_id("user-member-test")

        # Hub call_tool directly blocked
        hub = _hub()
        with pytest.raises(PermissionError) as exc_info:
            asyncio.run(hub.call_tool("gmail", "search_emails", {"query": "in:inbox"}))
        assert "Chỉ Quản trị viên" in str(exc_info.value)

        # registry.run("check_mail") blocked
        ctx_mem = R.ToolContext()
        ctx_mem.user_id = "user-member-test"
        res = asyncio.run(R.run("check_mail", {}, ctx=ctx_mem))
        assert res.outcome == "failed"
        assert "Chỉ Quản trị viên" in res.text

        # registry.chat_names filters out check_mail
        mem_tools = R.chat_names(user_id="user-member-test")
        assert "check_mail" not in mem_tools

        # Admin includes check_mail
        adm_tools = R.chat_names(user_id="admin")
        assert "check_mail" in adm_tools

        # Slash command /check_mail: như không có lệnh (không lộ tool tồn tại, ngài 2026-10-24)
        slash_res = resolve_slash_command("/check_mail", user_id="user-member-test")
        assert slash_res["kind"] == "not_found"
        assert "Chỉ Quản trị viên" not in slash_res["text"]

        # format_tools_help filters out check_mail for member
        help_mem = format_tools_help(user_id="user-member-test")
        assert "/check_mail" not in help_mem

        help_adm = format_tools_help(user_id="admin")
        assert "/check_mail" in help_adm

        # mcp_call tool is also admin_only
        res_mcp = asyncio.run(R.run("mcp_call", {"server": "gmail", "tool": "search_emails"}, ctx=ctx_mem))
        assert res_mcp.outcome == "failed"
        assert "Chỉ Quản trị viên" in res_mcp.text

    finally:
        set_current_user_id("admin")

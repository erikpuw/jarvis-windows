"""Tests for engine.tools.office_tools officecli handling. Run: python -m pytest tests/test_office_tools.py"""
import asyncio
import socket
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.tools import office_tools as ot

BATCH_OK = '```json\n[{"command": "add", "parent": "/body", "type": "paragraph", "props": {"text": "Hi"}}]\n```'


class FakeWs:
    def __init__(self):
        self.sent = []

    async def send_json(self, data):
        self.sent.append(data)


class Harness:
    """Fake LLM + fake officecli runner + fake watch process."""

    def __init__(self, monkeypatch, llm_text=BATCH_OK, rc_by_verb=None):
        self.calls = []
        self.popen = []
        self.rc_by_verb = rc_by_verb or {}

        async def fake_llm(*a, **k):
            msg = types.SimpleNamespace(content=llm_text)
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])

        llm_mod = types.ModuleType("engine.server.llm_server")
        llm_mod.call_llm = fake_llm
        monkeypatch.setitem(sys.modules, "engine.server.llm_server", llm_mod)

        async def fake_run(*args, timeout=120):
            self.calls.append(args)
            rcs = self.rc_by_verb.get(args[0])
            rc = rcs.pop(0) if isinstance(rcs, list) and rcs else (rcs if isinstance(rcs, int) else 0)
            return rc, "{}", "boom" if rc else ""

        monkeypatch.setattr(ot, "_run_officecli", fake_run)
        monkeypatch.setattr(ot, "_previewed_path", None)
        monkeypatch.setattr(ot.subprocess, "Popen", lambda cmd, **kw: self.popen.append(cmd))

        async def no_shell(*a, **k):
            raise AssertionError("shell must never be used for LLM output")

        monkeypatch.setattr(ot.asyncio, "create_subprocess_shell", no_shell)

    def verbs(self):
        return [c[0] for c in self.calls]

    def run(self, path, ws=None):
        return asyncio.run(ot.handle_office_command("tạo tài liệu", filepath=str(path), ws=ws))


def test_bash_output_from_llm_is_rejected_not_executed(monkeypatch, tmp_path):
    h = Harness(monkeypatch, llm_text="```bash\nofficecli create OUTPUT_PATH\ncalc.exe\n```")
    out = h.run(tmp_path / "a.docx")
    assert out.startswith("Lỗi")
    assert "batch" not in h.verbs()
    assert h.popen == []


def test_create_failure_is_retried_once_then_succeeds(monkeypatch, tmp_path):
    h = Harness(monkeypatch, rc_by_verb={"create": [1, 0]})
    out = h.run(tmp_path / "a.docx")
    assert h.verbs().count("create") == 2
    assert "batch" in h.verbs()
    assert "Đã xử lý xong tài liệu" in out and "a.docx" in out


def test_create_failure_twice_reports_error_without_batch(monkeypatch, tmp_path):
    h = Harness(monkeypatch, rc_by_verb={"create": 1})
    out = h.run(tmp_path / "a.docx")
    assert out.startswith("Lỗi")
    assert "batch" not in h.verbs()


def test_success_closes_file_and_starts_watch_on_explicit_port(monkeypatch, tmp_path):
    h = Harness(monkeypatch)
    ws = FakeWs()
    target = tmp_path / "a.docx"
    out = h.run(target, ws=ws)
    assert "close" in h.verbs()
    assert h.verbs().index("close") > h.verbs().index("batch")
    assert len(h.popen) == 1
    cmd = h.popen[0]
    assert cmd[:2] == ["officecli", "watch"] and "--port" in cmd
    port = cmd[cmd.index("--port") + 1]
    assert f"localhost:{port}" in ws.sent[-1]["text"]
    # Câu trả lời chỉ nêu tên tệp, không lộ đường dẫn máy chủ.
    assert target.name in out
    assert str(tmp_path) not in out


def test_batch_failure_still_closes_and_skips_preview(monkeypatch, tmp_path):
    h = Harness(monkeypatch, rc_by_verb={"batch": 1})
    out = h.run(tmp_path / "a.docx")
    assert "officecli báo lỗi" in out
    assert "close" in h.verbs()
    assert h.popen == []


def test_new_preview_unwatches_the_previous_file(monkeypatch, tmp_path):
    h = Harness(monkeypatch)
    first, second = tmp_path / "a.docx", tmp_path / "b.docx"
    h.run(first)
    h.run(second)
    unwatch = [c for c in h.calls if c[0] == "unwatch"]
    assert unwatch and unwatch[-1][1] == str(first)
    assert len(h.popen) == 2


def test_preview_falls_back_to_free_port_when_default_is_busy(monkeypatch, tmp_path):
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    busy.listen(1)
    try:
        monkeypatch.setattr(ot, "PREVIEW_PORT", busy.getsockname()[1])
        h = Harness(monkeypatch)
        h.run(tmp_path / "a.docx")
        cmd = h.popen[0]
        assert cmd[cmd.index("--port") + 1] != str(busy.getsockname()[1])
    finally:
        busy.close()


def test_success_delivers_the_document_to_the_frontend(monkeypatch, tmp_path):
    """Tài liệu officecli tạo ra phải về frontend dạng document để tải về."""
    h = Harness(monkeypatch)
    ws = FakeWs()
    target = tmp_path / "bao_cao.docx"
    h.run(target, ws=ws)

    files = [m for m in ws.sent if m.get("type") == "output_file"]
    assert files, ws.sent
    assert files[0]["kind"] == "document"
    assert files[0]["path"] == str(target)
    assert files[0]["name"] == "bao_cao.docx"


def test_preview_text_still_comes_after_the_file_event(monkeypatch, tmp_path):
    """Giữ contract cũ: ws.sent[-1] vẫn là text_chunk preview (test cũ dựa vào đây)."""
    h = Harness(monkeypatch)
    ws = FakeWs()
    h.run(tmp_path / "a.docx", ws=ws)
    assert ws.sent[-1]["type"] == "text_chunk"
    assert "localhost:" in ws.sent[-1]["text"]


def test_failed_batch_does_not_deliver_any_file(monkeypatch, tmp_path):
    h = Harness(monkeypatch, rc_by_verb={"batch": 1})
    ws = FakeWs()
    h.run(tmp_path / "a.docx", ws=ws)
    assert [m for m in ws.sent if m.get("type") == "output_file"] == []

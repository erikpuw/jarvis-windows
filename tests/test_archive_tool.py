"""Tệp nén đính kèm (2026-09-28): đúng 1 tệp xử lý được → thay tệp đính kèm bằng tệp đó; nhiều/không có → nói rõ.
Tệp nén thật: zipfile, bsdtar (C:\\Windows\\System32\\tar.exe), Rar.exe của WinRAR (bỏ qua nếu không có)."""
import asyncio
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.core.attachment_store import DEFAULT_UPLOAD_ROOT, register_attachment
from engine.turn import archive as RA
from engine.turn.context import TurnContext
from engine.tools import archive_tool

RAR_EXE = Path(r"C:\Program Files\WinRAR\Rar.exe")


@pytest.fixture
def box():
    d = DEFAULT_UPLOAD_ROOT / "_test_archive"
    shutil.rmtree(d, ignore_errors=True)
    (d / "src").mkdir(parents=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _zip(box, name, files):
    p = box / name
    with zipfile.ZipFile(p, "w") as z:
        for arc, data in files.items():
            z.writestr(arc, data)
    return p


def _turn(path):
    said = []

    async def send(ws, data):
        said.append(data)
        return True
    att = register_attachment(path, filename=path.name, channel="webui")
    ctx = TurnContext(ws=object(), send_json=send, attachment_context=att)
    return ctx, asyncio.run(RA.unpack_archive(ctx))


def test_single_document_replaces_the_attachment(box):
    ctx, msg = _turn(_zip(box, "a.zip", {"docs/bao cao.pdf": b"%PDF-1.4", "docs/": b""}))
    assert msg is None
    assert ctx.attachment_context.extension == ".pdf" and ctx.attachment_context.filename == "bao cao.pdf"
    assert ctx.attachment_context.resolved_path.read_bytes() == b"%PDF-1.4"


def test_many_files_stop_and_list_names(box):
    ctx, msg = _turn(_zip(box, "b.zip", {"a.pdf": b"1", "b.docx": b"2", "c.png": b"3"}))
    assert msg and "3 tệp" in msg and "a.pdf" in msg and "c.png" in msg
    assert ctx.attachment_context.extension == ".zip"


def test_nothing_processable(box):
    ctx, msg = _turn(_zip(box, "c.zip", {"setup.exe": b"MZ", "inner.zip": b"PK"}))
    assert msg and "không chứa" in msg and "setup.exe" in msg


def test_path_traversal_member_is_never_extracted(box):
    ctx, msg = _turn(_zip(box, "d.zip", {"../evil.pdf": b"x"}))
    assert msg and "không chứa" in msg
    assert not (box / "evil.pdf").exists() and not (DEFAULT_UPLOAD_ROOT / "evil.pdf").exists()


def test_limits(box, monkeypatch):
    monkeypatch.setattr(archive_tool, "MAX_ENTRIES", 2)
    _, msg = _turn(_zip(box, "e.zip", {"a.txt": b"1", "b.bin": b"2", "c.bin": b"3"}))
    assert msg and "quá nhiều" in msg
    monkeypatch.setattr(archive_tool, "MAX_ENTRIES", 200)
    monkeypatch.setattr(archive_tool, "MAX_BYTES", 5)
    _, msg = _turn(_zip(box, "f.zip", {"big.txt": b"0123456789"}))
    assert msg and "quá lớn" in msg


def test_7z_single_file(box):
    (box / "src" / "ghi chu.txt").write_text("xin chao", encoding="utf-8")
    out = box / "g.7z"
    subprocess.run([archive_tool.tar_exe(), "-a", "-cf", str(out), "-C", str(box / "src"), "."], check=True)
    ctx, msg = _turn(out)
    assert msg is None and ctx.attachment_context.filename == "ghi chu.txt"


@pytest.mark.skipif(not RAR_EXE.exists(), reason="WinRAR Rar.exe không có")
def test_rar_single_file(box):
    (box / "src" / "anh.png").write_bytes(b"\x89PNG")
    out = box / "h.rar"
    subprocess.run([str(RAR_EXE), "a", "-ep1", "-idq", str(out), str(box / "src" / "anh.png")], check=True)
    ctx, msg = _turn(out)
    assert msg is None and ctx.attachment_context.extension == ".png"


def test_not_an_archive_is_untouched(box):
    p = box / "x.pdf"
    p.write_bytes(b"%PDF")
    ctx, msg = _turn(p)
    assert msg is None and ctx.attachment_context.filename == "x.pdf"


def test_handle_turn_unpacks_before_loop(box, monkeypatch):
    from types import SimpleNamespace
    from engine.turn import entry as E
    seen = {}

    async def fake_loop(text, ctx, only=None):
        seen["ext"] = ctx.attachment_context.extension
        return "OK"
    monkeypatch.setattr("engine.turn.loop.run_loop", fake_loop)
    one = _zip(box, "i.zip", {"x.pdf": b"%PDF"})
    ctx = TurnContext(ws=SimpleNamespace(forced_command=None), send_json=lambda *a: asyncio.sleep(0),
                      attachment_context=register_attachment(one, filename="i.zip", channel="webui"))
    assert asyncio.run(E.handle_turn("lưu trữ dữ liệu", ctx)) == "OK" and seen["ext"] == ".pdf"

    seen.clear()
    many = _zip(box, "j.zip", {"a.pdf": b"1", "b.png": b"2"})
    ctx = TurnContext(ws=SimpleNamespace(forced_command=None), send_json=lambda *a: asyncio.sleep(0),
                      attachment_context=register_attachment(many, filename="j.zip", channel="webui"))
    res = asyncio.run(E.handle_turn("lưu trữ dữ liệu", ctx))
    assert "gửi từng tệp" in res and not seen  # vòng lặp không chạy

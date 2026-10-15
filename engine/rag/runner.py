"""Điểm vào của router cho kind "rag". Lệnh con cố định, không để LLM đoán tìm hay lưu."""
import asyncio
import hashlib
import logging
import os
import shutil
import time
import unicodedata
from pathlib import Path

from engine.core import rag_watcher

log = logging.getLogger("jarvis.rag.runner")


def _docs(chunks) -> list[dict]:
    """Tài liệu trong kho theo thứ tự xuất hiện đầu tiên, gộp theo tệp: [{name, path, chunks}]."""
    docs: dict[str, dict] = {}
    for c in chunks:
        key = c.get("file_path") or c.get("filename", "")
        d = docs.setdefault(key, {"name": c.get("filename", ""), "path": c.get("file_path", ""), "chunks": 0})
        d["chunks"] += 1
    return list(docs.values())


def _help_text() -> str:
    from engine.core.rag_engine import get_rag_engine
    rag = get_rag_engine()
    doc_count = len(_docs(rag.chunks))
    chunk_count = len(rag.chunks)
    stats = f" (Hiện có {doc_count} tài liệu, {chunk_count} đoạn trong kho)" if doc_count > 0 else " (Kho hiện đang trống)"

    return (
        f"📚 **Kho Tri Thức & Tài Liệu (@rag)**{stats}:\n\n"
        "• **Tra cứu tài liệu:** `@rag <câu hỏi>`\n"
        "  *Ví dụ:* `@rag thực đơn 7 ngày`, `@rag lịch tập gym`\n"
        "• **Xem danh sách tài liệu:** `@rag danh sách`\n"
        "• **Nạp thêm tài liệu:**\n"
        "  - Thả file (.pdf, .docx, .pptx, .xlsx, .txt, .md, .csv, .html) vào thư mục `data/wiki/Documents/` (tự động nạp ngầm).\n"
        "  - Hoặc đính kèm file trong chat và gõ `@rag lưu`.\n"
        "• **Xóa tài liệu:** `@rag xóa <số thứ tự hoặc tên file>` (tệp gốc được chuyển vào thùng rác của vault)"
    )


EMPTY = 'Kho tài liệu đang trống. Thả file vào thư mục data/wiki/Documents hoặc đính kèm tệp và nói "@rag lưu" để thêm.'
NO_MATCH = "Không tìm thấy nội dung phù hợp trong kho tài liệu."
NO_EMBED = "Embedding service chưa sẵn sàng để tìm trong kho tài liệu."
# ponytail: ngưỡng hybrid_score cố định; chunk không liên quan đứng ~0.16 (chỉ có điểm vị trí/độ dài).
# Chỉnh qua RAG_MIN_SCORE khi đổi model embedding hoặc công thức rerank.
MIN_SCORE = float(os.getenv("RAG_MIN_SCORE", "0.2"))

_DELETE_WORDS = {"xóa", "xoá"}


def parse(query: str, has_attachment: bool) -> tuple[str, str]:
    """-> (action, arg). 'lưu' chỉ là lệnh khi có tệp; 'xóa' chỉ khi sau đó là một số/từ, hoặc một tên tệp có đuôi hợp lệ."""
    q = unicodedata.normalize("NFC", " ".join(str(query or "").split()))
    low = q.lower()
    if not q:
        return "help", ""
    if low == "danh sách":
        return "list", ""
    head, _, rest = q.partition(" ")
    if head.lower() in _DELETE_WORDS and (
        len(rest.split()) <= 1 or Path(rest).suffix.lower() in rag_watcher.SUPPORTED_EXTENSIONS
    ):
        return "delete", rest
    if has_attachment and head.lower() == "lưu":
        return "save", rest
    return "ask", q


async def _say(ctx, text: str) -> str:
    if ctx and getattr(ctx, "send_json", None) and getattr(ctx, "ws", None):
        await ctx.send_json(ctx.ws, {"type": "text_chunk", "text": text})
        await ctx.send_json(ctx.ws, {"type": "stream_end"})
    return text


async def handle(d, ctx) -> str:
    att = ctx.attachment_context
    action, arg = parse(d.query, att is not None)
    try:
        if action == "help":
            text = _help_text()
        elif action == "list":
            text = _list()
        elif action == "delete":
            text = await _delete(arg)
        elif action == "save":
            text = await save_document(att)
        elif att is not None:
            # Hỏi về chính tệp đang đính kèm: giữ luồng đọc tệp sẵn có.
            from engine.tools.rag_tool import handle_rag_query
            text = (await handle_rag_query(query=arg, attachment_context=att))["text"]
        else:
            return await _ask(arg, ctx=ctx)
    except Exception as exc:
        log.exception("[RAG] failed")
        text = f"Kho tài liệu gặp lỗi: {exc}"
    return await _say(ctx, text)


async def _engine():
    from engine.core.rag_engine import get_rag_engine
    from engine.server.llm_server import get_embed_client
    rag = get_rag_engine()
    await rag.try_self_heal(get_embed_client())
    return rag


async def _ask(query: str, ctx=None) -> str:
    rag = await _engine()
    if not rag.chunks:
        return await _say(ctx, EMPTY)
    if rag.embed_client is None:
        return await _say(ctx, NO_EMBED)
    chunks = await rag.retrieve(query=query, top_k=5, max_tokens=4000, min_score=MIN_SCORE)
    if not chunks:
        return await _say(ctx, NO_MATCH)

    evidence = "\n\n---\n\n".join(f"[Đoạn {i + 1}]\n{c['content']}" for i, c in enumerate(chunks))
    from engine.rag import summary
    from engine.server import llm_server
    messages = summary.answer_messages(query, evidence, "kho tài liệu")

    sources = []
    for c in chunks:
        page = c.get("page_number")
        label = f"{c.get('filename', '')} (trang {page})" if page else c.get("filename", "")
        if label not in sources:
            sources.append(label)
    sources_text = ("\n\nNguồn: " + "; ".join(sources)) if sources else ""

    # Stream thời gian thực ra WebSocket nếu có TurnContext hợp lệ
    if ctx and getattr(ctx, "ws", None) and getattr(ctx, "send_json", None):
        try:
            response = await llm_server.call_llm(
                messages=messages,
                stream=True,
                **summary.ANSWER_KW,
            )
            if hasattr(response, "__aiter__"):
                full_content = ""
                streamer = None
                splitter = None
                try:
                    from engine.server.voice_streamer import VoiceStreamer
                    from engine.server.text_streamer import SentenceSplitter
                    streamer = VoiceStreamer(ctx.ws)
                    worker_task = streamer.start()
                    if getattr(ctx, "background_tasks", None) is not None:
                        ctx.background_tasks.add(worker_task)
                        worker_task.add_done_callback(ctx.background_tasks.discard)
                    splitter = SentenceSplitter()
                except Exception:
                    streamer = None
                    splitter = None

                try:
                    async for chunk in response:
                        if getattr(ctx.ws, "cancel_requested", False):
                            break
                        if not chunk.choices:
                            continue
                        delta = chunk.choices[0].delta.content or ""
                        if delta:
                            if not full_content:  # chữ đầu ra: "Đang trả lời…" như engine/turn/loop
                                from engine.turn.loop import ANSWERING
                                await ctx.send_json(ctx.ws, ANSWERING)
                            full_content += delta
                            await ctx.send_json(ctx.ws, {"type": "text_chunk", "text": delta})
                            if splitter and streamer:
                                for sentence in splitter.push(delta):
                                    await streamer.put(sentence)

                    if splitter and streamer:
                        for sentence in splitter.flush():
                            await streamer.put(sentence)
                except Exception as stream_err:
                    log.warning(f"RAG streaming error: {stream_err}")
                    if streamer:
                        await streamer.stop(clear_queue=True)

                if sources_text and not getattr(ctx.ws, "cancel_requested", False):
                    full_content += sources_text
                    await ctx.send_json(ctx.ws, {"type": "text_chunk", "text": sources_text})

                if not getattr(ctx.ws, "cancel_requested", False):
                    # LLM xong: status idle ngay, không gắn với bộ gõ chữ (như engine/turn/loop.run_loop)
                    await ctx.send_json(ctx.ws, {"type": "status", "state": "idle"})
                    await ctx.send_json(ctx.ws, {"type": "stream_end"})
                if streamer:  # sau stream_end như engine/turn/loop._Output.finish: chữ xong không chờ TTS tổng hợp
                    await streamer.stop()
                return full_content
        except Exception as e:
            log.warning(f"RAG stream call failed, falling back to sync: {e}")

    # Fallback đồng bộ (cho mock tests hoặc khi stream không khả dụng)
    response = await llm_server.call_llm(
        messages=messages,
        stream=False,
        **summary.ANSWER_KW,
    )
    if not response or not getattr(response, "choices", None):
        raise RuntimeError("LLM tổng hợp RAG không trả về nội dung")
    answer = (response.choices[0].message.content or "").strip()
    full_text = f"{answer}{sources_text}"
    if ctx and getattr(ctx, "ws", None) and getattr(ctx, "send_json", None):
        await _say(ctx, full_text)
    return full_text


SAVE_WAIT_SECONDS = 90


def _same_bytes(a: Path, b: Path) -> bool:
    if a.stat().st_size != b.stat().st_size:
        return False
    return hashlib.sha256(a.read_bytes()).digest() == hashlib.sha256(b.read_bytes()).digest()


def _copy_into(folder: Path, name: str, src: Path) -> tuple[Path, bool]:
    """Copy nguyên tử vào thư mục watcher. -> (đích, đã có sẵn cùng nội dung). Khác nội dung cùng tên thì thêm ' (2)'."""
    stem, suffix = Path(name).stem, Path(name).suffix
    dest, n = folder / name, 1
    while dest.exists():
        if _same_bytes(dest, src):
            return dest, True
        n += 1
        dest = folder / f"{stem} ({n}){suffix}"
    # Đuôi .part không thuộc SUPPORTED_EXTENSIONS: watcher chỉ thấy tệp khi os.replace xong, không đọc nửa chừng.
    tmp = dest.with_name(dest.name + ".part")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dest)
    return dest, False


async def save_document(att) -> str:
    """Copy tệp vào thư mục kho, chờ watcher nạp xong rồi kèm tổng hợp tài liệu nói về gì (2026-10-14)."""
    name = Path(att.filename).name
    if Path(name).suffix.lower() not in rag_watcher.SUPPORTED_EXTENSIONS:
        return f"Kho tài liệu không hỗ trợ định dạng {att.extension or 'không xác định'}."
    folder = rag_watcher.watch_folder()
    folder.mkdir(parents=True, exist_ok=True)
    dest, existed = await asyncio.to_thread(_copy_into, folder, name, Path(att.resolved_path))
    if existed:
        return f"{dest.name} đã có trong thư mục kho ({folder})."
    if rag_watcher.get_rag_watcher() is None:
        return f"Đã lưu {dest.name} vào {folder}. Sẽ được nạp vào kho khi bộ theo dõi chạy."
    resolved = str(dest.resolve())
    deadline = time.monotonic() + SAVE_WAIT_SECONDS
    while True:
        row = next((f for f in rag_watcher.get_watch_stats()["files"] if f["file_path"] == resolved), None)
        if row:
            return f"Đã lưu {dest.name} vào kho: {row['chunks']} đoạn." + await _summary_of(resolved, dest.name)
        if time.monotonic() >= deadline:
            return f'Đã lưu {dest.name} vào {folder}, đang nạp vào kho. Xem tiến độ bằng "@rag danh sách".'
        await asyncio.sleep(min(0.5, max(0.0, deadline - time.monotonic())))


async def _summary_of(file_path: str, name: str) -> str:
    from engine.core.rag_engine import get_rag_engine
    from engine.rag import summary
    key = os.path.normcase(file_path)  # watcher lưu "documents" chữ thường, resolve() ra "Documents"
    chunks = [c for c in get_rag_engine().chunks if os.path.normcase(c.get("file_path") or "") == key]
    text = await summary.summarize(name, chunks)
    return f"\n\n{text}" if text else ""


def _list() -> str:
    from engine.core.rag_engine import get_rag_engine
    docs = _docs(get_rag_engine().chunks)
    if not docs:
        return EMPTY
    lines = ["Tài liệu trong kho:"]
    lines += [f"{i}. {d['name']} ({d['chunks']} đoạn)" for i, d in enumerate(docs, 1)]
    lines.append('Xóa: "@rag xóa <số>" hoặc "@rag xóa <tên tệp>".')
    return "\n".join(lines)


def _to_vault_trash(path: str) -> Path | None:
    """Chỉ tệp nằm trong thư mục watcher mới bị chuyển đi; ngoài đó thì để nguyên. Thùng rác nằm cạnh thư mục
    watcher (không nằm trong), nếu không watcher sẽ nạp lại chính tệp trong thùng rác."""
    src = Path(path) if path else None
    folder = rag_watcher.watch_folder().resolve()
    if src is None or not src.is_file() or folder not in src.resolve().parents:
        return None
    trash = folder.parent / ".trash" / folder.name
    trash.mkdir(parents=True, exist_ok=True)
    dest, n = trash / src.name, 1
    while dest.exists():
        n += 1
        dest = trash / f"{src.stem} ({n}){src.suffix}"
    shutil.move(str(src), dest)
    return dest


async def remove_document(path: str) -> tuple[int, Path | None]:
    """Xóa = bỏ khỏi chỉ mục + chuyển tệp gốc vào thùng rác. Chỉ xóa chỉ mục thì lần khởi động sau
    scan_existing() thấy tệp chưa được đánh dấu và nạp lại ngay. -> (số đoạn đã xóa, nơi tệp được chuyển tới)."""
    from engine.core.rag_engine import get_rag_engine
    removed = await get_rag_engine().remove_document(path)
    rag_watcher.mark_removed(path)
    return removed, await asyncio.to_thread(_to_vault_trash, path)


async def _delete(arg: str) -> str:
    if not arg:
        return 'Cần số thứ tự hoặc tên tệp, ví dụ "@rag xóa 2". Xem số bằng "@rag danh sách".'
    from engine.core.rag_engine import get_rag_engine
    rag = get_rag_engine()
    docs = _docs(rag.chunks)
    if arg.isdigit():
        doc = docs[int(arg) - 1] if 1 <= int(arg) <= len(docs) else None
    else:
        doc = next((d for d in docs if d["name"].lower() == arg.lower()), None)
    if doc is None:
        return f'Không tìm thấy tài liệu "{arg}". Xem danh sách bằng "@rag danh sách".'
    removed, trashed = await remove_document(doc["path"] or doc["name"])
    note = f" Tệp gốc đã chuyển vào {trashed.parent}." if trashed else ""
    return f"Đã xóa {doc['name']} khỏi kho ({removed} đoạn).{note}"

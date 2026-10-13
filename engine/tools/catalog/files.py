"""Tool cho tệp đính kèm (spec 2026-10-12 mục 4): chỉ khai báo khi có tệp đúng định dạng."""
import os

from engine.tools.registry import tool

_OFFICE_EXT = (".docx", ".xlsx", ".pptx")


def _docs():
    from engine.tools.rag_tool import SUPPORTED_DOCUMENTS
    return SUPPORTED_DOCUMENTS


def _images():
    from engine.tools.image_engine import SUPPORTED_INPUT
    return SUPPORTED_INPUT


@tool(kind="change", needs_attachment=True,
      extensions=lambda: _OFFICE_EXT)
async def office_edit(instruction: str, ctx=None) -> str:
    from engine.tools.office_tools import handle_office_command
    return await handle_office_command(prompt=instruction, filepath=str(ctx.attachment_context.resolved_path),
                                       conversation_history=ctx.conversation_history, ws=ctx.ws)


@tool(display=True, needs_attachment=True, extensions=_docs)
async def rag_ask(question: str, ctx=None) -> dict:
    from engine.tools.rag_tool import handle_rag_query
    return await handle_rag_query(query=question, attachment_context=ctx.attachment_context)


@tool(display=True, needs_attachment=True, extensions=_images)
async def read_image(question: str = "", ctx=None) -> str:
    from engine.server.llm_server import get_llm_client
    from engine.tools.screen import describe_image
    return await describe_image(ctx.attachment_context.resolved_path, question or None,
                                llm_client=get_llm_client(), stream=False)


@tool(kind="change", needs_attachment=True, extensions=_images)
async def upscale_image(ctx=None) -> str:
    from engine.core.output_delivery import deliver_output_file
    from engine.tools.image_engine import upscale_image as _upscale
    result = await _upscale(input_path=str(ctx.attachment_context.resolved_path), output_path=None, scale=4,
                            model_name="upscayl-standard-4x", output_format="png")
    if str(result).startswith("Lỗi") or not os.path.exists(str(result)):
        return str(result)
    name = os.path.basename(str(result))
    if await deliver_output_file(ctx.ws, result, kind="image"):
        return f"Đã nâng cấp ảnh x4 và gửi hình xem trước. Tệp: {name}"
    return f"Đã nâng cấp ảnh x4 thành công. Tệp: {name}"

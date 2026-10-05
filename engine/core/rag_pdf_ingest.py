import asyncio
import base64
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Awaitable, Callable, Sequence

from pypdf import PdfReader, PdfWriter

from engine.core.rag_document_store import (
    PreparedDocument,
    RAGDocumentStore,
)


def is_corrupted_vietnamese(text: str) -> bool:
    if not text or not text.strip():
        return False
    corrupted_patterns = [
        r"[āēīōūĀĒĪŌŪ]",
        r"\b\w*úmng\w*\b",
        r"\b\w*thúrc\w*\b",
        r"\b\w*thurng\w*\b",
        r"\b\w*đurc\w*\b",
        r"\b\w*thr\s+vic\w*\b",
        r"\b\w*tuyẩn\w*\b",
        r"\b\w*đjnh\w*\b",
        r"\b\w*đng\w*\b",
        r"\b\w*gàn\s+nhát\w*\b",
    ]
    for pattern in corrupted_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    macron_count = len(re.findall(r"[āēīōūĀĒĪŌŪ]", text))
    return macron_count >= 2


PageConverter = Callable[[int, object], Awaitable[str]]


class RAGPDFIngestor:
    def __init__(
        self,
        store: RAGDocumentStore,
        native_convert: PageConverter | None = None,
        ocr_convert: PageConverter | None = None,
    ):
        self.store = store
        self.native_convert = native_convert or self._native_pdf_inspector
        self.ocr_convert = ocr_convert or self._vision_ocr

    async def ingest(
        self,
        source_path: Path,
        source_filename: str,
        pages: Sequence[object] | None = None,
    ) -> PreparedDocument:
        source = Path(source_path).resolve(strict=True)
        page_sequence = (
            pages if pages is not None else PdfReader(str(source)).pages
        )
        total_pages = len(page_sequence)
        prepared = self.store.open_staging(source, source_filename)
        manifest = self.store.initialize_manifest(prepared, total_pages)
        completed = {
            item["page"]
            for item in manifest["pages"]
            if item["status"] == "done"
        }

        extracted_pages_map = {}
        pages_needing_ocr_set = set()

        if self.native_convert == self._native_pdf_inspector:
            try:
                import pdf_inspector

                extraction = await asyncio.to_thread(
                    pdf_inspector.extract_pages_markdown, str(source)
                )
                pages_needing_ocr_set = set(
                    getattr(extraction, "pages_needing_ocr", [])
                )
                for pm in getattr(extraction, "pages", []):
                    page_num = getattr(pm, "page", None)
                    if page_num is not None:
                        extracted_pages_map[page_num + 1] = pm
            except Exception as exc:
                logging.warning(
                    "pdf_inspector không trích xuất được batch cho %s: %s",
                    source_filename,
                    exc,
                )

        for page_number, page in enumerate(page_sequence, start=1):
            if (
                page_number in completed
                and prepared.page_path(page_number).exists()
            ):
                continue

            try:
                page_0_idx = page_number - 1
                pm = extracted_pages_map.get(page_number)
                pm_markdown = getattr(pm, "markdown", "") if pm else ""
                pm_needs_ocr = getattr(pm, "needs_ocr", False) if pm else False

                if (
                    pm
                    and pm_markdown
                    and pm_markdown.strip()
                    and not pm_needs_ocr
                    and (page_0_idx not in pages_needing_ocr_set)
                    and not is_corrupted_vietnamese(pm_markdown)
                ):
                    content = pm_markdown.strip()
                    method = "native"
                else:
                    extracted = (page.extract_text() or "").strip()
                    if (
                        extracted
                        and (page_0_idx not in pages_needing_ocr_set)
                        and not is_corrupted_vietnamese(extracted)
                    ):
                        content = await self.native_convert(page_number, page)
                        if is_corrupted_vietnamese(content):
                            content = await self.ocr_convert(page_number, page)
                            method = "ocr"
                        else:
                            method = "native"
                            if not content.strip():
                                content = extracted
                    else:
                        content = await self.ocr_convert(page_number, page)
                        method = "ocr"

                if not content or not content.strip():
                    raise RuntimeError("không tạo được Markdown")
                self.store.write_page(
                    prepared,
                    page_number=page_number,
                    markdown=f"# Trang {page_number}\n\n{content.strip()}",
                    method=method,
                )
            except Exception as exc:
                self.store.mark_page_failed(prepared, page_number)
                raise RuntimeError(
                    f"Trang {page_number} xử lý thất bại: {exc}"
                ) from exc
        return prepared

    async def ingest_markdown_document(
        self,
        source: str | Path,
        source_filename: str,
        *,
        convert: Callable[[str], str] | None = None,
    ) -> PreparedDocument:
        source = Path(source)
        prepared = self.store.open_staging(source, source_filename)
        manifest = self.store.initialize_manifest(prepared, total_pages=1)
        completed = {
            int(item["page"])
            for item in manifest.get("pages", [])
            if item.get("status") == "done"
        }
        if 1 in completed and prepared.page_path(1).exists():
            return prepared

        if convert is None:
            content = await asyncio.to_thread(
                self._convert_markdown_document,
                source,
            )
        else:
            content = await asyncio.to_thread(convert, str(source))
        if not content or not content.strip():
            raise RuntimeError(
                f"Không trích xuất được nội dung từ {source_filename}"
            )
        self.store.write_page(
            prepared,
            page_number=1,
            markdown=content,
            method="native",
        )
        return prepared

    @staticmethod
    def _convert_markdown_document(source: Path) -> str:
        if source.suffix.lower() in {".txt", ".md", ".csv", ".json"}:
            return source.read_text(encoding="utf-8")

        from markitdown import MarkItDown

        return MarkItDown(enable_plugins=False).convert(
            str(source)
        ).text_content

    async def _convert_single_page(self, page, converter) -> str:
        with tempfile.TemporaryDirectory(
            prefix="jarvis-rag-page-"
        ) as temp_dir:
            page_pdf = Path(temp_dir) / "page.pdf"
            writer = PdfWriter()
            writer.add_page(page)
            with page_pdf.open("wb") as handle:
                writer.write(handle)
            return await asyncio.to_thread(converter, str(page_pdf))

    async def _native_pdf_inspector(
        self,
        page_number: int,
        page,
    ) -> str:
        return await self._convert_single_page(
            page,
            self._convert_page_pdf_inspector,
        )

    @staticmethod
    def _convert_page_pdf_inspector(path: str) -> str:
        import pdf_inspector

        res = pdf_inspector.extract_pages_markdown(path)
        if res and getattr(res, "pages", None):
            return res.pages[0].markdown or ""
        return ""

    async def _vision_ocr(
        self,
        page_number: int,
        page,
    ) -> str:
        from openai import OpenAI

        vision_url = os.getenv("VISION_URL") or os.getenv("LOCAL_URL")
        vision_key = (
            os.getenv("VISION_API_KEY")
            or os.getenv("LOCAL_API_KEY")
            or "dummy"
        )
        from engine.server.llm_server import strip_think, vision_model_name, vision_request_kwargs

        vision_model = vision_model_name()
        if not vision_url or not vision_model:
            raise RuntimeError("Vision OCR chưa được cấu hình")

        client = OpenAI(api_key=vision_key, base_url=vision_url)

        def convert(path: str) -> str:
            import fitz

            with fitz.open(path) as document:
                pixmap = document[0].get_pixmap(
                    matrix=fitz.Matrix(300 / 72, 300 / 72),
                    alpha=False,
                )
                image_data = base64.b64encode(
                    pixmap.tobytes("png")
                ).decode("ascii")

            prompt = (
                "Nhận diện toàn bộ văn bản tiếng Việt trong hình ảnh này và chuyển thành Markdown. "
                "LƯU Ý QUAN TRỌNG: Sửa lại toàn bộ các ký tự dấu tiếng Việt bị lỗi font "
                "(ví dụ: khôi phục dấu đầy đủ chuẩn ngữ pháp tiếng Việt: 'Chura tirng úmng tuyn' -> 'Chưa từng ứng tuyển', "
                "'đurc' -> 'được', 'hê thóng' -> 'hệ thống', 'ký Hp đòng' -> 'ký Hợp đồng', 'thr vic' -> 'thử việc'). "
                "Giữ chính xác toàn bộ số tiền, ngày tháng, tiêu đề, danh sách và ô bảng theo đúng thứ tự đọc. "
                "Không dịch, không tóm tắt, không suy đoán và không mô tả ảnh. "
                "Bỏ qua watermark của ứng dụng scan. Chỉ trả về nội dung Markdown đã khôi phục."
            )
            response = client.chat.completions.create(
                model=vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": (
                                        "data:image/png;base64," + image_data
                                    )
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
                max_tokens=4096,
                timeout=float(os.getenv("LOCAL_LLM_TIMEOUT_SECONDS", "180")),
                # OCR: tắt thinking, temp 0, không phạt lặp token (vision_request_kwargs đã đặt sẵn).
                **vision_request_kwargs(),
            )
            if not response or not getattr(response, "choices", None):
                raise RuntimeError(
                    f"Vision OCR trang {page_number} không trả về nội dung"
                )
            content = strip_think(response.choices[0].message.content or "")
            return content.strip() if content else ""

        return await self._convert_single_page(
            page,
            convert,
        )

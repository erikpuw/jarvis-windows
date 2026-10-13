# -*- coding: utf-8 -*-
import os
import re
import json
import logging
import socket
import subprocess
import asyncio
from pathlib import Path
from typing import Any

log = logging.getLogger("jarvis.office_tools")

ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = ROOT / "data" / "output"

PREVIEW_PORT = 26315
_previewed_path: str | None = None

BASE_PROMPT = """Bạn là một chuyên gia dùng công cụ Office (.docx, .xlsx, .pptx) chuyên nghiệp sử dụng công cụ CLI `officecli`.
Nhiệm vụ của bạn là nhận yêu cầu bằng tiếng Việt, từ đó sinh ra danh sách lệnh gọi batch JSON để tạo ra tài liệu có BỐ CỤC ĐẸP MẮT, NỘI DUNG ĐẦY ĐỦ, DÀI VÀ TRANG TRỌNG.

=== QUY TẮC ĐẦU RA BẮT BUỘC (BATCH JSON SCHEMA) ===
1. Bạn PHẢI TRẢ VỀ định dạng batch JSON duy nhất đặt trong block mã ```json. Không viết thêm giải thích ngoài block mã này.
2. Mỗi phần tử trong mảng JSON là một object biểu diễn một lệnh.
3. Tất cả thuộc tính của phần tử (text, bold, align, size, color, fill, x, y, width, height, v.v.) BẮT BUỘC PHẢI ĐẶT TRONG DICTIONARY NẰM TRONG TRƯỜNG `"props"`.
   CẤM TUYỆT ĐỐI dùng trường `"prop"` hoặc đặt trực tiếp ở cấp cao nhất của phần tử!
4. Thuộc tính lệnh:
   - `"command"`: Lệnh thực thi (`"add"`, `"set"`, `"remove"`).
   - `"parent"`: Đối tượng cha (khi `"command": "add"`).
   - `"type"`: Loại phần tử thêm mới (`"paragraph"`, `"table"`, `"sheet"`, `"cell"`, `"textbox"`, `"slide"`).
   - `"props"`: Dictionary chứa tất cả thuộc tính/định dạng (ví dụ: `{"text": "...", "bold": true, "align": "center"}`).
   - `"path"`: Đường dẫn đối tượng (khi `"command": "set"` hoặc `"remove"`).
"""

WORD_PROMPT = """
=== QUY CHUẨN SOẠN THẢO VĂN BẢN HÀNH CHÍNH VIỆT NAM (Nghị định 30/2020/NĐ-CP) ===
Khi soạn thảo tài liệu Word (.docx), giá trị `"parent"` khi thêm mới luôn là `"/body"`.
Cấu trúc văn bản chỉnh chu:
1. **Quốc hiệu & Tiêu ngữ (Bắt buộc)**: Đặt ở đầu trang, căn giữa hoặc căn phải, in đậm (Quốc hiệu) và in nghiêng (Tiêu ngữ).
2. **Tiêu đề văn bản**: Viết in hoa, in đậm, cỡ chữ lớn (15-16pt), căn giữa, giãn cách trước/sau rộng rãi (`spaceBefore="18pt"`, `spaceAfter="12pt"`).
3. **Kính gửi**: In đậm chữ "Kính gửi:", căn trái hoặc lùi lề dòng đầu.
4. **Nội dung chính**:
   - Chi tiết, văn phong hành chính trang trọng. Tuyệt đối KHÔNG viết quá ngắn hoặc dùng placeholder chung chung.
   - Thụ lề dòng đầu (`firstLineIndent="1cm"`) cho mỗi đoạn văn.
   - Căn lề đều hai bên (`align="both"` hoặc `align="justify"`).
5. **Lời kết & Ký tên**: Đặt lùi lề phải hoặc căn phải, in đậm tiêu đề ký.

=== VÍ DỤ MẪU BATCH JSON WORD (.docx) ===
```json
[
  {"command": "add", "parent": "/body", "type": "paragraph", "props": {"text": "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", "align": "center", "bold": true, "size": 13}},
  {"command": "add", "parent": "/body", "type": "paragraph", "props": {"text": "Độc lập - Tự do - Hạnh phúc", "align": "center", "italic": true, "size": 13, "spaceAfter": "18pt"}},
  {"command": "add", "parent": "/body", "type": "paragraph", "props": {"text": "ĐƠN XIN VIỆC", "align": "center", "bold": true, "size": 18, "spaceBefore": "12pt", "spaceAfter": "12pt"}},
  {"command": "add", "parent": "/body", "type": "paragraph", "props": {"text": "Kính gửi: Ban Giám đốc Công ty...", "bold": true, "spaceBefore": "6pt"}},
  {"command": "add", "parent": "/body", "type": "paragraph", "props": {"text": "Tôi tên là Nguyễn Văn A, tốt nghiệp chuyên ngành...", "firstLineIndent": "1cm", "align": "both"}}
]
```
"""

EXCEL_PROMPT = """
=== QUY CHUẨN THIẾT KẾ BẢNG TÍNH EXCEL (.xlsx) ===
Khi làm việc với Excel (.xlsx), dùng lệnh `"command": "set"` với `"path": "/Sheet1/A1"` hoặc `"command": "add"` với `"parent": "/"`, `"type": "sheet"`.
1. Tiêu đề bảng rõ ràng, in đậm, cỡ chữ lớn.
2. Tiêu đề các cột (Header Row) in đậm, sử dụng màu nền nhã nhặn (ví dụ xanh navy tối `fill="1F4E79"`, chữ trắng `font.color="FFFFFF"`).
3. Các cột số phải căn phải (`alignment.horizontal="right"`), định dạng số rõ ràng (`numberformat="#,##0"`).

=== VÍ DỤ MẪU BATCH JSON EXCEL (.xlsx) ===
```json
[
  {"command": "set", "path": "/Sheet1/A1", "props": {"value": "BÁO CÁO DOANH THU", "font.bold": "true", "font.size": "16", "fill": "1F4E79", "font.color": "FFFFFF"}},
  {"command": "set", "path": "/Sheet1/A2", "props": {"value": "Mặt hàng", "font.bold": "true", "fill": "D9E1F2"}},
  {"command": "set", "path": "/Sheet1/B2", "props": {"value": "Số lượng", "font.bold": "true", "fill": "D9E1F2", "alignment.horizontal": "right"}},
  {"command": "set", "path": "/Sheet1/A3", "props": {"value": "Sản phẩm A"}},
  {"command": "set", "path": "/Sheet1/B3", "props": {"value": 150, "numberformat": "#,##0"}}
]
```
"""

PPT_PROMPT = """
=== QUY CHUẨN THIẾT KẾ SLIDE POWERPOINT (.pptx) ===
Khi làm việc với PowerPoint (.pptx):
- Tạo slide mới: `"command": "add", "parent": "/", "type": "slide"`.
- Tạo textbox/shape trong slide: `"command": "add", "parent": "/slide[1]", "type": "textbox"`.
- Đặt tọa độ và kích thước bằng các thuộc tính `x`, `y`, `width` (hoặc `w`), `height` (hoặc `h`) trong `"props"`.

=== VÍ DỤ MẪU BATCH JSON POWERPOINT (.pptx) ===
```json
[
  {"command": "add", "parent": "/", "type": "slide"},
  {"command": "add", "parent": "/slide[1]", "type": "textbox", "props": {"text": "BÁO CÁO DỰ ÁN", "size": 32, "bold": true, "align": "center", "x": "0.5in", "y": "0.5in", "width": "12in", "height": "1in"}},
  {"command": "add", "parent": "/slide[1]", "type": "textbox", "props": {"text": "Nội dung giới thiệu chi tiết...", "size": 18, "x": "0.5in", "y": "1.8in", "width": "12in", "height": "4in"}}
]
```
"""

def _extract_batch_json(text: str) -> str | None:
    """Chỉ nhận block ```json; không bao giờ thực thi văn bản LLM như lệnh shell."""
    blocks = re.findall(r"```json\s*\n?(.*?)```", text, re.DOTALL | re.IGNORECASE)
    return blocks[0].strip() if blocks else None


async def _run_officecli(*args: str, timeout: float = 120) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "officecli", *args, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return (
        proc.returncode,
        out.decode("utf-8", errors="ignore").strip(),
        err.decode("utf-8", errors="ignore").strip(),
    )


def _pick_preview_port() -> int:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        if probe.connect_ex(("127.0.0.1", PREVIEW_PORT)) != 0:
            return PREVIEW_PORT
    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        return free.getsockname()[1]


async def _start_preview(path: str) -> int:
    """Mở `officecli watch` cho `path`; dừng preview cũ trước để không tranh cổng."""
    global _previewed_path
    if _previewed_path:
        try:
            await _run_officecli("unwatch", _previewed_path, timeout=30)
        except Exception as e:
            log.warning(f"Could not unwatch {_previewed_path}: {e}")
    port = _pick_preview_port()
    subprocess.Popen(
        ["officecli", "watch", path, "--port", str(port)],
        creationflags=0x00000008, close_fds=True,
    )
    _previewed_path = path
    return port

def _normalize_batch_json(code_str: str) -> str:
    """
    Tự động kiểm tra và sửa các lỗi định dạng JSON batch nhẹ của LLM
    như việc dùng trường 'prop' thay vì dictionary 'props'.
    """
    try:
        data = json.loads(code_str)
        if not isinstance(data, list):
            return code_str
        
        normalized_list = []
        for item in data:
            if not isinstance(item, dict):
                normalized_list.append(item)
                continue
            
            new_item = dict(item)
            props = new_item.get("props")
            if not isinstance(props, dict):
                props = {}

            # Nếu LLM lỡ tạo trường 'prop' thay vì 'props'
            if "prop" in new_item:
                val = new_item.pop("prop")
                if isinstance(val, dict):
                    props.update(val)
                elif isinstance(val, str) and "=" in val:
                    k, v = val.split("=", 1)
                    props[k.strip()] = v.strip()
                elif isinstance(val, list):
                    for elem in val:
                        if isinstance(elem, dict):
                            props.update(elem)
                        elif isinstance(elem, str) and "=" in elem:
                            k, v = elem.split("=", 1)
                            props[k.strip()] = v.strip()

            if props:
                new_item["props"] = props
            
            normalized_list.append(new_item)

        return json.dumps(normalized_list, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning(f"Could not parse/normalize batch JSON: {e}")
        return code_str

def _get_relevant_templates(ext: str, prompt: str) -> str:
    """
    Đọc động các tệp ví dụ/hướng dẫn từ thư mục examples/
    dựa trên loại định dạng file và từ khóa trong prompt.
    """
    examples_dir = ROOT / "examples"
    if not examples_dir.exists():
        return ""

    subfolder = "word" if ext == "docx" else ("excel" if ext == "xlsx" else "ppt")
    target_dir = examples_dir / subfolder
    if not target_dir.exists():
        return ""

    selected_files = []
    lower_prompt = prompt.lower()

    if ext == "docx":
        files_to_check = ["paragraph-formatting.sh", "document-formatting.sh"]
        if any(w in lower_prompt for w in ["bảng", "table", "danh sách"]):
            files_to_check.append("tables.sh")
        if any(w in lower_prompt for w in ["ảnh", "hình", "picture", "image", "logo"]):
            files_to_check.append("pictures.sh")
        if any(w in lower_prompt for w in ["biểu đồ", "chart"]):
            files_to_check.append("charts.sh")
        if any(w in lower_prompt for w in ["công thức", "formula", "toán", "math", "hóa"]):
            files_to_check.append("formulas.sh")
        
        for name in files_to_check:
            fpath = target_dir / name
            if fpath.exists():
                selected_files.append(fpath)

    elif ext == "xlsx":
        files_to_check = ["cell-formatting.sh"]
        if any(w in lower_prompt for w in ["biểu đồ", "chart"]):
            files_to_check.append("charts.sh")
        if any(w in lower_prompt for w in ["điều kiện", "conditional"]):
            files_to_check.append("conditional-formatting.sh")
        if any(w in lower_prompt for w in ["validation", "ràng buộc", "dropdown"]):
            files_to_check.append("data-validation.sh")
        if any(w in lower_prompt for w in ["pivot", "tổng hợp"]):
            files_to_check.append("pivot-tables.sh")
        
        for name in files_to_check:
            fpath = target_dir / name
            if fpath.exists():
                selected_files.append(fpath)

    elif ext == "pptx":
        files_to_check = ["presentation.sh"]
        if any(w in lower_prompt for w in ["biểu đồ", "chart"]):
            files_to_check.append("charts/charts-column.py")
        if any(w in lower_prompt for w in ["bảng", "table"]):
            files_to_check.append("tables/tables-basic.sh")
        
        for name in files_to_check:
            fpath = target_dir / name
            if fpath.exists():
                selected_files.append(fpath)

    if not selected_files:
        return ""

    context_parts = [
        "\n=== CÁC VÍ DỤ THỰC TẾ (FEW-SHOT EXAMPLES) ===",
        "LƯU Ý QUAN TRỌNG: Các file mẫu bên dưới sử dụng cú pháp cờ lệnh CLI --prop key=value. Khi sinh Batch JSON, bạn BẮT BUỘC phải chuyển đổi thành dictionary 'props': {'key': 'value'}. KHÔNG sử dụng trường 'prop' lẻ."
    ]
    for fpath in selected_files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                lines = f.readlines()
                content = "".join(lines[:120])
                if len(lines) > 120:
                    content += "\n# ... (phần còn lại lược bớt để tối ưu hóa) ...\n"
            context_parts.append(f"\n--- FILE MẪU: {fpath.name} ---\n```bash\n{content}```")
        except Exception as e:
            log.warning(f"Không thể đọc file mẫu {fpath}: {e}")

    return "\n".join(context_parts)

def _generate_output_path(prompt: str, ext: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9\s_-]", "", prompt[:60]).strip().replace(" ", "_")
    if not safe:
        safe = "document"
    return str(OUTPUT_DIR / f"{safe}.{ext}")

async def handle_office_command(prompt: str, filepath: str = "", conversation_history: list = None, ws: Any = None) -> str:
    from engine.server.llm_server import call_llm

    if not prompt:
        return "Lỗi: Thiếu prompt."

    # Xác định loại file dựa trên prompt hoặc filepath
    ext = "docx"
    if filepath:
        if filepath.endswith(".xlsx"):
            ext = "xlsx"
        elif filepath.endswith(".pptx"):
            ext = "pptx"
    else:
        if "excel" in prompt.lower() or "xlsx" in prompt.lower() or "bảng tính" in prompt.lower():
            ext = "xlsx"
        elif "powerpoint" in prompt.lower() or "pptx" in prompt.lower() or "slide" in prompt.lower() or "trình chiếu" in prompt.lower():
            ext = "pptx"

    output_path = filepath if filepath else _generate_output_path(prompt, ext)
    output_path = os.path.abspath(output_path)

    if filepath:
        # `filepath` đến trực tiếp từ tham số tool-call, có thể bị dẫn dắt qua
        # prompt injection (nội dung trang web/tài liệu độc hại). Chỉ cho phép
        # trỏ tới file Office thật — chặn khả năng ghi đè bất kỳ loại file nào
        # khác trên máy dưới danh nghĩa "tạo/sửa tài liệu".
        if not output_path.lower().endswith((".docx", ".xlsx", ".pptx")):
            return "Lỗi: Đường dẫn tệp (filepath) phải có đuôi .docx, .xlsx hoặc .pptx."

    # Ghép prompt theo mô-đun ứng với loại file (Word / Excel / PowerPoint)
    full_prompt = BASE_PROMPT
    if ext == "docx":
        full_prompt += WORD_PROMPT
    elif ext == "xlsx":
        full_prompt += EXCEL_PROMPT
    elif ext == "pptx":
        full_prompt += PPT_PROMPT

    templates_context = _get_relevant_templates(ext, prompt)
    if templates_context:
        full_prompt += templates_context

    full_prompt += f"\n\n=== THÔNG TIN MÔI TRƯỜNG ===\nOUTPUT_PATH = r'{output_path}'\nEXTENSION = '{ext}'\n"


    messages = [
        {"role": "system", "content": full_prompt}
    ]
    if conversation_history:
        for msg in conversation_history[-8:]:
            if isinstance(msg, dict) and msg.get("role") in ("user", "assistant"):
                messages.append(msg)
    messages.append({"role": "user", "content": prompt})

    try:
        response = await call_llm(messages, temperature=0.2, thinking=True)
        if not response or not getattr(response, "choices", None):
            return "Lỗi: LLM trả về response rỗng."
        raw = response.choices[0].message.content
        if not raw or not raw.strip():
            return "Lỗi: LLM trả về nội dung trống."

        code = _extract_batch_json(raw)
        if code is None:
            return "Lỗi: LLM không trả về batch JSON hợp lệ nên không thực thi lệnh nào."

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Thay OUTPUT_PATH bằng đường dẫn thật rồi chuẩn hóa JSON batch
        code = code.replace("OUTPUT_PATH", output_path.replace("\\", "\\\\"))
        code = _normalize_batch_json(code)

        # `batch` cần file tồn tại: tạo file rỗng trước, thử lại 1 lần nếu officecli khởi động lỗi
        if not os.path.exists(output_path):
            for attempt in (1, 2):
                rc, _, create_err = await _run_officecli("create", output_path, timeout=30)
                if rc == 0:
                    break
                log.warning(f"officecli create thất bại (lần {attempt}): {create_err}")
            else:
                return f"Lỗi: officecli không tạo được tệp:\n{create_err}"

        batch_file = os.path.join(os.path.dirname(output_path), "office_batch.json")
        with open(batch_file, "w", encoding="utf-8") as f:
            f.write(code)

        try:
            rc, out, err = await _run_officecli("batch", output_path, "--input", batch_file, "--json")
        finally:
            try:
                if os.path.exists(batch_file):
                    os.remove(batch_file)
            except Exception as rm_err:
                log.warning(f"Could not delete temporary batch file: {rm_err}")
            # Nhả khóa resident và flush xuống đĩa để Word/trình khác đọc được ngay
            try:
                await _run_officecli("close", output_path, timeout=30)
            except Exception as close_err:
                log.warning(f"Could not close {output_path}: {close_err}")

        if rc != 0:
            return f"officecli báo lỗi (code {rc}):\nStderr:\n{err}\nStdout:\n{out}"

        # Đưa tài liệu về frontend để tải về (gửi trước preview để ws gửi cuối
        # cùng vẫn là text_chunk xem trước).
        from engine.core.output_delivery import deliver_output_file, file_label

        doc_label = file_label(output_path) or ext.upper()
        await deliver_output_file(
            ws,
            output_path,
            kind="document",
            caption=f"Tài liệu {doc_label}",
        )

        try:
            port = await _start_preview(output_path)
            if ws:
                await ws.send_json({
                    "type": "text_chunk",
                    "text": f"\n\n🖥️ **[Live Preview]** Bản xem trước trực tiếp tài liệu đang hoạt động tại: [http://localhost:{port}](http://localhost:{port})\n"
                })
        except Exception as preview_err:
            log.warning(f"Could not start officecli preview: {preview_err}")

        return f"Đã xử lý xong tài liệu {doc_label} {os.path.basename(output_path)} — đã gửi về giao diện kèm nút tải về."

    except Exception as e:
        log.error(f"Lỗi khi thực thi office_tools: {e}", exc_info=True)
        return f"Lỗi thực thi: {e}"

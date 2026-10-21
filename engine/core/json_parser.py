import json
import logging
import re
from typing import Any

log = logging.getLogger("jarvis.json_parser")

def safe_json_loads(text: str) -> Any:
    """
    Giải mã chuỗi JSON một cách an toàn, sửa đổi các lỗi cú pháp phổ biến của LLM.
    - Bóc tách markdown code blocks (```json ... ```).
    - Trích xuất phần dữ liệu nằm trong ngoặc nhọn {} hoặc ngoặc vuông [].
    - Loại bỏ dấu phẩy dư thừa ở cuối phần tử (trailing commas).
    - Chuyển đổi nháy đơn sang nháy kép cho keys và values (hỗ trợ cả dấu nháy đơn bị escape \\').
    - Escape các ký tự điều khiển xuống dòng không hợp lệ trong chuỗi.
    """
    if not text:
        return {}
        
    text = text.strip()

    # Chốt chặn nếu text là Headroom compression placeholder (không phải JSON thực tế)
    if "Retrieve more: hash=" in text:
        log.info("Safe JSON Parser: Detected Headroom compression placeholder, returning empty dict.")
        return {}
    
    # 1. Loại bỏ markdown code block nếu có
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            if text.endswith("```"):
                text = text[first_nl:len(text)-3].strip()
            else:
                text = text[first_nl:].strip()
                
    # 2. Tìm và trích xuất khối chứa JSON thực sự ({...} hoặc [...])
    first_brace = text.find('{')
    first_bracket = text.find('[')
    
    start_idx = -1
    end_idx = -1
    
    if first_brace != -1 and (first_bracket == -1 or first_brace < first_bracket):
        start_idx = first_brace
        end_idx = text.rfind('}')
    elif first_bracket != -1:
        start_idx = first_bracket
        end_idx = text.rfind(']')
        
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        json_candidate = text[start_idx:end_idx+1]
    else:
        json_candidate = text
        
    # 3. Thử parse trực tiếp trước
    try:
        return json.loads(json_candidate)
    except Exception:
        pass
        
    # 4. Tiến hành sửa lỗi cú pháp nếu parse trực tiếp thất bại
    cleaned = json_candidate
    
    # a. Xóa bỏ trailing commas trước dấu đóng ngoặc } hoặc ]
    cleaned = re.sub(r',\s*([\]}])', r'\1', cleaned)
    
    # b. Sửa lỗi nháy đơn thành nháy kép cho các keys (ví dụ: 'app_name': -> "app_name":)
    cleaned = re.sub(r"'\s*(\w+)\s*'\s*:", r'"\1":', cleaned)
    
    # c. Sửa lỗi nháy đơn thành nháy kép cho các string values (ví dụ: : 'value' -> : "value")
    # Sử dụng regex nhận diện chuỗi có chứa dấu nháy đơn bị escape (\')
    cleaned = re.sub(r":\s*'([^'\\]*(?:\\.[^'\\]*)*)'", r': "\1"', cleaned)
    
    # d. Sửa lỗi các phần tử trong mảng dùng nháy đơn (ví dụ: ['a', 'b'] -> ["a", "b"])
    cleaned = re.sub(r"'\s*([^',\\]*(?:\\.[^',\\]*)*)\s*'", r'"\1"', cleaned)
    
    # e. Loại bỏ dấu escape thừa của nháy đơn trong nháy kép (ví dụ: \' -> ')
    # Vì trong nháy kép thì nháy đơn không cần escape
    cleaned = cleaned.replace("\\'", "'")
    
    # f. Escape các ký tự xuống dòng chưa được escape trong các chuỗi giá trị
    def _escape_newlines(match):
        return match.group(0).replace('\n', '\\n').replace('\r', '\\r')
        
    cleaned = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', _escape_newlines, cleaned)
    
    # 5. Thử parse lại sau khi làm sạch
    try:
        return json.loads(cleaned)
    except Exception as e:
        log.warning(f"Safe JSON Parser: Failed to parse repaired JSON candidate. Error: {e}. Raw content: {text[:150]}...")
        # Fallback: nếu text chỉ là JSON một phần (thiếu kết thúc), trả về dict rỗng
        stripped = text.strip()
        if stripped in ("{", "[", "", "{}", "[]"):
            return {}
        raise e

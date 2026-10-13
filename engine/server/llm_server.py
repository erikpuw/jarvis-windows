import os
import json
import logging
import re
import socket
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from openai import AsyncOpenAI, OpenAI

log = logging.getLogger("jarvis.llm_server")

_llm_client = None
_embed_client = None
_USAGE_FILE = Path(__file__).parent.parent.parent / "data" / "usage_log.jsonl"

_llm_status = {
    "online": False,
    "last_check": 0.0,
    "warned": False,
}
_embed_status = {
    "online": False,
    "last_check": 0.0,
    "warned": False,
}
_stream_tts_status = {
    "online": False,
    "last_check": 0.0,
    "warned": False,
}


def get_server_host_port(url_str: str | None, default_port: int, default_host: str = "127.0.0.1") -> tuple[str, int]:
    """Trích xuất hostname và port từ URL cấu hình."""
    if not url_str:
        return default_host, default_port
    try:
        parsed = urlparse(url_str)
        return parsed.hostname or default_host, parsed.port or default_port
    except Exception:
        return default_host, default_port


def is_port_open(host: str, port: int, timeout: float = 0.3) -> bool:
    """Kiểm tra nhanh kết nối TCP tới cổng máy chủ."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False


def check_llm_server(force: bool = False) -> tuple[bool, str, int]:
    """Kiểm tra kết nối tới máy chủ LLM (cổng 8080).
    Trả về (is_online, message, port).
    """
    global _llm_status
    base_url = os.getenv("LOCAL_URL")
    host, port = get_server_host_port(base_url, 8080)
    now = time.monotonic()

    if not force and (now - _llm_status["last_check"] < 3.0):
        online = _llm_status["online"]
    else:
        online = is_port_open(host, port)
        _llm_status["last_check"] = now

        if online:
            if not _llm_status["online"] and _llm_status["warned"]:
                log.info("Kết nối thành công đến máy chủ LLM cổng %s, hệ thống hoạt động bình thường.", port)
            _llm_status["online"] = True
            _llm_status["warned"] = False
        else:
            _llm_status["online"] = False
            if not _llm_status["warned"]:
                log.warning("Máy chủ LLM cổng %s chưa hoạt động (trạng thái: chờ kết nối).", port)
                _llm_status["warned"] = True

    if online:
        msg = f"Máy chủ LLM cổng {port} đang hoạt động bình thường"
    else:
        msg = f"Máy chủ LLM cổng {port} chưa hoạt động (trạng thái: chờ kết nối)"

    return online, msg, port


def check_embed_server(force: bool = False) -> tuple[bool, str, int]:
    """Kiểm tra kết nối tới máy chủ Embed (cổng 8081).
    Trả về (is_online, message, port).
    """
    global _embed_status
    base_url = os.getenv("LOCAL_EMBED_URL")
    host, port = get_server_host_port(base_url, 8081)
    now = time.monotonic()

    if not force and (now - _embed_status["last_check"] < 3.0):
        online = _embed_status["online"]
    else:
        online = is_port_open(host, port)
        _embed_status["last_check"] = now

        if online:
            if not _embed_status["online"] and _embed_status["warned"]:
                log.info("Kết nối thành công đến máy chủ Embed cổng %s, hệ thống hoạt động bình thường.", port)
            _embed_status["online"] = True
            _embed_status["warned"] = False
        else:
            _embed_status["online"] = False
            if not _embed_status["warned"]:
                log.warning("Máy chủ Embed cổng %s chưa hoạt động (trạng thái: chờ kết nối).", port)
                _embed_status["warned"] = True

    if online:
        msg = f"Máy chủ Embed cổng {port} đang hoạt động bình thường"
    else:
        msg = f"Máy chủ Embed cổng {port} chưa hoạt động (trạng thái: chờ kết nối)"

    return online, msg, port


def check_stream_tts_server(force: bool = False) -> tuple[bool, str, int]:
    """Kiểm tra kết nối tới máy chủ stream_TTS (cổng 8082).
    Trả về (is_online, message, port).
    """
    global _stream_tts_status
    base_url = os.getenv("TTS_STREAM_URL", "http://127.0.0.1:8082")
    host, port = get_server_host_port(base_url, 8082)
    now = time.monotonic()

    if not force and (now - _stream_tts_status["last_check"] < 3.0):
        online = _stream_tts_status["online"]
    else:
        online = is_port_open(host, port)
        _stream_tts_status["last_check"] = now

        if online:
            if not _stream_tts_status["online"] and _stream_tts_status["warned"]:
                log.info("Kết nối thành công đến máy chủ stream_TTS cổng %s, hệ thống hoạt động bình thường.", port)
            _stream_tts_status["online"] = True
            _stream_tts_status["warned"] = False
        else:
            _stream_tts_status["online"] = False
            if not _stream_tts_status["warned"]:
                log.warning("Máy chủ stream_TTS cổng %s chưa hoạt động (trạng thái: chờ kết nối).", port)
                _stream_tts_status["warned"] = True

    if online:
        msg = f"Máy chủ stream_TTS cổng {port} đang hoạt động bình thường"
    else:
        msg = f"Máy chủ stream_TTS cổng {port} chưa hoạt động (trạng thái: chờ kết nối)"

    return online, msg, port


def _is_bonsai() -> bool:
    # Bonsai (Qwen3.8 base): dùng thẻ <think> như Qwen, tham số thinking riêng.
    return os.getenv("BONSAI_MODEL", "false").lower() == "true"


def _is_gemma() -> bool:
    # BONSAI_MODEL ưu tiên hơn CHANG_MODEL để bật thử Bonsai mà không phải tắt cờ Gemma.
    return os.getenv("CHANG_MODEL", "false").lower() == "true" and not _is_bonsai()


# ---------------------------------------------------------------------------
# Model adapter: tham số + cú pháp function-calling theo từng hãng, một chỗ duy
# nhất. Đổi model (Qwen/Gemma/Bonsai) chỉ đổi cờ .env, hành vi theo đúng spec
# đã đo (live_eval: Qwen gate 52/54 + classifier 32/32, Gemma gate 70/70).
# Số liệu bên dưới giữ nguyên hành vi cũ — refactor cấu trúc, không đổi số.
# ---------------------------------------------------------------------------
MODEL_PROFILES = {
    # Qwen3.5 (kể cả bản coder đang phục vụ): vendor spec qua llama.cpp
    # OpenAI-compatible endpoint. Đã probe: server có jinja tool template,
    # tool_choice auto/required đều trả native tool_calls (không cần parse text).
    "qwen": {
        "temp_thinking": 1.0, "temp_instruct": 0.7,
        "top_p_thinking": 0.95, "top_p_instruct": 0.8,
        "top_k": 20, "min_p_thinking": 0.5, "min_p_instruct": 0.0,
        "presence_thinking": 1.5, "presence_instruct": 1.5,
        "repetition_penalty": 1.0,
        "max_thinking": 16384, "max_instruct": 8192,
        "think_start": "<think>", "think_end": "</think>",
        "merge_system_first": True,  # template Qwen/Bonsai bắt system đứng đầu
        "native_tools": True,
    },
    # Bonsai 2 27B (ternary): model card khuyến nghị thinking min_p=0.0,
    # presence_penalty=0.0. Nhánh instruct giữ presence 1.5 như hành vi cũ.
    "bonsai": {
        "temp_thinking": 1.0, "temp_instruct": 0.7,
        "top_p_thinking": 0.95, "top_p_instruct": 0.8,
        "top_k": 20, "min_p_thinking": 0.0, "min_p_instruct": 0.0,
        "presence_thinking": 0.0, "presence_instruct": 1.5,
        "repetition_penalty": 1.0,
        "max_thinking": 16384, "max_instruct": 8192,
        "think_start": "<think>", "think_end": "</think>",
        "merge_system_first": True,
        "native_tools": True,
    },
    # Gemma 4: custom config, thinking kích bằng reasoning flag.
    # Note: Không chèn tay <|think|> vì template Gemma 4 tự bật thinking theo enable_thinking=true
    "gemma": {
        "temp_thinking": 1.0, "temp_instruct": 1.0,
        "top_p_thinking": 0.95, "top_p_instruct": 0.95,
        "top_k": 64, "min_p_thinking": 0.0, "min_p_instruct": 0.0,
        "presence_thinking": 0.0, "presence_instruct": 0.0,
        "repetition_penalty": None,
        "max_thinking": 16384, "max_instruct": 8192,
        "think_start": "<|channel>thought", "think_end": "<channel|>",
        "merge_system_first": True,  # Gemma 4: một system turn duy nhất ở đầu (đo 2026-10-08)
        "native_tools": True,
    },
}


def active_model_key() -> str:
    """'bonsai' | 'gemma' | 'qwen' theo cờ .env (bonsai > gemma > qwen)."""
    if _is_bonsai():
        return "bonsai"
    if _is_gemma():
        return "gemma"
    return "qwen"


def active_model_profile() -> dict:
    return MODEL_PROFILES[active_model_key()]


def active_model_name() -> str | None:
    """Tên model chat đang chạy. Cùng quy tắc chọn với get_llm_client (bonsai > gemma > qwen)."""
    if _is_bonsai():
        return os.getenv("LOCAL_BONSAI_MODEL")
    if _is_gemma():
        return os.getenv("LOCAL_GEMMA_MODEL")
    return os.getenv("LOCAL_MODEL")


def vision_model_name() -> str | None:
    """Model 'mắt' cho screen/webcam/OCR: đi theo model đang chạy khi VISION_MODEL trống hoặc 'auto',
    để đổi model chat thì vision đổi theo, không phải sửa hai chỗ."""
    v = (os.getenv("VISION_MODEL") or "").strip()
    return active_model_name() if not v or v.lower() == "auto" else v


def reasoning_controls(thinking: bool) -> dict:
    """Phần extra_body điều khiển reasoning, theo docs/llama.cpp_server_readme_new.md (dòng 1318-1322).
    reasoning_format="deepseek": thought luôn nằm ở message.reasoning_content, KHÔNG lọt vào content
    (với "none", server trả nguyên "<|channel>thought…" trong content)."""
    controls = {"chat_template_kwargs": {"enable_thinking": thinking}, "reasoning_format": "deepseek"}
    if not thinking:
        controls["reasoning_effort"] = "none"
    return controls


def sampling_params(thinking: bool = False, temperature: float | None = None) -> dict:
    """Mọi tham số lấy mẫu, từ profile đang chạy. temperature=None → mặc định profile; số tường minh
    (kể cả 0.0) luôn thắng. Chọn công cụ / phân loại / trích JSON phải truyền temperature=0.0 tường minh
    (khi temperature=0 thì top_p/top_k/min_p không còn tác dụng)."""
    prof = active_model_profile()
    mode = "thinking" if thinking else "instruct"
    extra = {"top_k": prof["top_k"], "min_p": prof[f"min_p_{mode}"]}
    if prof["repetition_penalty"] is not None:
        extra["repetition_penalty"] = prof["repetition_penalty"]
    return {"temperature": prof[f"temp_{mode}"] if temperature is None else temperature,
            "top_p": prof[f"top_p_{mode}"], "presence_penalty": prof[f"presence_{mode}"], "extra_body": extra}


def vision_request_kwargs() -> dict:
    """Tham số cho request vision/OCR (chế độ instruct, tắt thinking) theo model đang chạy.
    Đọc chữ/số trong ảnh phải tất định: temperature 0 và không phạt lặp token (presence_penalty làm hỏng
    số/ký tự lặp lại trong văn bản gốc). Đo trên Gemma E4B: temp 1.0 đọc sai giờ/phần trăm hoặc trả rỗng."""
    sp = sampling_params(False, temperature=0.0)
    rc = reasoning_controls(False)
    return {
        "temperature": sp["temperature"],
        "top_p": sp["top_p"],
        "presence_penalty": 0.0,
        "extra_body": {**sp["extra_body"], **rc},
    }


def _log_usage(in_tokens: int, out_tokens: int, call_type: str = "api", cached_tokens: int = 0):
    in_t = in_tokens or 0
    out_t = out_tokens or 0
    c_t = cached_tokens or 0
    log.info("[%s] tokens: in=%d (cached=%d) out=%d total=%d", call_type, in_t, c_t, out_t, in_t + out_t)
    try:
        _USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.time(),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "type": call_type,
            "input_tokens": in_t,
            "cached_tokens": c_t,
            "output_tokens": out_t,
        }
        with open(_USAGE_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        log.warning("Failed to write usage JSONL: %s", e)


# ---------------------------------------------------------------------------
# OpenAI client (cached)
# ---------------------------------------------------------------------------

def get_llm_client():
    global _llm_client
    if _llm_client is None:
        api_key = os.getenv("LOCAL_API_KEY") or "dummy"
        base_url = os.getenv("LOCAL_URL") or "http://127.0.0.1:8080/v1"
        
        # Check model switch config
        if _is_bonsai():
            model = os.getenv("LOCAL_BONSAI_MODEL")
            log.info("Switching LLM client model to Bonsai: %s", model)
        elif _is_gemma():
            model = os.getenv("LOCAL_GEMMA_MODEL")
            log.info("Switching LLM client model to Gemma 4: %s", model)
        else:
            model = os.getenv("LOCAL_MODEL")
            
        # Không có timeout tường minh trước đây -> mặc định SDK ~600s. Nếu
        # llama.cpp treo hoặc quá tải, call_llm (dùng bởi routing, agents và
        # luồng phản hồi chính) có thể chặn tới 10 phút trước khi bất kỳ
        # fallback nào kích hoạt, trong khi người dùng chỉ thấy "đang nghĩ"
        # không phản hồi suốt thời gian đó.
        llm_timeout = float(os.getenv("LOCAL_LLM_TIMEOUT_SECONDS", "180"))
        _llm_client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=llm_timeout, max_retries=1)
        _llm_client.model = model
    return _llm_client


def get_embed_client():
    global _embed_client
    api_key = os.getenv("LOCAL_EMBED_API")
    base_url = os.getenv("LOCAL_EMBED_URL")
    if not api_key or not base_url:
        return None

    # Kiểm tra máy chủ Embed trước khi khởi tạo / trả về client
    online, _, _ = check_embed_server()
    if not online:
        return None

    if _embed_client is None:
        embed_timeout = float(os.getenv("LOCAL_EMBED_TIMEOUT_SECONDS", "30"))
        _embed_client = OpenAI(api_key=api_key, base_url=base_url, timeout=embed_timeout, max_retries=1)
        log.info("Initialized lazy embedding client pointing to %s", base_url)
    return _embed_client


async def close_llm_client():
    """Close and clear the shared LLM client during application shutdown."""
    global _llm_client
    try:
        if _llm_client is not None:
            await _llm_client.close()
    finally:
        _llm_client = None

# ---------------------------------------------------------------------------
# Thinking‑tag stripper for Qwen and Gemma 4 <think> / <|channel>thought blocks
# ---------------------------------------------------------------------------

class StreamThinkStripper:
    def __init__(self):
        prof = active_model_profile()
        self.START = prof["think_start"]
        self.END   = prof["think_end"]
            
        self.buffer = ""
        self.suppress = False
        self.just_ended = False

    def _partial_prefix(self, haystack: str, prefix: str):
        if not prefix:
            return False
        for i in range(1, min(len(prefix), len(haystack)) + 1):
            if prefix.startswith(haystack[-i:]):
                return True
        return False

    def process(self, text: str) -> str:
        if not text:
            return ""
        self.buffer += text
        out = ""

        while self.buffer:
            if self.suppress:
                idx = self.buffer.find(self.END)
                if idx != -1:
                    self.buffer = self.buffer[idx + len(self.END):]
                    self.suppress = False
                    self.just_ended = True
                elif self._partial_prefix(self.buffer, self.END):
                    break
                else:
                    self.buffer = ""
                    break
                continue

            ti = self.buffer.find(self.START)
            if ti != -1:
                out += self.buffer[:ti]
                self.buffer = self.buffer[ti + len(self.START):]
                self.suppress = True
            else:
                if self._partial_prefix(self.buffer, self.START):
                    break
                
                # Nếu vừa mới kết thúc thẻ đóng, lọc bỏ mọi khoảng trắng/dấu xuống dòng thừa ở đầu
                if self.just_ended:
                    stripped_buf = self.buffer.lstrip()
                    if not stripped_buf and self.buffer:
                        break
                    self.buffer = stripped_buf
                    self.just_ended = False
                    
                out += self.buffer
                self.buffer = ""

        return out


def strip_think(content: str) -> str:
    if not content:
        return content
    start = active_model_profile()["think_start"]
    if active_model_key() == "gemma":
        # Thẻ đóng thật là "<channel|>"; bản cũ viết "</channel|>" khiến "|" thành toán tử "hoặc"
        # của regex và xoá mọi ký tự ">" khỏi câu trả lời.
        # Xoá tag + newline/tab liền sau
        content = re.sub(r'<\|channel>thought.*?<channel\|>[\n\t]*', '', content, flags=re.DOTALL)
        # Nếu chỉ có thẻ đóng mà không có thẻ mở (server đã prefill thẻ mở vào prompt),
        # bỏ mọi thứ từ đầu tới hết thẻ đóng
        if "<channel|>" in content and start not in content:
            end_idx = content.find("<channel|>")
            if end_idx != -1:
                content = content[end_idx + len("<channel|>"):].lstrip()
        elif start in content:
            content = content.split(start)[0]
    else:
        # Tương tự cho Qwen/Bonsai
        content = re.sub(r'<think>.*?</think>[\n\t]*', '', content, flags=re.DOTALL)
        if "</think>" in content and start not in content:
            end_idx = content.find("</think>")
            if end_idx != -1:
                content = content[end_idx + len("</think>"):].lstrip()
        elif start in content:
            content = content.split(start)[0]
    # Không gộp khoảng trắng: hàm này chạy trên mọi câu trả lời, bảng/danh sách Markdown phải còn nguyên dòng.
    return content.strip()


# ---------------------------------------------------------------------------
# Core LLM call compliant with Qwen3.5-9B and Gemma 4 official specifications
# ---------------------------------------------------------------------------

async def call_llm(
    messages: list,
    model: str = None,
    thinking: bool = False,
    stream: bool = False,
    tools: list = None,
    tool_choice: str = None,
    temperature: float = None,
    max_tokens: int = None,
    response_format: dict = None,
    thinking_budget: int = None,
):
    # Single choke point for every LLM caller in the process — hot path,
    # agents, Dream, Learning, Self-Healing, Evolution, RAG. Admission control
    # lives here so background work cannot queue in front of a live turn.
    from engine.core.activity_gate import get_inference_gate, in_interactive_turn
    async with get_inference_gate().slot(interactive=in_interactive_turn()):
        return await _call_llm_inner(
            messages, model, thinking, stream, tools, tool_choice,
            temperature, max_tokens, response_format, thinking_budget,
        )


async def _call_llm_inner(
    messages: list,
    model: str = None,
    thinking: bool = False,
    stream: bool = False,
    tools: list = None,
    tool_choice: str = None,
    temperature: float = None,
    max_tokens: int = None,
    response_format: dict = None,
    thinking_budget: int = None,
):
    client = get_llm_client()
    # Kiểm tra kết nối tới máy chủ LLM (cổng 8080) trước khi tạo request thực tế
    if isinstance(client, AsyncOpenAI):
        is_online, status_msg, llm_port = check_llm_server()
        if not is_online:
            raise ConnectionError(f"Máy chủ LLM cổng {llm_port} chưa hoạt động (trạng thái: chờ kết nối)")

    model_name = model or client.model
    prof = active_model_profile()

    cleaned = []
    if messages:
        for msg in messages:
            if not isinstance(msg, dict):
                if hasattr(msg, "model_dump"):
                    msg_dict = msg.model_dump()
                elif hasattr(msg, "dict"):
                    msg_dict = msg.dict()
                else:
                    msg_dict = {
                        "role": getattr(msg, "role", "assistant"),
                        "content": getattr(msg, "content", ""),
                    }
                    if hasattr(msg, "tool_calls"):
                        msg_dict["tool_calls"] = getattr(msg, "tool_calls", None)
                msg = msg_dict

            role = msg.get("role")
            content = msg.get("content")
            if role == "assistant" and isinstance(content, str):
                cleaned.append({**msg, "content": strip_think(content)})
            else:
                cleaned.append(msg)

    # Một system turn duy nhất ở đầu: template Qwen/Bonsai raise nếu system không nằm đầu; Gemma 4 không báo lỗi
    # nhưng chỉ được huấn luyện với một system turn (ai.google.dev) — đo 2026-10-08: gộp giữ nguyên chất lượng chat.
    if prof["merge_system_first"] and any(m.get("role") == "system" for m in cleaned[1:]):
        sys_parts = [str(m.get("content") or "") for m in cleaned if m.get("role") == "system"]
        rest = [m for m in cleaned if m.get("role") != "system"]
        cleaned = [{"role": "system", "content": "\n\n".join(p for p in sys_parts if p)}] + rest

    # Xây dựng sampling params (temperature, top_p, presence_penalty) + extra_body (top_k, min_p, ...)
    sp = sampling_params(thinking, temperature)
    extra_body = {**sp["extra_body"], **reasoning_controls(thinking)}
    if thinking and thinking_budget is not None:  # giới hạn token suy nghĩ theo request (think_mode_probe 2026-10-12)
        extra_body["thinking_budget_tokens"] = thinking_budget

    # Tính max_tokens mặc định theo mode
    mode = "thinking" if thinking else "instruct"
    default_max_tokens = prof[f"max_{mode}"]

    # Đóng gói tham số gửi đi
    params = {
        "model": model_name,
        "messages": cleaned,
        "temperature": sp["temperature"],
        "top_p": sp["top_p"],
        "max_tokens": max_tokens if max_tokens is not None else default_max_tokens,
        "presence_penalty": sp["presence_penalty"],
        "extra_body": extra_body,
        "stream": stream,
    }

    if tools is not None:
        params["tools"] = tools
    if tool_choice is not None:
        params["tool_choice"] = tool_choice
    if response_format is not None:
        params["response_format"] = response_format

    if stream:
        params["stream_options"] = {"include_usage": True}

    log.info(
        "LLM request config: model=%s thinking=%s stream=%s temperature=%s top_p=%s top_k=%s min_p=%s max_tokens=%s",
        model_name,
        thinking,
        stream,
        sp["temperature"],
        sp["top_p"],
        extra_body.get("top_k"),
        extra_body.get("min_p"),
        params["max_tokens"],
    )

    request_started = time.monotonic()
    try:
        response = await client.chat.completions.create(**params)
        log.info(
            "LLM transport ready: stream=%s elapsed=%.2fs",
            stream,
            time.monotonic() - request_started,
        )

        if stream:
            async def stream_wrapper(original_stream):
                stripper = StreamThinkStripper()
                last_usage = None
                try:
                    async for chunk in original_stream:
                        if not chunk.choices:
                            if hasattr(chunk, "usage") and chunk.usage:
                                last_usage = chunk.usage
                            yield chunk
                            continue
                        delta = chunk.choices[0].delta
                        if hasattr(delta, "content") and delta.content:
                            delta.content = stripper.process(delta.content)
                        # reasoning_content không nên hiển thị cho consumer (nằm ở delta.reasoning_content)
                        if hasattr(delta, "reasoning_content"):
                            delta.reasoning_content = None
                        yield chunk
                    if last_usage:
                        cached_t = 0
                        if hasattr(last_usage, "prompt_tokens_details") and last_usage.prompt_tokens_details:
                            cached_t = getattr(last_usage.prompt_tokens_details, "cached_tokens", 0) or 0
                        _log_usage(last_usage.prompt_tokens, last_usage.completion_tokens, cached_tokens=cached_t)
                finally:  # dừng sớm (kẹt lặp, huỷ) → đóng kết nối để llama-server không sinh tiếp
                    if hasattr(original_stream, "close"):
                        await original_stream.close()

            return stream_wrapper(response)
        else:
            if hasattr(response, "usage") and response.usage:
                usage = response.usage
                cached_t = 0
                if hasattr(usage, "prompt_tokens_details") and usage.prompt_tokens_details:
                    cached_t = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0
                _log_usage(usage.prompt_tokens, usage.completion_tokens, cached_tokens=cached_t)
            msg = response.choices[0].message if response.choices else None
            if msg and msg.content:
                msg.content = strip_think(msg.content)
            return response

    except Exception as e:
        is_conn_err = (
            isinstance(e, ConnectionError)
            or "connection" in type(e).__name__.lower()
            or "connect" in str(e).lower()
        )
        if is_conn_err:
            _, _, llm_port = check_llm_server(force=True)
            log.warning(
                "Máy chủ LLM cổng %s chưa hoạt động (trạng thái: chờ kết nối).",
                llm_port,
            )
        else:
            log.error(
                "LLM API call failed after %.2fs: %s: %s",
                time.monotonic() - request_started,
                type(e).__name__,
                e,
                exc_info=True,
            )
        raise

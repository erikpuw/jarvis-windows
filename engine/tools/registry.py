"""Danh mục tool duy nhất (spec 2026-10-12 mục 2): hàm Python khai báo chữ ký + cờ; chữ model đọc nằm ở
prompt/tools/<tên>.md (dòng mô tả, `tham_số: mô tả`, `## answer`). Không viết mô tả tool ở nơi khác."""
import importlib
import inspect
import json
import logging
import re
import sys
import time
import typing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

log = logging.getLogger("jarvis.tools.registry")

_CATALOG_MODULES = ("system", "media", "lookup", "gym", "files", "internal")
_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}
_PARAM_LINE = re.compile(r"^(\w+):\s*(.+)$")
TOOL_DOCS = Path(__file__).resolve().parents[2] / "prompt" / "tools"


@dataclass
class ToolContext:
    ws: Any = None
    send_json: Any = None
    attachment_context: Any = None
    conversation_history: list | None = None
    user_text: str = ""
    trace: list | None = None          # win_control: thao tác cua đã chạy (spec 2026-10-13 mục 4.1)
    replay_steps: list | None = None   # win_control: thao tác cua cần phát lại (mục 4.2)


@dataclass(frozen=True)
class ToolResult:
    text: str
    outcome: str  # success | failed | no_result


@dataclass
class ToolSpec:
    name: str
    fn: Callable
    kind: str
    display: bool
    needs_attachment: bool
    extensions: Callable[[], Iterable[str]] | None
    chat: bool
    description: str = ""
    parameters: dict | None = None
    answer: str = ""
    wants_ctx: bool = False


_TOOLS: dict[str, ToolSpec] = {}
_loaded = False


def parse_doc(text: str) -> tuple[str, dict[str, str], str]:
    """(dòng mô tả, {tham_số: mô tả}, luật trả lời) từ nội dung prompt/tools/<tên>.md."""
    body, _, answer = text.partition("## answer")
    lines = [line.strip() for line in body.strip().splitlines() if line.strip()]
    params = {}
    for line in lines[1:]:
        m = _PARAM_LINE.match(line)
        if m:
            params[m.group(1)] = m.group(2).strip()
    return (lines[0] if lines else ""), params, answer.strip()


def _build(spec: ToolSpec, doc_text: str) -> None:
    description, param_docs, answer = parse_doc(doc_text)
    sig = inspect.signature(spec.fn)
    hints = typing.get_type_hints(spec.fn)
    props: dict[str, dict] = {}
    required: list[str] = []
    for pname, p in sig.parameters.items():
        if pname == "ctx":
            spec.wants_ctx = True
            continue
        hint = hints.get(pname, str)
        if typing.get_origin(hint) is Literal:
            prop = {"type": "string", "enum": list(typing.get_args(hint))}
        elif hint is list or typing.get_origin(hint) is list:
            prop = {"type": "array", "items": {"type": "object"}}
        else:
            prop = {"type": _TYPES.get(hint, "string")}
        if pname in param_docs:
            prop["description"] = param_docs[pname]
        props[pname] = prop
        if p.default is inspect.Parameter.empty:
            required.append(pname)
    spec.description, spec.answer = description, answer
    spec.parameters = {"type": "object", "properties": props, "required": required}


def tool(kind: str = "read", display: bool = False, needs_attachment: bool = False,
         extensions: Callable[[], Iterable[str]] | None = None, chat: bool = True):
    def wrap(fn):
        spec = ToolSpec(fn.__name__, fn, kind, display, needs_attachment, extensions, chat)
        _build(spec, (TOOL_DOCS / f"{fn.__name__}.md").read_text(encoding="utf-8"))
        _TOOLS[spec.name] = spec
        return fn
    return wrap


def _register_for_test(fn, doc: str = "", **kw):
    global _loaded
    _loaded = True  # test tự đăng ký, không nạp catalog thật
    spec = ToolSpec(fn.__name__, fn, kw.get("kind", "read"), kw.get("display", False),
                    kw.get("needs_attachment", False), kw.get("extensions"), kw.get("chat", True))
    _build(spec, doc or fn.__name__)
    _TOOLS[spec.name] = spec
    return fn


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        for mod in _CATALOG_MODULES:
            name = f"engine.tools.catalog.{mod}"
            # reload: sau _reset_for_test module đã nằm trong sys.modules, import lại không chạy decorator
            if name in sys.modules:
                importlib.reload(sys.modules[name])
            else:
                importlib.import_module(name)
    except BaseException:
        # import lỗi: không để cờ "đã nạp" khi registry còn thiếu tool
        _loaded = False
        raise


def _reset_for_test():
    global _loaded
    _TOOLS.clear()
    _loaded = False


def get(name: str) -> ToolSpec | None:
    _ensure_loaded()
    return _TOOLS.get(name)


def names() -> list[str]:
    _ensure_loaded()
    return list(_TOOLS)


def _accepts(spec: ToolSpec, attachment_context) -> bool:
    if attachment_context is None:
        return False
    if spec.extensions is None:
        return True
    ext = (getattr(attachment_context, "extension", "") or "").lower()
    return bool(ext) and ext in {e.lower() for e in spec.extensions()}


def chat_names(attachment_context=None) -> list[str]:
    """Tool model được chọn trong lượt thường: chat=True, tool tệp chỉ khi tệp hợp."""
    _ensure_loaded()
    return [s.name for s in _TOOLS.values()
            if s.chat and (not s.needs_attachment or _accepts(s, attachment_context))]


def file_tools_for(attachment_context) -> list[str]:
    _ensure_loaded()
    return [s.name for s in _TOOLS.values() if s.chat and s.needs_attachment and _accepts(s, attachment_context)]


def _coerce(value, prop: dict):
    t = prop.get("type")
    if t == "integer" and isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    if t == "number" and isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return value
    if t == "boolean" and isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "có")
    return value


def validate(name: str, args, allowed: set[str]) -> tuple[dict | None, str | None]:
    """(args đã làm sạch, None) hoặc (None, lỗi). Bỏ khoá lạ, ép kiểu đơn giản, kiểm required + enum."""
    _ensure_loaded()
    if name not in allowed or name not in _TOOLS:
        return None, f"tool '{name}' không được khai báo lượt này"
    if not isinstance(args, dict):
        return None, "tham số không phải object"
    params = _TOOLS[name].parameters
    props = params["properties"]
    clean = {k: _coerce(v, props[k]) for k, v in args.items() if k in props}
    missing = [p for p in params["required"] if clean.get(p) in (None, "")]
    if missing:
        return None, f"thiếu tham số {missing}"
    for k, v in clean.items():
        if "enum" in props[k] and v not in props[k]["enum"]:
            return None, f"{k}={v!r} không thuộc {props[k]['enum']}"
    return clean, None


def parameters(name: str) -> dict:
    spec = get(name)
    return spec.parameters if spec else {"type": "object", "properties": {}, "required": []}


def description(name: str) -> str:
    spec = get(name)
    return spec.description if spec else ""


def answer_rules(name: str) -> str:
    spec = get(name)
    return spec.answer if spec else ""


def display(name: str) -> bool:
    spec = get(name)
    return bool(spec and spec.display)


def kind(name: str) -> str:
    spec = get(name)
    return spec.kind if spec else "read"


def params(name: str) -> list[str]:
    return list(parameters(name)["properties"])


def usage(name: str) -> str:
    ps = params(name)
    return f"/{name}" + (f" <{', '.join(ps)}>" if ps else "")


def catalog_text(names: list[str]) -> str:
    """Danh mục công cụ trong <cong_cu> của prompt/jarvis.md (định dạng đã đo 2026-10-12)."""
    lines = []
    for n in names:
        props = parameters(n)["properties"]
        ps = ", ".join(f"{k}: {v.get('description', v['type'])}" for k, v in props.items())
        lines.append(f"- {n}: {description(n)}" + (f" ({ps})" if ps else ""))
    return "\n".join(lines)


def _format(raw) -> str:
    if not isinstance(raw, dict):
        return str(raw)
    for key in ("text", "message", "display"):
        if isinstance(raw.get(key), str) and raw[key].strip():
            return raw[key]
    return json.dumps(raw, ensure_ascii=False, indent=2)


def _outcome(text: str, raw) -> str:
    low = text.lower()
    if text.startswith(("Lỗi", "Error", "Xin lỗi")) or text.rstrip(" .!\n").endswith("Thất bại"):
        return "failed"
    if isinstance(raw, dict) and ("error" in raw or raw.get("status") == "failed"):
        return "failed"
    if low.startswith(("không tìm thấy", "không có kết quả", "không thể", "no results")):
        return "no_result"
    return "success"


async def run(name: str, args: dict, ctx: ToolContext | None = None) -> ToolResult:
    """Chạy tool đã validate: guardrail (fail-closed) → hàm → làm sạch → trace."""
    from engine.core import guardrails
    from engine.core.trace_logger import TraceLogger
    spec = get(name)
    started = time.time()
    raw = None
    try:
        ok, reason = guardrails.verify_output(name, args)
    except Exception as exc:
        ok, reason = False, f"không kiểm tra được lệnh gọi '{name}' ({exc})"
    if not ok:
        text, outcome = f"Lỗi bảo mật: {reason}", "failed"
    elif spec is None:
        text, outcome = f"Lỗi: Không tìm thấy công cụ '{name}'.", "failed"
    else:
        try:
            kwargs = dict(args)
            if spec.wants_ctx:
                kwargs["ctx"] = ctx or ToolContext()
            raw = await spec.fn(**kwargs)
            text = guardrails.scrub_untrusted(_format(raw))
            outcome = _outcome(text, raw)
        except Exception as exc:
            log.error("Tool '%s' failed: %s", name, exc, exc_info=True)
            text, outcome = f"Lỗi khi thực thi công cụ '{name}': {exc}", "failed"
    TraceLogger.log_trace(action_name=name, args=args, outcome=outcome, output=text,
                          duration=time.time() - started, error_message=text if outcome == "failed" else "")
    return ToolResult(text, outcome)

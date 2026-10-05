"""Module quản lý prompt tập trung (spec 2026-09-25 mục 2)."""
import string
from pathlib import Path

_PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompt"
_CACHE: dict[str, str] = {}

_DEFAULTS: dict[str, dict[str, str]] = {}


def _personalize(text: str) -> str:
    from engine.prompts.honorific import personalize
    return personalize(text)


def load(name: str, **vars) -> str:
    """Nạp template prompt/<name>.md, cache nội dung và format biến dạng {var}.
    Kiểm tra thiếu biến và báo KeyError nếu template yêu cầu biến chưa được cung cấp."""
    if name not in _CACHE:
        file_path = _PROMPT_DIR / f"{name}.md"
        if not file_path.is_file():
            raise FileNotFoundError(f"Prompt template not found: {file_path}")
        _CACHE[name] = file_path.read_text(encoding="utf-8")

    template = _CACHE[name]

    formatter = string.Formatter()
    field_names = {fname for _, fname, _, _ in formatter.parse(template) if fname is not None}

    if not field_names and not vars:
        return _personalize(template)

    merged_vars = dict(_DEFAULTS.get(name, {}))
    merged_vars.update(vars)

    missing = field_names - set(merged_vars.keys())
    if missing:
        raise KeyError(f"Missing required prompt variables for '{name}': {missing}")

    return _personalize(template.format(**merged_vars))


def clear_cache():
    """Xóa cache template (dùng trong test hoặc khi reload)."""
    _CACHE.clear()

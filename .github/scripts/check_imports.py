"""Kiểm tra mọi `from engine... import X` trỏ tới module và tên có thật.

Bắt lỗi kiểu xoá/đổi tên hàm mà quên sửa nơi import — ruff không thấy được vì
import nội bộ thường nằm trong thân hàm (lazy import) và chỉ nổ lúc chạy.
Chạy: python .github/scripts/check_imports.py
"""
import ast
import subprocess
import sys
from pathlib import Path

ROOTS = ("engine", "hooks", "plugins", "skills", "server")
SKIP = (".agents/", ".claude/", "examples/")


def module_path(module: str) -> Path | None:
    base = Path(*module.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.exists():
            return candidate
    return base if base.is_dir() else None


_defined: dict[Path, set[str]] = {}


def defined_names(path: Path) -> set[str]:
    if path not in _defined:
        names: set[str] = set()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                names.add(node.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                names.update((a.asname or a.name).split(".")[0] for a in node.names)
        _defined[path] = names
    return _defined[path]


def main() -> int:
    files = subprocess.check_output(["git", "ls-files", "*.py"], text=True).split()
    errors = []
    for file in files:
        if file.startswith(SKIP):
            continue
        tree = ast.parse(Path(file).read_text(encoding="utf-8"), filename=file)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                if node.module.split(".")[0] not in ROOTS:
                    continue
                target = module_path(node.module)
                if target is None:
                    errors.append(f"{file}:{node.lineno}: không có module {node.module}")
                    continue
                for alias in node.names:
                    if alias.name == "*" or module_path(f"{node.module}.{alias.name}"):
                        continue
                    source = target if target.suffix == ".py" else target / "__init__.py"
                    if not source.exists() or alias.name not in defined_names(source):
                        errors.append(f"{file}:{node.lineno}: {node.module} không có '{alias.name}'")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "engine" and module_path(alias.name) is None:
                        errors.append(f"{file}:{node.lineno}: không có module {alias.name}")
    print("\n".join(errors) or "Import nội bộ: OK")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

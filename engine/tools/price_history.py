"""So giá market_price với lần tra thành công gần nhất trước hôm nay (ngài 2026-10-18).

Không có kho riêng: kết quả đã nằm trong bảng outcomes (Dream giữ 14 ngày). Code tách từng dòng bảng Markdown thành
(mặt hàng, cột) → số, rồi tính chênh lệch; model chỉ đọc lại, không tự tính."""
import json
import re
import sqlite3
from datetime import datetime

from engine.core.memory import DB_PATH

_COMPARE = re.compile(r"hôm qua|hôm trước|so với|so sánh|thay đổi|tăng|giảm|biến động|chênh|có gì khác", re.I)
_NUM = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?")


def wants_compare(text: str) -> bool:
    return bool(_COMPARE.search(text or ""))


def _number(cell: str) -> float | None:
    m = _NUM.search(cell)
    return float(m.group().replace(".", "").replace(",", ".")) if m else None


def parse_rows(text: str) -> dict[tuple[str, str], float]:
    """Bảng Markdown → {(cột đầu của dòng, tên cột): giá}. Dòng tiêu đề là dòng ngay trên dòng | :---: |."""
    rows: dict[tuple[str, str], float] = {}
    header: list[str] = []
    lines = [ln.strip() for ln in (text or "").splitlines()]
    for i, line in enumerate(lines):
        if not line.startswith("|"):
            header = []
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(re.fullmatch(r":?-+:?", c) for c in cells):
            continue
        if i + 1 < len(lines) and re.fullmatch(r"\|(\s*:?-+:?\s*\|)+", lines[i + 1]):
            header = cells
            continue
        for col, cell in zip(header[1:], cells[1:]):
            value = _number(cell)
            if value is not None:
                rows[(cells[0], col)] = value
    return rows


def _fmt(v: float) -> str:
    if v == int(v):
        return f"{int(v):,}".replace(",", ".")
    return f"{v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _previous(new_rows: dict, now: datetime, db_path) -> tuple[datetime, dict] | None:
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    conn = sqlite3.connect(db_path)
    try:
        found = conn.execute(
            "SELECT traces, created_at FROM outcomes WHERE status='success' AND tools LIKE '%market_price%'"
            " AND created_at < ? ORDER BY created_at DESC", (start_of_day,)).fetchall()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    for traces, created in found:
        old = {}
        for t in json.loads(traces or "[]"):
            if t.get("tool") == "market_price":
                old.update(parse_rows(t.get("result", "")))
        if old.keys() & new_rows.keys():
            return datetime.fromtimestamp(created), old
    return None


def compare(new_text: str, now: datetime | None = None, db_path=DB_PATH) -> str:
    """Đoạn chữ so sánh để nối vào kết quả market_price."""
    now = now or datetime.now()
    new_rows = parse_rows(new_text)
    prev = _previous(new_rows, now, db_path) if new_rows else None
    if not prev:
        return "📈 Chưa có lần tra giá nào trước hôm nay cho các mục này để so sánh (hệ thống giữ kết quả tra 14 ngày)."
    when, old = prev
    label = f"lần tra {when:%H:%M} ngày {when:%d/%m}"
    changed = [(k, old[k], v) for k, v in new_rows.items() if k in old and old[k] != v]
    same = sum(1 for k, v in new_rows.items() if k in old and old[k] == v)
    if not changed:
        return f"📈 Không có thay đổi so với {label}."
    lines = [f"📈 **So với {label}:**"]  # bảng giá đã có ở trên: chỉ báo mục đổi giá, không vẽ lại bảng
    for (item, col), before, after in changed:
        lines.append(f"- {item} ({col}): {'tăng' if after > before else 'giảm'} {_fmt(abs(after - before))}, nay {_fmt(after)}")
    if same:
        lines.append(f"{same} mục khác không đổi.")
    return "\n".join(lines)

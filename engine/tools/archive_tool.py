"""Tệp nén đính kèm (2026-09-28): liệt kê bằng bsdtar của Windows (libarchive: zip, 7z, rar/rar5, tar, gz,
bz2, xz, zst) và chỉ giải nén đúng MỘT tệp khi bên trong có đúng một tệp xử lý được. Không cài thư viện mới.
ponytail: không dùng UnRAR.exe dự phòng — libarchive 3.8 đọc được RAR5; thêm khi gặp RAR nó không mở được."""
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from uuid import uuid4

ARCHIVE_EXTENSIONS = (".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".zst")
MAX_ENTRIES = 200
MAX_BYTES = 200 * 1024 * 1024
TIMEOUT = 60


@dataclass
class ArchiveScan:
    processable: list[str] = field(default_factory=list)  # tên thành viên xử lý được
    skipped: list[str] = field(default_factory=list)
    extracted: Path | None = None
    error: str = ""


def is_archive(filename: str) -> bool:
    return filename.lower().endswith(ARCHIVE_EXTENSIONS)


def tar_exe() -> str:
    system_tar = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"
    return str(system_tar) if system_tar.exists() else (shutil.which("tar") or "tar")


def _list(archive: Path) -> list[tuple[str, int, bool]]:
    """[(tên, kích thước, là thư mục)]. Cột ngày theo ngôn ngữ máy ("Thg9 28 08:00") nên tách theo khoảng trắng."""
    out = subprocess.run([tar_exe(), "-tvf", str(archive)], capture_output=True, timeout=TIMEOUT)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.decode("utf-8", "replace").strip()[:200] or "không đọc được tệp nén")
    entries = []
    for line in out.stdout.decode("utf-8", "replace").splitlines():
        parts = line.split(None, 8)
        if len(parts) == 9 and parts[4].isdigit():
            entries.append((parts[8], int(parts[4]), parts[0].startswith("d")))
    return entries


def _safe(name: str) -> bool:
    p = PurePosixPath(name.replace("\\", "/"))
    return not p.is_absolute() and ".." not in p.parts and ":" not in name


def scan_and_extract(archive: Path, is_processable) -> ArchiveScan:
    """is_processable(extension) -> bool. Chỉ giải nén khi có đúng một tệp xử lý được."""
    scan = ArchiveScan()
    try:
        entries = _list(archive)
    except (RuntimeError, subprocess.TimeoutExpired, OSError) as exc:
        scan.error = f"không đọc được tệp nén ({exc})"
        return scan
    if len(entries) > MAX_ENTRIES:
        scan.error = f"tệp nén có quá nhiều mục (> {MAX_ENTRIES})"
        return scan
    sizes = {}
    for name, size, is_dir in entries:
        if is_dir:
            continue
        base = PurePosixPath(name.replace("\\", "/")).name
        ext = PurePosixPath(base).suffix.lower()
        if _safe(name) and not is_archive(base) and is_processable(ext):
            scan.processable.append(name)
            sizes[name] = size
        else:
            scan.skipped.append(base)
    if len(scan.processable) != 1:
        return scan
    member = scan.processable[0]
    if sizes[member] > MAX_BYTES:
        scan.error = f"tệp bên trong quá lớn (> {MAX_BYTES // (1024 * 1024)} MB)"
        return scan
    dest = archive.parent / f"{uuid4().hex}_x"
    dest.mkdir()
    try:
        out = subprocess.run([tar_exe(), "-xf", str(archive), "-C", str(dest), member],
                             capture_output=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        scan.error = "giải nén quá thời gian"
        return scan
    target = (dest / member).resolve()
    if out.returncode != 0 or not target.is_file() or not target.is_relative_to(dest.resolve()):
        msg = out.stderr.decode("utf-8", "replace").strip()
        scan.error = "không giải nén được" + (" (có mật khẩu?)" if "passphrase" in msg.lower() or "encrypt" in msg.lower() else "") + (f": {msg[:150]}" if msg else "")
        return scan
    scan.extracted = target
    return scan

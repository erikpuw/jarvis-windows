"""Process-tree utilities for clean shutdown on Windows.

JARVIS runs a two-process model (supervisor -> worker). The worker spawns
stream_tts, redis (when self-started), MCP stdio subprocesses, and tool
helpers. Force-killing the worker alone orphans those descendants and they
keep holding ports (8082, 8340, 6379). This module enumerates every
descendant PID that server.py spawned and force-kills them all, which is the
"các pid của server.py chạy cái nào là kill cái đó" pattern.

Enumeration uses the Toolhelp32 snapshot API via ctypes (no wmic, no psutil).
"""

import ctypes
import os
import subprocess
from ctypes import wintypes

_TH32CS_SNAPPROCESS = 0x00000002
_INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value


class _PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(wintypes.ULONG)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]


def _snapshot_parent_map() -> dict:
    """Return {pid: ppid} for every live process on the system."""
    if os.name != "nt":
        raise NotImplementedError("process tree helpers are Windows-only")
    h = ctypes.windll.kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if h == _INVALID_HANDLE_VALUE:
        return {}
    mapping = {}
    try:
        pe = _PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(_PROCESSENTRY32)
        if ctypes.windll.kernel32.Process32First(h, ctypes.byref(pe)):
            while True:
                mapping[int(pe.th32ProcessID)] = int(pe.th32ParentProcessID)
                if not ctypes.windll.kernel32.Process32Next(h, ctypes.byref(pe)):
                    break
    finally:
        ctypes.windll.kernel32.CloseHandle(h)
    return mapping


def list_descendant_pids(root_pid: int) -> list:
    """Return every descendant PID of root_pid (BFS order), excluding root."""
    parent_map = _snapshot_parent_map()
    children = {}
    for pid, ppid in parent_map.items():
        children.setdefault(ppid, []).append(pid)

    result = []
    queue = [root_pid]
    seen = {root_pid}
    while queue:
        pid = queue.pop(0)
        for child in children.get(pid, ()):
            if child not in seen:
                seen.add(child)
                result.append(child)
                queue.append(child)
    return result


def _taskkill(pid: int) -> bool:
    try:
        r = subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True,
            timeout=10,
        )
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def force_kill_pids(pids) -> int:
    """Force-kill each pid via taskkill. Returns number successfully signaled."""
    killed = 0
    for pid in pids:
        if _taskkill(int(pid)):
            killed += 1
    return killed


def kill_descendants(root_pid: int) -> int:
    """Enumerate every descendant of root_pid and force-kill them all.

    Returns the number of processes killed. If root_pid is gone, no-op.
    """
    pids = list_descendant_pids(root_pid)
    if not pids:
        return 0
    return force_kill_pids(pids)


def find_listening_pids(port: int) -> list:
    """Find all PIDs listening on a given TCP port on Windows."""
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return []

    pids = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[-1].upper() == "LISTENING":
            local_addr = parts[1]
            if local_addr.endswith(f":{port}"):
                try:
                    pids.add(int(parts[-2]))
                except ValueError:
                    continue
    return sorted(pids)


def free_port(port: int) -> list:
    """Force-kill whatever is already LISTENING on `port`, if anything."""
    pids = find_listening_pids(port)
    if pids:
        force_kill_pids(pids)
    return pids


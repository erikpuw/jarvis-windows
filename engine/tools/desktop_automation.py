"""
Desktop Automation — Điều khiển desktop Windows: click, nhập text, lấy controls.

Chạy PowerShell để tương tác với UI Windows qua SendKeys, UIAutomation.
"""

import asyncio
import logging
import re

log = logging.getLogger("jarvis.desktop_automation")

try:
    from engine.server.llm_server import _log_usage
except ImportError:
    _log_usage = lambda *a, **kw: None

_PS_CMD = ["powershell.exe", "-NoProfile", "-Command"]


async def _run_ps(script: str, timeout: float = 15) -> tuple[str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *_PS_CMD, script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return stdout.decode("utf-8", errors="replace").strip(), stderr.decode("utf-8", errors="replace").strip()
    except asyncio.TimeoutError:
        return "", "TIMEOUT"
    except Exception as e:
        return "", str(e)

async def _get_process_name(app_name: str) -> str:
    """Tra cứu process name thực tế của một ứng dụng từ tên hiển thị."""
    script = (
        f'$name = "{app_name}"\n'
        f'# 1. Exact process match\n'
        f'$proc = Get-Process -Name $name -ErrorAction SilentlyContinue | Select-Object -First 1\n'
        f'if (-not $proc) {{ $proc = Get-Process -Name "$name*" -ErrorAction SilentlyContinue | Select-Object -First 1 }}\n'
        f'if (-not $proc) {{\n'
        f'  # 2. Registry App Paths\n'
        f'  $regPath = Get-ItemProperty "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\$name.exe" -Name "(default)" -ErrorAction SilentlyContinue\n'
        f'  if (-not $regPath) {{ $regPath = Get-ItemProperty "HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\$name.exe" -Name "(default)" -ErrorAction SilentlyContinue }}\n'
        f'  if ($regPath) {{ $exePath = $regPath."(default)"; $exeName = [System.IO.Path]::GetFileNameWithoutExtension($exePath); $proc = Get-Process -Name $exeName -ErrorAction SilentlyContinue | Select-Object -First 1 }}\n'
        f'}}\n'
        f'if (-not $proc) {{\n'
        f'  # 3. Map known display names\n'
        f'  $map = @{{\n'
        f'    "task manager"="Taskmgr"; "taskmgr"="Taskmgr";\n'
        f'    "notepad"="notepad"; "paint"="mspaint";\n'
        f'    "calculator"="Calculator"; "calc"="Calculator"; "cal"="Calculator";\n'
        f'    "control panel"="control panel"; "control"="control panel";\n'
        f'    "cmd"="cmd"; "command prompt"="cmd";\n'
        f'    "powershell"="powershell"; "power shell"="powershell";\n'
        f'    "settings"="SystemSettings"; "System Setting"="SystemSettings";\n'
        f'    "windows update"="SystemSettings"; "windowsupdate"="SystemSettings";\n'
        f'    "registry"="regedit"; "regedit"="regedit";\n'
        f'    "explorer"="explorer"; "file explorer"="explorer";\n'
        f'    "chrome"="chrome"; "edge"="msedge"; "microsoft edge"="msedge";\n'
        f'    "snipping tool"="SnippingTool"; "snip sketch"="SnippingTool"; "snip and sketch"="SnippingTool";\n'
        f'    "word"="WINWORD"; "excel"="EXCEL"; "powerpoint"="POWERPNT"; "outlook"="OUTLOOK";\n'
        f'    "teams"="Teams"; "zoom"="Zoom"; "discord"="Discord"; "slack"="slack";\n'
        f'    "spotify"="Spotify"; "vlc"="vlc"; "notepad++"="notepad++"; "vscode"="Code";\n'
        f'  }}\n'
        f'  $mapped = $map[$name.ToLower()]\n'
        f'  if ($mapped) {{ $proc = Get-Process -Name $mapped -ErrorAction SilentlyContinue | Select-Object -First 1 }}\n'
        f'}}\n'
        f'if (-not $proc) {{\n'
        f'  # 4. Search by MainWindowTitle\n'
        f'  $proc = Get-Process | Where-Object {{ $_.MainWindowTitle -like "*$name*" }} | Select-Object -First 1\n'
        f'}}\n'
        f'if ($proc) {{ Write-Output $proc.ProcessName }} else {{ Write-Output "" }}\n'
    )
    stdout, _ = await _run_ps(script, timeout=5)
    return stdout.strip()


async def _is_process_running(process_name: str) -> bool:
    if not process_name:
        return False
    script = f'if (Get-Process -Name "{process_name}" -ErrorAction SilentlyContinue) {{ Write-Output "YES" }} else {{ Write-Output "NO" }}'
    stdout, _ = await _run_ps(script, timeout=5)
    return "YES" in stdout


async def _open_via_start_menu(app_name: str) -> bool:
    """Bấm Win → gõ tên → Enter → chờ process xuất hiện.
    
    Dùng keybd_event (user32.dll) để gửi phím Windows ở system level,
    không phụ thuộc vào foreground window.
    """
    safe_name = re.sub(r'[^\w\s-]', '', app_name)
    script = (
        'Add-Type @"\n'
        'using System;\n'
        'using System.Runtime.InteropServices;\n'
        'public class KeySim {\n'
        '    [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, int dwExtraInfo);\n'
        '    [DllImport("user32.dll")] public static extern short VkKeyScan(char ch);\n'
        '    [DllImport("user32.dll")] public static extern uint MapVirtualKey(uint uCode, uint uMapType);\n'
        '}\n'
        '"@\n'
        'function SendChar($c) {\n'
        '    $vk = [KeySim]::VkKeyScan($c) -band 0xFF\n'
        '    $scan = [KeySim]::MapVirtualKey($vk, 0)\n'
        '    [KeySim]::keybd_event($vk, $scan, 0, 0)\n'
        '    Start-Sleep -Milliseconds 20\n'
        '    [KeySim]::keybd_event($vk, $scan, 2, 0)\n'
        '    Start-Sleep -Milliseconds 20\n'
        '}\n'
        'function SendKey($vk) {\n'
        '    $scan = [KeySim]::MapVirtualKey($vk, 0)\n'
        '    [KeySim]::keybd_event($vk, $scan, 0, 0)\n'
        '    Start-Sleep -Milliseconds 30\n'
        '    [KeySim]::keybd_event($vk, $scan, 2, 0)\n'
        '}\n'
        '# VK_LWIN = 0x5B, VK_RETURN = 0x0D\n'
        'Start-Sleep -Milliseconds 300\n'
        'SendKey 0x5B\n'
        'Start-Sleep -Milliseconds 800\n'
        f'foreach ($ch in \"{safe_name}\".ToCharArray()) {{ SendChar $ch }}\n'
        'Start-Sleep -Milliseconds 1500\n'
        'SendKey 0x0D\n'
    )
    _, stderr = await _run_ps(script, timeout=20)
    if "TIMEOUT" in stderr:
        return False
    await asyncio.sleep(3)
    return True


# Map: tên hiển thị → (shell_cmd để Start-Process, process_name để verify)
# Tách riêng để tránh nhầm giữa protocol URI và process name thực tế
_KNOWN_APPS: dict[str, tuple[str, str]] = {
    "notepad":         ("notepad",                   "notepad"),
    "task manager":    ("taskmgr",                   "Taskmgr"),
    "taskmgr":         ("taskmgr",                   "Taskmgr"),
    "trình quản lý tác vụ": ("taskmgr",              "Taskmgr"),
    "paint":           ("mspaint",                   "mspaint"),
    "vẽ":              ("mspaint",                   "mspaint"),
    "control panel":   ("control",                   "control"),
    "control":         ("control",                   "control"),
    "bảng điều khiển":  ("control",                   "control"),
    "calculator":      ("calc",                      "Calculator"),
    "calc":            ("calc",                      "Calculator"),
    "cal":             ("calc",                      "Calculator"),
    "máy tính":        ("calc",                      "Calculator"),
    "cmd":             ("cmd",                       "cmd"),
    "command prompt":  ("cmd",                       "cmd"),
    "powershell":      ("powershell",                "powershell"),
    "power shell":     ("powershell",                "powershell"),
    "explorer":        ("explorer",                  "explorer"),
    "file explorer":   ("explorer",                  "explorer"),
    "registry":        ("regedit",                   "regedit"),
    "regedit":         ("regedit",                   "regedit"),
    "snipping tool":   ("SnippingTool",              "SnippingTool"),
    "snip & sketch":   ("SnippingTool",              "SnippingTool"),
    "edge":            ("microsoft-edge:",           "msedge"),
    "microsoft edge":  ("microsoft-edge:",           "msedge"),
    "chrome":          ("chrome",                    "chrome"),
    "word":            ("winword",                   "WINWORD"),
    "excel":           ("excel",                     "EXCEL"),
    "powerpoint":      ("powerpnt",                  "POWERPNT"),
    "outlook":         ("outlook",                   "OUTLOOK"),
}


_MAX_APP_NAME_WORDS = 4


def _clean_app_name(app_name: str) -> str:
    """Only the characters an app name has. The name is put inside PowerShell double-quoted
    strings below, where `$(...)` runs a command, so every metacharacter ($ ( ) " ` & ; % ^ * [ ])
    is dropped — open/close must run on this same name that app_target_exists checked."""
    return " ".join(re.sub(r"[^\w \-\.\+]", "", (app_name or "").replace(".exe", "")).split())


async def app_target_exists(app_name: str) -> bool:
    """True only if `app_name` really names something openable/closable here: a known app,
    a running process, or a Start Menu entry (incl. Store apps). A whole sentence or an
    unknown phrase is not an app — without this check open_application typed such text
    into the Start Menu search and close_application matched it against window titles
    (jarvis.log 2026-09-20 09:54: 'thử lại giọng đọc tts')."""
    name = _clean_app_name(app_name).lower()
    if not name or len(name.split()) > _MAX_APP_NAME_WORDS:
        return False
    if name in _KNOWN_APPS:
        return True
    if await _get_process_name(name):
        return True
    out, _ = await _run_ps(
        f'Get-StartApps | Where-Object {{ $_.Name -like "*{name}*" }} | Select-Object -First 1 -ExpandProperty Name',
        timeout=10,
    )
    return bool(out.strip())


async def open_application(app_name: str) -> bool:
    app_name = _clean_app_name(app_name)
    if not app_name or not await app_target_exists(app_name):
        log.warning("Refusing to open %r: not a known app, running process or Start Menu entry", app_name)
        return False

    # Ghi log thông tin tiến trình hiện tại nếu đã chạy
    proc_name = await _get_process_name(app_name)
    if proc_name:
        log.info("App is currently running: %s (%s), but we will attempt to open/activate a new window.", app_name, proc_name)


    # Cách 1: Start-Process với shell command đã biết
    app_entry = _KNOWN_APPS.get(app_name.lower())
    if app_entry:
        shell_cmd, verify_proc = app_entry
        script = f'Start-Process "{shell_cmd}"'
        await _run_ps(script, timeout=6)
        await asyncio.sleep(2)
        if await _is_process_running(verify_proc) or await _is_process_running(app_name):
            log.info("Opened via Start-Process: %s (shell_cmd=%s)", app_name, shell_cmd)
            return True
        log.info("Start-Process sent for %s but process not detected yet, continuing...", app_name)

    # Cách 2: Win key → gõ tên → Enter (Start Menu search — mọi app kể cả bên thứ 3)
    ok = await _open_via_start_menu(app_name)
    if ok:
        await asyncio.sleep(3)
        retries = 6
        for i in range(retries):
            proc = await _get_process_name(app_name)
            if proc:
                log.info("Opened via Start Menu search: %s (process: %s)", app_name, proc)
                return True
            log.info("Waiting for process after Start Menu... attempt %d/%d", i + 1, retries)
            await asyncio.sleep(1.5)

    # Cách 3: cmd /c start — fallback cuối dùng Windows Shell
    log.info("Trying cmd /c start fallback for: %s", app_name)
    safe = app_name.replace('"', '')
    script3 = f'cmd /c start "" "{safe}"'
    await _run_ps(script3, timeout=8)
    await asyncio.sleep(2.5)
    proc = await _get_process_name(app_name)
    if proc:
        log.info("Opened via cmd /c start fallback: %s (process: %s)", app_name, proc)
        return True

    log.warning("Failed to open application after all methods: %s", app_name)
    return False


async def close_application(app_name: str) -> bool:
    app_name = _clean_app_name(app_name)
    if not app_name or not await app_target_exists(app_name):
        log.warning("Refusing to close %r: not a known app, running process or Start Menu entry", app_name)
        return False
    proc_name = await _get_process_name(app_name)

    def make_script(target_name: str) -> str:
        return (
            f'$p = Get-Process -Name "{target_name}" -ErrorAction SilentlyContinue;\n'
            f'if ($p) {{\n'
            f'    $p | Stop-Process -Force -ErrorAction SilentlyContinue;\n'
            f'    Start-Sleep -Milliseconds 600;\n'
            f'    $p2 = Get-Process -Name "{target_name}" -ErrorAction SilentlyContinue;\n'
            f'    if (-not $p2) {{ Write-Output "KILLED" }} else {{ Write-Output "FAILED_TO_KILL" }}\n'
            f'}} else {{\n'
            f'    Write-Output "NOT_FOUND"\n'
            f'}}\n'
        )

    # 1. Thử tắt bằng process name được ánh xạ trước
    if proc_name:
        script = make_script(proc_name)
        stdout, _ = await _run_ps(script, timeout=10)
        if "KILLED" in stdout:
            log.info("Closed application: %s (process: %s)", app_name, proc_name)
            return True
        elif "FAILED_TO_KILL" in stdout:
            log.warning("Failed to kill mapped process: %s", proc_name)

    # 2. Thử tắt trực tiếp bằng tên nhập vào
    script_direct = make_script(app_name)
    stdout, _ = await _run_ps(script_direct, timeout=10)
    if "KILLED" in stdout:
        log.info("Closed application direct name match: %s", app_name)
        return True
    elif "FAILED_TO_KILL" in stdout:
        log.warning("Failed to kill direct process: %s", app_name)

    # 3. Fallback: Tìm process bằng MainWindowTitle hoặc một phần ProcessName
    script_fallback = (
        f'$procs = @(Get-Process | Where-Object {{ $_.MainWindowTitle -like "*{app_name}*" -or $_.ProcessName -like "*{app_name}*" }})\n'
        f'if ($procs) {{\n'
        f'    $procs | Stop-Process -Force -ErrorAction SilentlyContinue;\n'
        f'    Start-Sleep -Milliseconds 600;\n'
        f'    $still_running = @(Get-Process | Where-Object {{ $_.MainWindowTitle -like "*{app_name}*" -or $_.ProcessName -like "*{app_name}*" }})\n'
        f'    if (-not $still_running) {{ Write-Output "KILLED" }} else {{ Write-Output "FAILED_TO_KILL" }}\n'
        f'}} else {{\n'
        f'    Write-Output "NOT_FOUND"\n'
        f'}}\n'
    )
    stdout, _ = await _run_ps(script_fallback, timeout=10)
    if "KILLED" in stdout:
        log.info("Closed application via fallback title/name match: %s", app_name)
        return True

    log.warning("Application not found or could not be closed: %s", app_name)
    return False


def clean_query(text: str) -> str:
    """Lọc các từ khóa phụ thuộc/yêu cầu lịch sự khỏi câu lệnh truy vấn."""
    t = text.lower().strip()
    t = re.sub(r"^(?:hãy|giúp|vui\s+lòng|làm\s+ơn|cho\s+tôi\s+biết|tìm\s+kiếm|tra\s+cứu|xem|check|search|phát|xem\s+phim|mở\s+nhạc|nghe\s+nhạc)\s+", "", t)
    return t.strip()


def extract_app_name(text: str) -> str:
    """Trích xuất tên ứng dụng từ câu lệnh thô (ví dụ 'mở notepad' -> 'notepad')."""
    t = clean_query(text)
    # Loại bỏ hàng loạt các từ khóa hành động và kính ngữ ở đầu câu
    t = re.sub(r"^(?:mở|open|chạy|start|khởi\s+động|launch|run|tắt|đóng|close|stop|dừng|giúp\s+tôi|ứng\s+dụng|app|\s+)+", "", t)
    return t.strip()

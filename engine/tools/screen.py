"""
JARVIS Screen Awareness — see what's on the user's Windows screen.

Two capabilities:
1. Window/app list via PowerShell (fast, text-based)
2. Screenshot via PowerShell → LLM vision API (sees everything)
"""

import asyncio
import base64
import logging
import os
import tempfile
from pathlib import Path
from typing import AsyncGenerator


log = logging.getLogger("jarvis.screen")

_PS_CMD = ["powershell.exe", "-NoProfile", "-Command"]

_vision_client = None

def _get_vision_client():
    global _vision_client
    if _vision_client is not None:
        return _vision_client
    url = os.getenv("VISION_URL")
    if not url:
        return None
    try:
        import openai
        key = os.getenv("VISION_API_KEY")
        _vision_client = openai.AsyncOpenAI(base_url=url, api_key=key)
        log.info("Vision client initialized: %s", url)
    except Exception as e:
        log.warning("Vision client init failed: %s", e)
        return None
    return _vision_client


async def _run_ps(script: str, timeout: float = 10) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            *_PS_CMD, script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return stdout.decode("utf-8", errors="replace").strip()
    except Exception as e:
        log.warning(f"PS error: {e}")
        return ""


async def get_active_windows() -> list[dict]:
    """Get list of visible windows with app name and title.

    Returns list of {"app": str, "title": str, "frontmost": bool}.
    """
    script = '''
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
using System.Diagnostics;
public class WinHelper {
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    public static string GetInfo() {
        IntPtr hWnd = GetForegroundWindow();
        StringBuilder sb = new StringBuilder(256);
        GetWindowText(hWnd, sb, 256);
        GetWindowThreadProcessId(hWnd, out uint pid);
        string name = "";
        try { name = Process.GetProcessById((int)pid).ProcessName; } catch {}
        return name + "|||" + sb.ToString();
    }
}
"@
[WinHelper]::GetInfo()
'''
    raw = await _run_ps(script, timeout=5)
    windows = []
    if raw and "|||" in raw:
        parts = raw.split("|||")
        windows.append({
            "app": parts[0].strip(),
            "title": parts[1].strip() if len(parts) > 1 else "",
            "frontmost": True,
        })

    # Also get all windows with titles
    script2 = '''
Get-Process | Where-Object { $_.MainWindowTitle -ne "" } | ForEach-Object {
    $_.ProcessName + "|||" + $_.MainWindowTitle
}
'''
    raw2 = await _run_ps(script2, timeout=5)
    if raw2:
        for line in raw2.split("\n"):
            parts = line.strip().split("|||")
            if len(parts) >= 2:
                app = parts[0].strip()
                title = parts[1].strip()
                if app and title and not any(w.get("app") == app and w.get("title") == title for w in windows):
                    windows.append({
                        "app": app,
                        "title": title,
                        "frontmost": False,
                    })

    return windows


async def get_running_apps() -> list[str]:
    """Get list of running application names (with windows)."""
    script = '''
Get-Process | Where-Object { $_.MainWindowTitle -ne "" } | Select-Object -ExpandProperty ProcessName -Unique
'''
    raw = await _run_ps(script, timeout=5)
    if raw:
        return [a.strip() for a in raw.split("\n") if a.strip()]
    return []


async def take_screenshot() -> str | None:
    """Take a screenshot and return base64-encoded PNG."""
    tmp = Path(tempfile.mktemp(suffix=".png"))
    script = f'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$image = New-Object System.Drawing.Bitmap($screen.Width, $screen.Height)
$graphics = [System.Drawing.Graphics]::FromImage($image)
$graphics.CopyFromScreen($screen.X, $screen.Y, 0, 0, $screen.Size)
$image.Save("{tmp}")
$graphics.Dispose()
$image.Dispose()
'''
    # _run_ps trong screen.py trả về str (stdout only) — không unpack tuple
    await _run_ps(script, timeout=15)
    if tmp.exists() and tmp.stat().st_size > 0:
        data = base64.b64encode(tmp.read_bytes()).decode()
        try:
            tmp.unlink()
        except Exception:
            pass
        log.info(f"Screenshot captured: {len(data)} bytes")
        return data
    return None


async def take_screenshot_file(output_path: str) -> bool:
    """Take a screenshot using Windows PowerShell and save it directly to output_path."""
    try:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        script = f'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$image = New-Object System.Drawing.Bitmap($screen.Width, $screen.Height)
$graphics = [System.Drawing.Graphics]::FromImage($image)
$graphics.CopyFromScreen($screen.X, $screen.Y, 0, 0, $screen.Size)
$image.Save("{out_p.resolve()}")
$graphics.Dispose()
$image.Dispose()
'''
        await _run_ps(script, timeout=15)
        if out_p.exists() and out_p.stat().st_size > 0:
            log.info(f"Screenshot saved to: {output_path}")
            return True
    except Exception as e:
        log.warning(f"Failed to save screenshot to {output_path}: {e}")
    return False


# Mô tả vision hiện nguyên văn cho ngài (display, 2026-10-13): không chào, không xưng "bạn" (e2e: xưng sai: bạn).
NO_ADDRESS = "Viết mô tả khách quan, không chào hỏi, không xưng hô với người đọc."


async def analyze_screenshot(
    screenshot_b64: str,
    prompt: str = "Hãy mô tả chi tiết những gì bạn thấy trên màn hình này bằng tiếng Việt.",
    llm_client=None,
    vision_model: str | None = None,
    max_tokens: int = 2048,
    stream: bool = True,
) -> str | AsyncGenerator[str, None]:
    """Gửi screenshot đến vision LLM để phân tích.

    Dùng vision server (VISION_URL) nếu không có llm_client. Model lấy từ VISION_MODEL,
    trống/'auto' thì theo model chat đang chạy (llm_server.vision_model_name).
    """
    from engine.server.llm_server import (
        StreamThinkStripper, strip_think, vision_model_name, vision_request_kwargs,
    )

    if not screenshot_b64:
        return "" if not stream else None
    client = llm_client or _get_vision_client()
    if not client:
        return "" if not stream else None
        
    model = vision_model or vision_model_name()

    if not model:
        log.warning("No vision model configured (VISION_MODEL và model chat đều chưa đặt)")
        return "" if not stream else None
    try:
        # Tham số instruct + tắt thinking theo model đang chạy (gemma/qwen/bonsai), không gán cứng.
        content_list = [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}},
            {"type": "text", "text": f"{prompt}\n{NO_ADDRESS}"},
        ]

        response = await client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            **vision_request_kwargs(),
            messages=[
                {
                    "role": "user",
                    "content": content_list,
                }
            ],
            stream=stream,
        )
        if stream:
            async def stream_generator():
                stripper = StreamThinkStripper()
                async for chunk in response:
                    if chunk.choices and chunk.choices[0].delta.content:
                        text = stripper.process(chunk.choices[0].delta.content)
                        if text:
                            yield text
            return stream_generator()
        else:
            return strip_think(response.choices[0].message.content or "")
    except Exception as e:
        log.warning("Vision analysis failed (model=%s): %s", model, e)
        return "" if not stream else None


_IMAGE_MAX_SIDE = 2048


def _image_b64(path) -> str | None:
    """PNG base64 của tệp ảnh, thu nhỏ cạnh dài còn <= 2048px (vision server không nhận ảnh quá lớn)."""
    import io
    from PIL import Image, ImageOps
    try:
        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB") if img.mode not in ("RGB", "RGBA", "L") else img
            img.thumbnail((_IMAGE_MAX_SIDE, _IMAGE_MAX_SIDE))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
    except Exception as e:
        log.warning("Cannot read image %s: %s", path, e)
        return None
    return base64.b64encode(buf.getvalue()).decode()


async def describe_image(path, prompt: str | None = None, llm_client=None, stream: bool = True) -> str | AsyncGenerator[str, None]:
    """Phân tích một tệp ảnh bằng vision model (cùng đường với describe_screen)."""
    b64 = await asyncio.to_thread(_image_b64, path)
    if not b64:
        return "Không đọc được tệp ảnh này."
    ask = "Hãy phân tích bức ảnh này và trả lời bằng tiếng Việt."
    if prompt and prompt.strip():
        ask += f" Yêu cầu của người dùng: {prompt.strip()}"
    desc = await analyze_screenshot(b64, prompt=ask, llm_client=None, stream=stream)
    if (desc is None or desc == "") and llm_client:
        desc = await analyze_screenshot(b64, prompt=ask, llm_client=llm_client, stream=stream)
    return desc if desc else "Không phân tích được ảnh: model vision chưa sẵn sàng."


async def describe_screen(llm_client=None, stream: bool = True) -> str | AsyncGenerator[str, None]:
    """Describe what's on the user's screen.

    Tries screenshot + vision (model đang chạy) first. Falls back to window list.
    """
    screenshot_b64 = await take_screenshot()
    if screenshot_b64:
        # Ưu tiên dùng client Vision (VISION_URL), fallback sang llm_client
        desc = await analyze_screenshot(screenshot_b64, llm_client=None, stream=stream)
        if (desc is None or desc == "") and llm_client:
            desc = await analyze_screenshot(screenshot_b64, llm_client=llm_client, stream=stream)
        if desc is not None and desc != "":
            return desc

    # Fallback: get window list
    windows = await get_active_windows()
    apps = await get_running_apps()

    if not windows and not apps:
        return "I wasn't able to see your screen, sir."

    if windows:
        active = next((w for w in windows if w.get("frontmost")), None)
        result = f"You have {len(windows)} windows open."
        if active:
            result += f" Currently focused on {active['app']}"
            if active.get("title"):
                result += f": {active['title']}"
            result += "."
        return result

    return f"Running apps: {', '.join(apps)}."


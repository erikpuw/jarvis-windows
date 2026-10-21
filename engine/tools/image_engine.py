import logging
import os
import subprocess
import asyncio
from pathlib import Path

log = logging.getLogger("jarvis.image_engine")

_BIN_PATH = r"C:\Program Files\Upscayl\resources\bin\upscayl-bin.exe"
_MODELS_PATH = r"C:\Program Files\Upscayl\resources\models"

SUPPORTED_INPUT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
AVAILABLE_MODELS = [
    "upscayl-standard-4x",
    "upscayl-lite-4x",
    "digital-art-4x",
    "high-fidelity-4x",
    "remacri-4x",
    "ultramix-balanced-4x",
    "ultrasharp-4x",
]


async def upscale_image(
    input_path: str,
    output_path: str = None,
    scale: int = 4,
    model_name: str = "upscayl-standard-4x",
    output_format: str = "png",
) -> str:
    if not os.path.exists(_BIN_PATH):
        return f"Lỗi: Không tìm thấy upscayl-bin.exe tại {_BIN_PATH}"

    if not os.path.exists(_MODELS_PATH):
        return f"Lỗi: Không tìm thấy thư mục models tại {_MODELS_PATH}"

    if not os.path.exists(input_path):
        return f"Lỗi: File ảnh đầu vào không tồn tại: {input_path}"

    ext = Path(input_path).suffix.lower()
    if ext not in SUPPORTED_INPUT:
        return f"Lỗi: Định dạng ảnh {ext} không hỗ trợ. Chỉ chấp nhận: {', '.join(SUPPORTED_INPUT)}"

    if model_name not in AVAILABLE_MODELS:
        return f"Lỗi: Model '{model_name}' không tồn tại. Các model có sẵn: {', '.join(AVAILABLE_MODELS)}"

    if output_format not in {"png", "jpg", "jpeg", "webp"}:
        output_format = "png"

    if not output_path:
        stem = Path(input_path).stem
        parent = Path(input_path).parent
        output_path = str(parent / f"{stem}_upscaled.{output_format}")

    model_bin = os.path.join(_MODELS_PATH, f"{model_name}.bin")
    model_param = os.path.join(_MODELS_PATH, f"{model_name}.param")
    if not os.path.exists(model_param) or not os.path.exists(model_bin):
        return f"Lỗi: File model {model_name} không đầy đủ trong {_MODELS_PATH}"

    log.info(f"Upscaling: {input_path} -> {output_path} (scale={scale}, model={model_name})")

    try:
        loop = asyncio.get_event_loop()
        proc = await loop.run_in_executor(None, lambda: subprocess.run(
            [
                _BIN_PATH,
                "-i", input_path,
                "-o", output_path,
                "-s", str(scale),
                "-m", _MODELS_PATH,
                "-n", model_name,
                "-f", output_format,
            ],
            capture_output=True,
            text=True,
            timeout=300,
        ))

        if proc.returncode != 0:
            err = proc.stderr.strip() or "Không rõ lỗi"
            log.error(f"upscayl-bin failed: {err}")
            return f"Lỗi khi upscale ảnh: {err}"

        if not os.path.exists(output_path):
            return "Lỗi: Ảnh đầu ra không được tạo, không rõ nguyên nhân."

        out_size = os.path.getsize(output_path)
        log.info(f"Upscale success: {output_path} ({out_size} bytes)")
        return output_path

    except subprocess.TimeoutExpired:
        return "Lỗi: Quá thời gian xử lý ảnh (5 phút)."
    except FileNotFoundError:
        return f"Lỗi: Không tìm thấy upscayl-bin.exe tại {_BIN_PATH}. Kiểm tra lại đường dẫn."
    except Exception as e:
        log.error(f"Upscale exception: {e}", exc_info=True)
        return f"Lỗi không xác định khi upscale: {e}"

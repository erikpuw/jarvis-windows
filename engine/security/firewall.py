"""
JARVIS Local Firewall Middleware & IP Verification.
"""

import os
import logging
from pathlib import Path
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from engine.security.policy import DEFAULT_CORS_ORIGINS, NetworkPolicy, is_origin_allowed, parse_cors_origins

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Thiết lập log bảo mật riêng
LOG_DIR = Path(__file__).parents[2] / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
sec_logger = logging.getLogger("jarvis.security")
sec_logger.setLevel(logging.INFO)

# Tránh add nhiều handler nếu file được import lại
if not sec_logger.handlers:
    handler = logging.FileHandler(str(LOG_DIR / "security_alerts.log"), encoding="utf-8-sig")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    sec_logger.addHandler(handler)


def is_ip_allowed(client_host: str | None) -> bool:
    """Kiểm tra xem IP của client có được phép kết nối hay không."""
    local_only = os.getenv("JARVIS_SECURITY_LOCAL_ONLY", "true").lower() == "true"
    lan_open = os.getenv("JARVIS_SECURITY_LAN_OPEN", "true").lower() == "true"
    allowed_ips_raw = os.getenv("JARVIS_SECURITY_ALLOWED_IPS", "")
    allowed_ips = tuple(ip.strip() for ip in allowed_ips_raw.split(",") if ip.strip())
    normalized_host = "127.0.0.1" if client_host and client_host.strip().lower() == "localhost" else client_host
    return NetworkPolicy(
        local_only=local_only,
        lan_open=lan_open,
        allowed_ips=allowed_ips,
    ).is_allowed(normalized_host)


def is_request_origin_allowed(headers) -> bool:
    """Origin của trình duyệt phải là frontend JARVIS (cùng host, localhost mặc định, hoặc JARVIS_CORS_ORIGINS).

    Localhost mặc định luôn được giữ: thêm IP Tailscale vào JARVIS_CORS_ORIGINS không được khoá UI trên chính PC.
    """
    return is_origin_allowed(
        headers.get("origin"),
        headers.get("host"),
        DEFAULT_CORS_ORIGINS + parse_cors_origins(os.getenv("JARVIS_CORS_ORIGINS", "")),
    )


class SecurityFirewallMiddleware(BaseHTTPMiddleware):
    """Middleware chốt chặn bảo mật ở tầng HTTP cho FastAPI."""
    
    async def dispatch(self, request: Request, call_next) -> Response:
        client = request.client
        client_host = client.host if client else None
        
        # Nếu là request nội bộ từ các luồng router nội bộ (FastAPI client test...)
        if not client_host:
            return await call_next(request)

        if not is_ip_allowed(client_host):
            sec_logger.warning(
                f"Blocked unauthorized HTTP access attempt from IP: {client_host} "
                f"to path: {request.url.path} (Method: {request.method})"
            )
            return JSONResponse(
                status_code=403,
                content={
                    "error": "Forbidden",
                    "message": f"Truy cập bị chặn. Địa chỉ IP của bạn ({client_host}) không được phép kết nối đến máy chủ JARVIS."
                }
            )

        if request.method in _UNSAFE_METHODS and not is_request_origin_allowed(request.headers):
            sec_logger.warning(
                f"Blocked cross-origin {request.method} to {request.url.path} "
                f"from Origin: {request.headers.get('origin')}"
            )
            return JSONResponse(
                status_code=403,
                content={"error": "Forbidden", "message": "Origin không được phép."},
            )

        return await call_next(request)

"""
JARVIS Security Daemon Monitor.
Periodically scans active socket connections of JARVIS server ports to detect intrusive clients.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Callable, Optional

sec_logger = logging.getLogger("jarvis.security")

# Lưu vết danh sách IP đã cảnh báo để tránh ghi đè log liên tục
_warned_ips = set()

def get_active_network_connections(port: int = 8000) -> list[str]:
    """Sử dụng cơ chế quét hoặc socket kiểm tra nếu có thể, hoặc fallback qua psutil nếu có sẵn."""
    connected_hosts = []
    
    # Fallback nhẹ nhàng thông qua psutil (nếu có sẵn trong môi trường)
    try:
        import psutil
        for conn in psutil.net_connections(kind="inet"):
            if conn.status == "ESTABLISHED" and conn.laddr.port == port:
                raddr = conn.raddr
                if raddr:
                    connected_hosts.append(raddr.ip)
    except Exception:
        # Nếu không import được psutil hoặc thiếu quyền hệ thống đọc connection
        pass
        
    return list(set(connected_hosts))


async def monitor_network_loop(get_ws_session: Callable[[], Optional[any]], server_port: int = 8340):
    """Vòng lặp chạy ngầm định kỳ kiểm tra các kết nối vào máy chủ JARVIS."""
    from engine.security.firewall import is_ip_allowed

    sec_logger.debug(f"Security connection monitor daemon started on port {server_port}")
    heartbeat_counter = 0

    while True:
        try:
            # Kiểm tra mỗi 10 giây
            await asyncio.sleep(10)
            heartbeat_counter += 1
            
            if heartbeat_counter >= 180:
                heartbeat_counter = 0

            # Lấy danh sách kết nối mạng hiện hoạt
            active_ips = await asyncio.to_thread(get_active_network_connections, server_port)
            
            for ip in active_ips:
                if not is_ip_allowed(ip):
                    if ip not in _warned_ips:
                        sec_logger.critical(
                            f"SECURITY ALERT: Non-whitelisted IP {ip} has established "
                            f"an active network socket connection to JARVIS server (Port {server_port})!"
                        )
                        _warned_ips.add(ip)
                        
                        # Kích hoạt thông báo giọng nói qua WebSocket của client đang hoạt động (nếu có)
                        ws = get_ws_session()
                        if ws:
                            from server import safe_ws_send_json
                            await safe_ws_send_json(ws, {
                                "type": "text_chunk",
                                "text": f"[CẢNH BÁO BẢO MẬT]: Phát hiện kết nối trái phép từ địa chỉ IP {ip}."
                            })
                            
                else:
                    # Nếu IP đã an toàn hoặc đã ngắt kết nối thì có thể xóa khỏi danh sách đã cảnh báo sau này
                    if ip in _warned_ips:
                        _warned_ips.discard(ip)

        except asyncio.CancelledError:
            sec_logger.info("Security monitor daemon stopped.")
            break
        except Exception as e:
            sec_logger.error(f"Error in security monitor loop: {e}")


def start_security_monitor(get_ws_session: Callable[[], Optional[any]], server_port: int = 8340) -> asyncio.Task:
    """Tạo tác vụ chạy ngầm giám sát các kết nối mạng."""
    task = asyncio.create_task(monitor_network_loop(get_ws_session, server_port))
    return task


def run_security_check() -> str:
    """Đọc cấu hình bảo mật, log xâm nhập và giám sát trạng thái kết nối mạng active."""
    from engine.security.policy import parse_cors_origins
    
    local_only = os.getenv("JARVIS_SECURITY_LOCAL_ONLY", "true").lower() == "true"
    allowed_ips = os.getenv("JARVIS_SECURITY_ALLOWED_IPS", "")
    cors_origins = parse_cors_origins(os.getenv("JARVIS_CORS_ORIGINS", ""))
    upload_limit_raw = os.getenv("JARVIS_UPLOAD_MAX_BYTES", str(25 * 1024 * 1024))
    stt_limit_raw = os.getenv("JARVIS_STT_MAX_BYTES", str(20 * 1024 * 1024))
    upload_limit = int(upload_limit_raw) if upload_limit_raw.isdigit() and int(upload_limit_raw) > 0 else 25 * 1024 * 1024
    stt_limit = int(stt_limit_raw) if stt_limit_raw.isdigit() and int(stt_limit_raw) > 0 else 20 * 1024 * 1024
    
    # 1. Đọc log xâm nhập mạng gần đây
    log_path = Path(__file__).resolve().parent.parent.parent / "logs" / "security_alerts.log"
    blocked_attempts = []
    if log_path.exists():
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                # Lấy tối đa 8 dòng cuối
                blocked_attempts = [line.strip() for line in lines[-8:] if line.strip()]
        except Exception as log_err:
            sec_logger.warning(f"Failed to read security alerts log: {log_err}")
    
    try:
        server_port = int(os.getenv("JARVIS_SERVER_PORT", "8340"))
        if not 1 <= server_port <= 65535:
            raise ValueError
    except ValueError:
        server_port = 8340

    # 2. Lấy danh sách kết nối active
    active_connections = []
    connection_error = ""
    try:
        active_connections = get_active_network_connections(port=server_port)
    except Exception as exc:
        connection_error = str(exc)
        sec_logger.warning(f"Failed to inspect active network connections: {exc}")

    # 3. Tạo báo cáo Markdown
    report = "🛡️ **[BÁO CÁO GIÁM SÁT AN NINH JARVIS]**\n\n"
    
    # Cấu hình tường lửa
    report += "⚙️ **Cấu hình Firewall:**\n"
    if local_only:
        report += "- **Chế độ:** `LOCAL_ONLY` (Chỉ chấp nhận các kết nối từ máy cục bộ).\n"
    else:
        report += "- **Chế độ:** `lan_open` (Mở rộng cho phép truy cập từ mạng LAN).\n"
    
    if allowed_ips:
        report += f"- **Danh sách IP trắng:** `{allowed_ips}`\n"
    else:
        report += "- **Danh sách IP trắng:** *Không cấu hình (Chỉ localhost)*\n"

    report += "\n🧱 **Lớp bảo vệ ứng dụng:**\n"
    report += "- **IP/CIDR:** Có; áp dụng chung cho HTTP và WebSocket.\n"
    report += "- **Media local:** Chỉ phục vụ tệp nằm trong thư mục media được phép.\n"
    report += f"- **Giới hạn WebUI upload:** {upload_limit:,} bytes; đọc theo chunk.\n"
    report += f"- **Giới hạn STT upload:** {stt_limit:,} bytes; đọc theo chunk.\n"
    report += f"- **CORS origins:** `{', '.join(cors_origins)}`\n"
    report += "- **Xác thực phiên/API:** Chưa triển khai (giai đoạn 2).\n"
    report += "- **Rate limiting:** Chưa triển khai (giai đoạn 2).\n"
    report += "- **Guardrail dữ liệu LLM/MCP/RAG:** Chưa mở rộng trong giai đoạn 1.\n"
        
    # Trạng thái kết nối active
    report += f"\n🔌 **Kết nối TCP hoạt động (Cổng {server_port}):**\n"
    if connection_error:
        report += f"- *Không thể đọc trạng thái socket: {connection_error}*\n"
    elif active_connections:
        for ip in active_connections:
            report += f"- IP: `{ip}`\n"
    else:
        report += "- *Không có kết nối bên ngoài hoạt động.*\n"
        
    # Log xâm nhập gần đây
    report += "\n🚨 **Nhật ký cảnh báo xâm nhập gần nhất:**\n"
    if blocked_attempts:
        for attempt in blocked_attempts:
            report += f"- {attempt}\n"
    else:
        report += "- *Không phát hiện nỗ lực xâm nhập mạng trái phép nào trong thời gian gần đây.*\n"
        
    return report

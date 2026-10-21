"""Small, dependency-free security policies shared by HTTP and WebSocket paths."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address, ip_network
from pathlib import Path
from urllib.parse import urlsplit


IPAddress = IPv4Address | IPv6Address
IPNetwork = IPv4Network | IPv6Network
DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://localhost:8340",
    "https://127.0.0.1:8340",
)


def _parse_ip(value: str | None) -> IPAddress | None:
    if not value:
        return None
    raw = value.strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    if "%" in raw:
        raw = raw.split("%", 1)[0]
    try:
        address = ip_address(raw)
    except ValueError:
        return None
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


@dataclass(frozen=True)
class NetworkPolicy:
    """Fail-closed address policy with explicit exact/CIDR exceptions."""

    local_only: bool = True
    lan_open: bool = False
    allowed_ips: Iterable[str] = ()
    _allowed_networks: tuple[IPNetwork, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        networks: list[IPNetwork] = []
        for raw in self.allowed_ips:
            value = str(raw).strip()
            if not value:
                continue
            try:
                networks.append(ip_network(value, strict=False))
            except ValueError:
                continue
        object.__setattr__(self, "_allowed_networks", tuple(networks))

    def is_allowed(self, host: str | None) -> bool:
        address = _parse_ip(host)
        if address is None:
            return False
        if address.is_loopback:
            return True
        if any(address.version == network.version and address in network for network in self._allowed_networks):
            return True
        if self.local_only:
            return False
        if self.lan_open:
            return address.is_private
        return False


def parse_cors_origins(raw_origins: str) -> tuple[str, ...]:
    """Return validated HTTP(S) origins and never enable a wildcard origin."""

    if not raw_origins.strip():
        return DEFAULT_CORS_ORIGINS

    origins: list[str] = []
    for raw in raw_origins.split(","):
        origin = raw.strip().rstrip("/")
        if not origin or origin == "*":
            continue
        try:
            parsed = urlsplit(origin)
            _ = parsed.port
        except ValueError:
            continue
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            continue
        if origin not in origins:
            origins.append(origin)
    return tuple(origins) or DEFAULT_CORS_ORIGINS


def is_origin_allowed(origin: str | None, host: str | None, allowed_origins: Iterable[str]) -> bool:
    """Chặn trang web lạ trong trình duyệt gọi vào JARVIS (CSRF / Cross-Site WebSocket Hijacking).

    Firewall IP không đủ: một trang web độc hại mở trên chính máy này kết nối tới
    ws://127.0.0.1:8340 vẫn mang IP loopback. Trình duyệt luôn gửi header Origin cho
    WebSocket và cho POST/PUT/DELETE khác origin, nên kiểm tra nó là đủ. Client không
    phải trình duyệt (Telegram bot, httpx, curl) không gửi Origin và vẫn được cho qua.
    """

    if not origin:
        return True
    origin = origin.strip().rstrip("/")
    if origin.lower() == "null":
        return False
    if origin in set(allowed_origins):
        return True
    try:
        netloc = urlsplit(origin).netloc.lower()
    except ValueError:
        return False
    # Cùng origin: trang được phục vụ từ chính server này (vd. điện thoại trong LAN mở https://<ip>:8340).
    return bool(netloc) and netloc == (host or "").strip().lower()


def resolve_file_under(root: Path, raw_path: str) -> Path:
    """Resolve an existing regular file while preventing escape from ``root``."""

    requested = Path(raw_path)
    if requested.is_absolute():
        raise ValueError("Absolute paths are not allowed")

    root_resolved = root.resolve()
    candidate = (root_resolved / requested).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("Path escapes the allowed directory") from exc
    if not candidate.is_file():
        raise FileNotFoundError(raw_path)
    return candidate


class UploadTooLarge(ValueError):
    def __init__(self, max_bytes: int):
        super().__init__(f"Upload exceeds the {max_bytes}-byte limit")
        self.max_bytes = max_bytes


async def read_limited(
    read: Callable[[int], Awaitable[bytes]],
    *,
    max_bytes: int,
    chunk_size: int = 1024 * 1024,
) -> bytes:
    """Read an async upload incrementally and stop immediately after its limit."""

    if max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    content = bytearray()
    while True:
        remaining = max_bytes - len(content)
        chunk = await read(min(chunk_size, remaining + 1))
        if not chunk:
            return bytes(content)
        content.extend(chunk)
        if len(content) > max_bytes:
            raise UploadTooLarge(max_bytes)

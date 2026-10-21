import logging
import mimetypes
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from uuid import uuid4

log = logging.getLogger("jarvis.attachment_store")


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_UPLOAD_ROOT = PROJECT_ROOT / "data" / "uploads"


@dataclass(frozen=True)
class AttachmentContext:
    attachment_id: str
    resolved_path: Path
    filename: str
    extension: str
    mime_type: str
    size: int
    channel: str
    created_at: float

    def router_metadata(self) -> dict[str, str | int]:
        return {
            "filename": self.filename,
            "extension": self.extension,
            "mime_type": self.mime_type,
            "size": self.size,
            "channel": self.channel,
        }


class AttachmentStore:
    def __init__(
        self,
        upload_root: Path = DEFAULT_UPLOAD_ROOT,
        ttl_seconds: float = 300.0,
    ):
        self.upload_root = upload_root.resolve()
        self.ttl_seconds = ttl_seconds
        self._items: dict[str, AttachmentContext] = {}
        self._lock = Lock()

    def register(
        self,
        path: Path,
        *,
        filename: str,
        mime_type: str | None = None,
        channel: str,
    ) -> AttachmentContext:
        resolved_path = path.resolve(strict=True)
        if not resolved_path.is_relative_to(self.upload_root):
            raise ValueError("Attachment is outside the configured upload root")

        attachment_id = uuid4().hex
        context = AttachmentContext(
            attachment_id=attachment_id,
            resolved_path=resolved_path,
            filename=Path(filename).name,
            extension=resolved_path.suffix.lower(),
            mime_type=mime_type
            or mimetypes.guess_type(filename)[0]
            or "application/octet-stream",
            size=resolved_path.stat().st_size,
            channel=channel,
            created_at=time.monotonic(),
        )
        with self._lock:
            expired = self._purge_expired_locked()
            self._items[attachment_id] = context
        self._delete_files(expired)
        return context

    def resolve(self, attachment_id: str | None) -> AttachmentContext | None:
        if not attachment_id:
            return None
        with self._lock:
            expired = self._purge_expired_locked()
            result = self._items.get(attachment_id)
        self._delete_files(expired)
        return result

    def discard(self, attachment_id: str | None) -> None:
        if not attachment_id:
            return
        with self._lock:
            context = self._items.pop(attachment_id, None)
        if context is not None:
            self._delete_file(context.resolved_path)

    def _purge_expired_locked(self) -> list[AttachmentContext]:
        # Chỉ hết hạn METADATA trong RAM trước đây — file .pdf thật trên đĩa
        # ở data/uploads/ không bao giờ bị xoá, tăng trưởng vô hạn theo mỗi
        # lượt upload. Xoá file thật cùng lúc với việc hết hạn tham chiếu.
        #
        # Chỉ định phải gọi hàm này trong khi đang giữ self._lock — nhưng
        # bản thân việc xoá file (I/O chặn) được thực hiện ở NGOÀI lock bởi
        # caller, để không giữ lock trong lúc unlink().
        cutoff = time.monotonic() - self.ttl_seconds
        expired = [
            (attachment_id, context)
            for attachment_id, context in self._items.items()
            if context.created_at < cutoff
        ]
        for attachment_id, _ in expired:
            self._items.pop(attachment_id, None)
        return [context for _, context in expired]

    def _delete_files(self, contexts: list[AttachmentContext]) -> None:
        for context in contexts:
            self._delete_file(context.resolved_path)

    def _delete_file(self, path: Path) -> None:
        try:
            if path.is_relative_to(self.upload_root):
                path.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("Failed to delete expired attachment file %s: %s", path, exc)


_attachment_store = AttachmentStore()


def register_attachment(
    path: Path,
    *,
    filename: str,
    mime_type: str | None = None,
    channel: str,
) -> AttachmentContext:
    return _attachment_store.register(
        path,
        filename=filename,
        mime_type=mime_type,
        channel=channel,
    )


def resolve_attachment(attachment_id: str | None) -> AttachmentContext | None:
    return _attachment_store.resolve(attachment_id)


def discard_attachment(attachment_id: str | None) -> None:
    _attachment_store.discard(attachment_id)

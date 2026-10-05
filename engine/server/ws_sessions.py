"""Danh sách WebSocket giọng nói đang mở. `latest` là tab kết nối gần nhất còn sống."""


class ActiveSessions:
    def __init__(self) -> None:
        self._items: list = []

    def add(self, ws) -> None:
        self._items.append(ws)

    def remove(self, ws) -> None:
        if ws in self._items:
            self._items.remove(ws)

    @property
    def latest(self):
        return self._items[-1] if self._items else None

    def __len__(self) -> int:
        return len(self._items)

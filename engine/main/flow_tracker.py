"""
FlowTracker — Báo từng bước hoạt động của hệ thống theo thời gian thực.
Mỗi bước gửi độc lập, frontend tự tích lũy và hiển thị.
"""
class StepContext:
    def __init__(self, tracker, label: str):
        self.tracker = tracker
        self.label = label
        self._initial_label = label
        self._step_id = None

    async def __aenter__(self):
        self._step_id = await self.tracker._create_step(self._initial_label, "active")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            await self.tracker.track(self._initial_label, "failed", step_id=self._step_id)
        else:
            if self.label != self._initial_label:
                await self.tracker.update_label(self._initial_label, self.label, step_id=self._step_id)
            await self.tracker.track(self.label, "completed", step_id=self._step_id)


class FlowTracker:
    def __init__(self, ws, safe_send):
        self._ws = ws
        self._send = safe_send
        self._seq = 0
        self._steps: list[dict] = []

    def reset(self):
        self._seq = 0
        self._steps.clear()

    def step(self, label: str):
        """Trả về StepContext để dùng với cú pháp 'async with flow_tracker.step(label)'."""
        return StepContext(self, label)

    async def update_label(self, old_label: str, new_label: str, step_id: int = None):
        """Cập nhật nhãn của một bước đang active."""
        if step_id is not None:
            for s in self._steps:
                if s["id"] == step_id:
                    s["label"] = new_label
                    return
        for s in self._steps:
            if s["label"] == old_label and s["status"] in ("active", "pending"):
                s["label"] = new_label
                break

    async def _send_step(self, step: dict):
        """Gửi một trạng thái bước và ghi nhận kết quả gửi WebSocket."""
        await self._send(self._ws, {"type": "flow_step", "step": step})

    async def _create_step(self, label: str, status: str) -> int:
        """Luôn tạo một bước mới độc lập (dùng cho __aenter__ để tránh đụng độ giữa các bước cùng nhãn chạy song song)."""
        self._seq += 1
        step = {"id": self._seq, "label": label, "status": status}
        self._steps.append(step)
        await self._send_step(step)
        return step["id"]

    async def track(self, label: str, status: str = "completed", step_id: int = None):
        if step_id is not None:
            for s in self._steps:
                if s["id"] == step_id:
                    s["label"] = label
                    s["status"] = status
                    await self._send_step(s)
                    if label == "Hoàn thành" and status == "completed":
                        await self._complete_all_active()
                    return
        for s in self._steps:
            if s["label"] == label and s["status"] in ("active", "pending"):
                s["status"] = status
                await self._send_step(s)
                if label == "Hoàn thành" and status == "completed":
                    await self._complete_all_active()
                return
        self._seq += 1
        step = {"id": self._seq, "label": label, "status": status}
        self._steps.append(step)
        await self._send_step(step)
        if label == "Hoàn thành" and status == "completed":
            await self._complete_all_active()

    async def fail_all_active(self):
        """Đánh dấu failed cho tất cả các bước đang active hoặc pending để tránh treo UI."""
        for s in self._steps:
            if s["status"] in ("active", "pending"):
                s["status"] = "failed"
                await self._send_step(s)

    async def _complete_all_active(self):
        """Tự động chuyển các bước đang active hoặc pending thành completed khi toàn bộ luồng kết thúc."""
        for s in self._steps:
            if s["status"] in ("active", "pending"):
                s["status"] = "completed"
                await self._send_step(s)

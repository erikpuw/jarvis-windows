"""8 khung giờ của ngài (greeting cũ, trước c31f113): một bảng duy nhất cho lớp chào và <thoi_gian> của chat."""
from datetime import datetime

# (giờ kết thúc, tên khung cho chat, câu chào lớp chào)
_SLOTS = (
    (5, "đêm khuya", "Đêm khuya rồi"),
    (7, "sáng sớm", "Chào buổi sáng sớm"),
    (11, "buổi sáng", "Chào buổi sáng"),
    (13, "buổi trưa", "Chào buổi trưa"),
    (17, "buổi chiều", "Chào buổi chiều"),
    (19, "xế chiều", "Chào buổi xế chiều"),
    (22, "buổi tối", "Chào buổi tối"),
    (24, "khuya", "Khuya rồi"),
)


def time_slot(hour: int) -> tuple[str, str]:
    """Giờ 0-23 → (tên khung, câu chào)."""
    return next((part, greeting) for end, part, greeting in _SLOTS if hour < end)


def local_now() -> datetime:
    return datetime.now().astimezone()

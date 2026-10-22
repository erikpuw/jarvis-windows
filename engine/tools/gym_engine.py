"""Local workout and profile storage for the gym agent."""

import json
import logging
import re
import shutil
import sqlite3
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

GYM_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "gym"
WIKI_GYM_DIR = Path(__file__).resolve().parents[2] / "data" / "wiki" / "Gym"
log = logging.getLogger("jarvis.gym")
_PROFILE_ID = re.compile(r"^[0-9a-f]{32}$")
_NUTRITION_GOALS = {"eat_food", "maintain", "fat_loss", "gain_muscle"}


def _resolve_user_id(user_id: str | None = None) -> str:
    if user_id:
        return user_id
    try:
        from engine.core.session_context import get_current_user_id
        return get_current_user_id() or "admin"
    except Exception:
        return "admin"


def _gym_data_dir(user_id: str | None = None) -> Path:
    uid = _resolve_user_id(user_id)
    if uid != "admin":
        return Path(__file__).resolve().parents[2] / "data" / "users" / uid / "gym"
    return GYM_DATA_DIR


def _wiki_gym_dir(user_id: str | None = None) -> Path:
    uid = _resolve_user_id(user_id)
    if uid != "admin":
        return Path(__file__).resolve().parents[2] / "data" / "users" / uid / "wiki" / "Gym"
    return WIKI_GYM_DIR


def get_local_now() -> datetime:
    """Thời gian hiện tại theo múi giờ địa phương kèm offset (tránh lệch giờ UTC)."""
    return datetime.now().astimezone()


def get_local_today_str() -> str:
    """Ngày hiện tại theo múi giờ địa phương (YYYY-MM-DD)."""
    return get_local_now().date().isoformat()


def parse_natural_date(text: str) -> str:
    """Trích xuất ngày từ câu nói tự nhiên ('hôm nay', 'hôm qua', 'hôm kia', ngày DD/MM/YYYY)."""
    t_lower = text.lower()
    today = get_local_now().date()
    if "hôm kia" in t_lower:
        return (today - timedelta(days=2)).isoformat()
    if "hôm qua" in t_lower:
        return (today - timedelta(days=1)).isoformat()
    if "hôm nay" in t_lower:
        return today.isoformat()

    iso_m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if iso_m:
        return iso_m.group(1)

    dmy_m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", text)
    if dmy_m:
        d, m, y = int(dmy_m.group(1)), int(dmy_m.group(2)), int(dmy_m.group(3))
        try:
            return date(y, m, d).isoformat()
        except ValueError:
            pass

    dm_m = re.search(r"(?:ngày\s+)?\b(\d{1,2})[/-](\d{1,2})\b", text)
    if dm_m:
        d, m = int(dm_m.group(1)), int(dm_m.group(2))
        try:
            return date(today.year, m, d).isoformat()
        except ValueError:
            pass

    return today.isoformat()
_NUTRITION_ADVICE = {
    "eat_food": "Ăn đa dạng rau quả, đậu, ngũ cốc nguyên hạt và nguồn đạm phù hợp; ưu tiên món ít chế biến, giảm dần đồ uống nhiều đường và món quá mặn.",
    "maintain": "Giữ nhịp ăn uống có thể duy trì, chọn khẩu phần vừa đủ và tiếp tục tập luyện đều. Theo dõi xu hướng cân nặng theo tuần nếu việc cân đo phù hợp với bạn.",
    "fat_loss": "Nếu mục tiêu là giảm mỡ, bắt đầu bằng một thay đổi nhỏ có thể giữ lâu dài: thêm rau/đậu và nguồn đạm vào bữa, giảm đồ uống có đường hoặc bớt một phần ăn dư. Tránh nhịn ăn cực đoan.",
    "gain_muscle": "Nếu mục tiêu là tăng cơ, duy trì tập kháng lực có tiến triển và các bữa ăn đều với nguồn đạm, tinh bột và rau quả. Không cần mặc định phải dùng thực phẩm bổ sung.",
}
EXERCISES = [
    {
        "name": "Barbell bench press",
        "vietnamese_name": "Đẩy tạ đòn ngực nằm (Bench Press)",
        "muscles": ["chest", "triceps", "shoulders"],
        "aliases": ["ngực", "nguc", "đẩy ngực", "ngực đòn", "bench press"],
        "video_url": "https://www.youtube.com/watch?v=phB6ITV66mM",
        "video_title": "Pietro Boselli — Chest Workout"
    },
    {
        "name": "Dumbbell bench press",
        "vietnamese_name": "Đẩy tạ đơn ngực nằm (Dumbbell Bench Press)",
        "muscles": ["chest", "triceps", "shoulders"],
        "aliases": ["ngực", "nguc", "tạ đơn ngực", "đẩy ngực", "dumbbell press"],
        "video_url": "https://www.youtube.com/watch?v=phB6ITV66mM",
        "video_title": "Pietro Boselli — Chest Workout"
    },
    {
        "name": "Push up",
        "vietnamese_name": "Hít đất / Chống đẩy (Push Up)",
        "muscles": ["chest", "triceps", "shoulders", "core"],
        "aliases": ["hít đất", "hit dat", "chống đẩy", "chong day", "ngực", "nguc", "push up"],
        "video_url": "https://www.youtube.com/watch?v=phB6ITV66mM",
        "video_title": "Pietro Boselli — Push Up Tutorial"
    },
    {
        "name": "Dips",
        "vietnamese_name": "Chống xà kép (Dips)",
        "muscles": ["chest", "triceps", "shoulders"],
        "aliases": ["xà kép", "xa kep", "ngực dưới", "nguc duoi", "tay sau", "dips"],
        "video_url": "https://www.youtube.com/watch?v=phB6ITV66mM",
        "video_title": "Pietro Boselli — Dips Tutorial"
    },
    {
        "name": "Barbell squat",
        "vietnamese_name": "Gánh tạ đùi sau / mông (Barbell Squat)",
        "muscles": ["quadriceps", "glutes", "legs"],
        "aliases": ["chân", "chan", "đùi", "dui", "mông", "mong", "squat", "gánh tạ"],
        "video_url": "https://www.youtube.com/watch?v=Dh306V9f6hA",
        "video_title": "Pietro Boselli — Legs Workout"
    },
    {
        "name": "Leg press",
        "vietnamese_name": "Đạp đùi trên máy (Leg Press)",
        "muscles": ["quadriceps", "glutes", "legs"],
        "aliases": ["đạp đùi", "dap dui", "chân", "chan", "leg press"],
        "video_url": "https://www.youtube.com/watch?v=Dh306V9f6hA",
        "video_title": "Pietro Boselli — Legs Workout"
    },
    {
        "name": "Deadlift",
        "vietnamese_name": "Kéo tạ đòn đùi sau & lưng (Deadlift)",
        "muscles": ["hamstrings", "glutes", "back"],
        "aliases": ["lưng", "lung", "đùi sau", "mông", "deadlift"],
        "video_url": "https://www.youtube.com/watch?v=vRhmL5HbGo0",
        "video_title": "Pietro Boselli — Back Workout"
    },
    {
        "name": "Overhead press",
        "vietnamese_name": "Đẩy tạ qua đầu (Overhead Press)",
        "muscles": ["shoulders", "triceps"],
        "aliases": ["vai", "vai trước", "vai trên", "overhead press", "đẩy vai"],
        "video_url": "https://www.youtube.com/watch?v=BMBJR9j6-3w",
        "video_title": "Pietro Boselli — Shoulders Workout"
    },
    {
        "name": "Lateral raise",
        "vietnamese_name": "Dang tạ đơn sang bên (Lateral Raise)",
        "muscles": ["shoulders"],
        "aliases": ["dang vai", "vai giữa", "vai ngang", "lateral raise", "vai"],
        "video_url": "https://www.youtube.com/watch?v=BMBJR9j6-3w",
        "video_title": "Pietro Boselli — Shoulders Workout"
    },
    {
        "name": "Barbell row",
        "vietnamese_name": "Kéo tạ đòn gập người (Barbell Row)",
        "muscles": ["back", "biceps"],
        "aliases": ["lưng", "lung", "xô", "xo", "chèo tạ", "row"],
        "video_url": "https://www.youtube.com/watch?v=vRhmL5HbGo0",
        "video_title": "Pietro Boselli — Back Workout"
    },
    {
        "name": "Lat pulldown",
        "vietnamese_name": "Kéo cáp xô lưng (Lat Pulldown)",
        "muscles": ["back", "biceps"],
        "aliases": ["kéo xô", "keo xo", "lưng", "lung", "xô", "xo", "lat pulldown"],
        "video_url": "https://www.youtube.com/watch?v=vRhmL5HbGo0",
        "video_title": "Pietro Boselli — Back Workout"
    },
    {
        "name": "Pull up",
        "vietnamese_name": "Hít xà đơn (Pull Up)",
        "muscles": ["back", "biceps", "shoulders"],
        "aliases": ["hít xà", "hit xa", "xà đơn", "xa don", "lưng", "xô", "pull up"],
        "video_url": "https://www.youtube.com/watch?v=vRhmL5HbGo0",
        "video_title": "Pietro Boselli — Back & Pull Ups"
    },
    {
        "name": "Biceps curl",
        "vietnamese_name": "Cuốn tạ tay trước (Biceps Curl)",
        "muscles": ["biceps", "arms"],
        "aliases": ["tay trước", "tay truoc", "bắp tay", "bap tay", "cuốn tạ", "tay", "curl"],
        "video_url": "https://www.youtube.com/watch?v=lIXRWGzZ8-E",
        "video_title": "Pietro Boselli — Arms Workout"
    },
    {
        "name": "Triceps pushdown",
        "vietnamese_name": "Kéo cáp tay sau (Triceps Pushdown)",
        "muscles": ["triceps", "arms"],
        "aliases": ["tay sau", "tay sau", "bắp tay sau", "triceps", "tay"],
        "video_url": "https://www.youtube.com/watch?v=lIXRWGzZ8-E",
        "video_title": "Pietro Boselli — Arms Workout"
    },
    {
        "name": "Plank & Crunch",
        "vietnamese_name": "Gập bụng và Plank cơ bụng (Plank / Crunch)",
        "muscles": ["abs", "core"],
        "aliases": ["bụng", "bung", "cơ bụng", "gập bụng", "plank", "crunch", "abs"],
        "video_url": "https://www.youtube.com/watch?v=Dh306V9f6hA",
        "video_title": "Pietro Boselli — Core & Abs Workout"
    },
]

GYM_COMMAND_GUIDE = [
    {"icon": "🏋️", "category": "Ghi buổi tập", "example": "@gym vừa tập Bench Press 3 hiệp 10 reps 60kg", "desc": "Ghi nhận bài tập, số hiệp, reps và khối lượng."},
    {"icon": "⚖️", "category": "Ghi cân nặng", "example": "@gym hôm nay cân nặng 72kg", "desc": "Theo dõi tiến độ cân nặng theo ngày."},
    {"icon": "🔍", "category": "Tra cứu bài tập", "example": "@gym tìm bài tập ngực", "desc": "Xem kỹ thuật và video hướng dẫn YouTube."},
    {"icon": "📊", "category": "Thống kê & Tiến độ", "example": "@gym thống kê tiến độ", "desc": "Xem tổng volume, ước tính 1RM, lịch sử các buổi tập."},
    {"icon": "🥗", "category": "Tư vấn dinh dưỡng", "example": "@gym tư vấn dinh dưỡng tăng cơ", "desc": "Nguyên tắc ăn uống lành mạnh theo khuyến nghị WHO."},
    {"icon": "🎯", "category": "Theo dõi thói quen", "example": "@gym hôm nay đã uống đủ 2 lít nước", "desc": "Ghi nhận thói quen tốt và chuỗi ngày duy trì."},
    {"icon": "👤", "category": "Quản lý hồ sơ", "example": "@gym tạo hồ sơ [Tên] / @gym chọn hồ sơ [Tên]", "desc": "Tạo mới hoặc chuyển đổi hồ sơ người dùng."},
]

def _profile_dir(profile_id: str, user_id: str | None = None) -> Path:
    if not isinstance(profile_id, str) or not _PROFILE_ID.fullmatch(profile_id):
        raise ValueError("profile_id không hợp lệ; hãy chọn hồ sơ từ danh sách.")
    path = _gym_data_dir(user_id) / profile_id
    if not path.is_dir():
        raise ValueError("Không tìm thấy hồ sơ tập luyện này.")
    return path


def _connect(profile_id: str, user_id: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(_profile_dir(profile_id, user_id=user_id) / "gym.db")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS workouts (
            id INTEGER PRIMARY KEY, trained_on TEXT NOT NULL, exercise TEXT NOT NULL,
            sets_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bodyweight (
            id INTEGER PRIMARY KEY, measured_on TEXT NOT NULL, weight_kg REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY, day TEXT NOT NULL, habit TEXT NOT NULL,
            done INTEGER NOT NULL, note TEXT NOT NULL DEFAULT '', UNIQUE(day, habit)
        );
    """)
    return conn


def list_profiles(user_id: str | None = None) -> list[dict]:
    gym_dir = _gym_data_dir(user_id)
    if not gym_dir.is_dir():
        return []
    profiles = []
    for directory in gym_dir.iterdir():
        if not directory.is_dir() or not _PROFILE_ID.fullmatch(directory.name):
            continue
        try:
            profiles.append(json.loads((directory / "profile.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return sorted(profiles, key=lambda p: p.get("created_at", ""))


def get_active_profile(user_id: str | None = None) -> dict | None:
    """Return the persistent local selection, or auto-select the only profile."""
    profiles = list_profiles(user_id=user_id)
    pointer = _gym_data_dir(user_id) / "active_profile.json"
    profile_id = ""
    try:
        profile_id = json.loads(pointer.read_text(encoding="utf-8")).get("profile_id", "")
    except (OSError, ValueError, AttributeError):
        pass
    if profile_id:
        current = next((p for p in profiles if p["profile_id"] == profile_id), None)
        if current:
            return current
    if len(profiles) == 1:
        return select_profile(profiles[0]["profile_id"], user_id=user_id)
    return None


def select_profile(profile_id: str, user_id: str | None = None) -> dict:
    profile_dir = _profile_dir(profile_id, user_id=user_id)
    profile = json.loads((profile_dir / "profile.json").read_text(encoding="utf-8"))
    (_gym_data_dir(user_id) / "active_profile.json").write_text(
        json.dumps({"profile_id": profile_id}, ensure_ascii=False), encoding="utf-8"
    )
    return profile


def create_profile(name: str, user_id: str | None = None) -> dict:
    name = " ".join(str(name or "").split())
    if not name or len(name) > 80:
        raise ValueError("Tên hồ sơ phải có từ 1 đến 80 ký tự.")
    gym_dir = _gym_data_dir(user_id)
    gym_dir.mkdir(parents=True, exist_ok=True)
    profile_id = uuid.uuid4().hex
    directory = gym_dir / profile_id
    directory.mkdir(parents=True, exist_ok=True)
    created_now = get_local_now().isoformat()
    uid = _resolve_user_id(user_id)
    profile = {"profile_id": profile_id, "name": name, "user_id": uid, "created_at": created_now}
    (directory / "profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    with _connect(profile_id, user_id=user_id):
        pass
    if len(list_profiles(user_id=user_id)) == 1:
        select_profile(profile_id, user_id=user_id)
    sync_profile_to_wiki(profile_id, user_id=user_id)
    return profile


_GYM_STOP_WORDS = {
    "tìm", "tim", "bài", "bai", "tập", "tap", "hướng", "huong", "dẫn", "dan",
    "video", "các", "cac", "những", "nhung", "cho", "tôi", "toi", "xem", "kiểm", "tra"
}

_MUSCLE_SYNONYMS = {
    "ngực": ["chest", "ngực", "nguc"],
    "nguc": ["chest", "ngực", "nguc"],
    "lưng": ["back", "lưng", "lung", "xô", "xo"],
    "lung": ["back", "lưng", "lung", "xô", "xo"],
    "xô": ["back", "xô", "xo"],
    "xo": ["back", "xô", "xo"],
    "vai": ["shoulders", "vai"],
    "tay": ["arms", "biceps", "triceps", "tay"],
    "tay trước": ["biceps", "tay trước", "tay truoc", "arms"],
    "tay truoc": ["biceps", "tay trước", "tay truoc", "arms"],
    "tay sau": ["triceps", "tay sau", "arms"],
    "chân": ["legs", "quadriceps", "glutes", "chân", "chan", "đùi", "dui"],
    "chan": ["legs", "quadriceps", "glutes", "chân", "chan", "đùi", "dui"],
    "đùi": ["quadriceps", "legs", "đùi", "dui"],
    "dui": ["quadriceps", "legs", "đùi", "dui"],
    "mông": ["glutes", "mông", "mong"],
    "mong": ["glutes", "mông", "mong"],
    "bụng": ["abs", "core", "bụng", "bung"],
    "bung": ["abs", "core", "bụng", "bung"],
}


def search_exercises(query: str = "") -> list[dict]:
    raw = str(query or "").casefold().strip()
    if not raw:
        return EXERCISES

    tokens = [w for w in raw.split() if w]
    filtered_tokens = [w for w in tokens if w not in _GYM_STOP_WORDS]
    search_tokens = filtered_tokens if filtered_tokens else tokens

    expanded_terms = set(search_tokens)
    for token in search_tokens:
        if token in _MUSCLE_SYNONYMS:
            expanded_terms.update(_MUSCLE_SYNONYMS[token])

    cleaned_phrase = " ".join(search_tokens)

    results = []
    for item in EXERCISES:
        corpus = (
            item["name"] + " " +
            item.get("vietnamese_name", "") + " " +
            " ".join(item.get("muscles", [])) + " " +
            " ".join(item.get("aliases", []))
        ).casefold()

        if cleaned_phrase and cleaned_phrase in corpus:
            results.append(item)
            continue

        if any(term in corpus for term in expanded_terms):
            results.append(item)

    if results:
        return results

    # Fallback: kiểm tra bất kỳ token nào trong name/aliases
    fallback = [item for item in EXERCISES if any(t in item["name"].casefold() or any(t in a for a in item.get("aliases", [])) for t in tokens)]
    return fallback if fallback else EXERCISES


def log_workout(profile_id: str, trained_on: str, exercises: list[dict], user_id: str | None = None) -> dict:
    trained_on = date.fromisoformat(trained_on).isoformat()
    if not exercises:
        raise ValueError("Buổi tập cần ít nhất một bài tập.")
    saved = []
    created_now = get_local_now().isoformat()
    with _connect(profile_id, user_id=user_id) as conn:
        for item in exercises:
            name, sets = " ".join(str(item.get("name", "")).split()), item.get("sets")
            if not name or not isinstance(sets, list) or not sets:
                raise ValueError("Mỗi bài tập cần tên và ít nhất một set.")
            normalized = []
            for entry in sets:
                reps, weight = int(entry["reps"]), float(entry.get("weight_kg", 0))
                if reps < 1 or weight < 0:
                    raise ValueError("Reps phải lớn hơn 0 và khối lượng không được âm.")
                normalized.append({"reps": reps, "weight_kg": weight})
            cursor = conn.execute("INSERT INTO workouts(trained_on, exercise, sets_json, created_at) VALUES (?, ?, ?, ?)",
                                  (trained_on, name, json.dumps(normalized), created_now))
            saved.append({"id": cursor.lastrowid, "name": name, "sets": normalized})
    volume = sum(item["reps"] * item["weight_kg"] for exercise in saved for item in exercise["sets"])
    sync_profile_to_wiki(profile_id, user_id=user_id)
    return {"profile_id": profile_id, "trained_on": trained_on, "exercises": saved, "volume_kg": round(volume, 1)}


def record_bodyweight(profile_id: str, measured_on: str, weight_kg: float, user_id: str | None = None) -> dict:
    measured_on, weight_kg = date.fromisoformat(measured_on).isoformat(), float(weight_kg)
    if not 20 <= weight_kg <= 500:
        raise ValueError("Cân nặng phải trong khoảng 20–500 kg.")
    with _connect(profile_id, user_id=user_id) as conn:
        conn.execute("INSERT INTO bodyweight(measured_on, weight_kg) VALUES (?, ?)", (measured_on, weight_kg))
    sync_profile_to_wiki(profile_id, user_id=user_id)
    return {"profile_id": profile_id, "measured_on": measured_on, "weight_kg": weight_kg}


def nutrition_guide(goal: str = "eat_food") -> dict:
    goal = str(goal or "eat_food").strip().lower()
    if goal not in _NUTRITION_GOALS:
        raise ValueError("Mục tiêu ăn uống phải là eat_food, maintain, fat_loss hoặc gain_muscle.")
    return {
        "goal": goal,
        "advice": _NUTRITION_ADVICE[goal],
        "basics": [
            "Ưu tiên sự đa dạng, cân bằng và món ít chế biến; điều chỉnh theo văn hóa ăn uống và điều kiện thực tế.",
            "WHO gợi ý người trên 10 tuổi hướng tới ít nhất 400 g rau quả mỗi ngày; tăng dần nếu hiện tại còn ít.",
            "Đặt mục tiêu nhỏ cho tuần này, chuẩn bị sẵn một lựa chọn tiện lợi và quay lại nhịp thường ngày sau một bữa lệch kế hoạch.",
        ],
        "sources": [
            "https://www.who.int/en/news-room/fact-sheets/detail/healthy-diet",
            "https://www.who.int/publications/i/item/9789240015128",
        ],
        "note": "Thông tin giáo dục chung, không phải thực đơn điều trị hay chỉ định calo. Nếu có bệnh nền, đang mang thai, dưới 18 tuổi hoặc có tiền sử rối loạn ăn uống, hãy hỏi chuyên gia y tế/dinh dưỡng.",
    }


def log_habit(profile_id: str, day: str, habit: str, done: bool, note: str = "", user_id: str | None = None) -> dict:
    day = date.fromisoformat(day).isoformat()
    habit = " ".join(str(habit or "").split())
    note = str(note or "").strip()
    if not habit or len(habit) > 80:
        raise ValueError("Tên thói quen phải có từ 1 đến 80 ký tự.")
    if not isinstance(done, bool):
        raise ValueError("done phải là true hoặc false.")
    if len(note) > 500:
        raise ValueError("Ghi chú không được dài quá 500 ký tự.")
    with _connect(profile_id, user_id=user_id) as conn:
        conn.execute("""INSERT INTO habits(day, habit, done, note) VALUES (?, ?, ?, ?)
            ON CONFLICT(day, habit) DO UPDATE SET done=excluded.done, note=excluded.note""",
            (day, habit, int(done), note))
    sync_profile_to_wiki(profile_id, user_id=user_id)
    return {"profile_id": profile_id, "day": day, "habit": habit, "done": done, "note": note}


def get_habit_summary(profile_id: str, days: int = 7, user_id: str | None = None) -> dict:
    days = max(1, min(int(days), 90))
    since = (date.today() - timedelta(days=days - 1)).isoformat()
    with _connect(profile_id, user_id=user_id) as conn:
        rows = conn.execute("SELECT day, habit, done FROM habits WHERE day >= ? ORDER BY day DESC", (since,)).fetchall()
    grouped = {}
    for row in rows:
        grouped.setdefault(row["habit"], set())
        if row["done"]:
            grouped[row["habit"]].add(date.fromisoformat(row["day"]))
    summaries = []
    for habit, completed in sorted(grouped.items()):
        anchor = date.today() if date.today() in completed else date.today() - timedelta(days=1)
        streak = 0
        while anchor in completed:
            streak += 1
            anchor -= timedelta(days=1)
        tracked = sum(row["habit"] == habit for row in rows)
        summaries.append({"habit": habit, "completed_days": len(completed), "tracked_days": tracked,
                          "completion_percent": round(100 * len(completed) / tracked), "current_streak_days": streak})
    return {"profile_id": profile_id, "period_days": days, "habits": summaries}


def get_history(profile_id: str, limit: int = 20, user_id: str | None = None) -> list[dict]:
    with _connect(profile_id, user_id=user_id) as conn:
        rows = conn.execute("SELECT * FROM workouts ORDER BY trained_on DESC, id DESC LIMIT ?", (max(1, min(int(limit), 100)),)).fetchall()
    return [{"id": r["id"], "trained_on": r["trained_on"], "exercise": r["exercise"], "sets": json.loads(r["sets_json"])} for r in rows]


def get_training_stats(profile_id: str, days: int = 30, user_id: str | None = None) -> dict:
    days = max(1, min(int(days), 3650))
    since = (date.today() - timedelta(days=days - 1)).isoformat()
    with _connect(profile_id, user_id=user_id) as conn:
        workouts = conn.execute("SELECT trained_on, exercise, sets_json FROM workouts WHERE trained_on >= ? ORDER BY trained_on", (since,)).fetchall()
        weights = conn.execute("SELECT measured_on, weight_kg FROM bodyweight ORDER BY measured_on, id").fetchall()
    volume = sum(s["reps"] * s["weight_kg"] for w in workouts for s in json.loads(w["sets_json"]))
    best = {}
    for workout in workouts:
        for entry in json.loads(workout["sets_json"]):
            estimate = entry["weight_kg"] * (1 + entry["reps"] / 30)
            best[workout["exercise"]] = max(best.get(workout["exercise"], 0), round(estimate, 1))
    session_count = len({w["trained_on"] for w in workouts})
    latest_weight = weights[-1]["weight_kg"] if weights else None
    return {"profile_id": profile_id, "days": days, "workout_count": session_count, "session_count": session_count,
            "logged_exercise_count": len(workouts), "volume_kg": round(volume, 1), "total_volume_kg": round(volume, 1), "estimated_1rm_kg": best,
            "bodyweight_latest_kg": latest_weight,
            "bodyweight": [{"measured_on": r["measured_on"], "weight_kg": r["weight_kg"]} for r in weights],
            "note": "1RM là ước tính Epley, không phải phép đo trực tiếp."}


def sync_profile_to_wiki(profile_id: str, user_id: str | None = None) -> Path | None:
    """Đồng bộ toàn bộ dữ liệu của một hồ sơ Gym ra tệp Markdown trong Obsidian Wiki (data/wiki/Gym/)
    để người dùng theo dõi trực quan trong Obsidian.
    Đánh dấu no_index: true để đảm bảo KHÔNG bị nạp ngược vào semantic AI memory."""
    try:
        profile_dir = _profile_dir(profile_id, user_id=user_id)
        profile = json.loads((profile_dir / "profile.json").read_text(encoding="utf-8"))
        name = profile.get("name", "Unknown")

        wiki_dir = _wiki_gym_dir(user_id=user_id)
        wiki_dir.mkdir(parents=True, exist_ok=True)
        wiki_file = wiki_dir / f"{name}.md"

        stats = get_training_stats(profile_id, days=90, user_id=user_id)
        history = get_history(profile_id, limit=30, user_id=user_id)
        habits_summary = get_habit_summary(profile_id, days=14, user_id=user_id)

        with _connect(profile_id, user_id=user_id) as conn:
            weights = conn.execute("SELECT measured_on, weight_kg FROM bodyweight ORDER BY measured_on DESC, id DESC LIMIT 20").fetchall()

        now_str = get_local_now().strftime("%Y-%m-%d %H:%M:%S")
        created_at_val = profile.get("created_at", "")
        if "T" in created_at_val:
            try:
                created_at_val = datetime.fromisoformat(created_at_val).strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass

        lines = [
            "---",
            "type: gym_log",
            f'profile_id: "{profile_id}"',
            f'profile_name: "{name}"',
            "no_index: true",
            "sync_source: gym_agent",
            f'updated_at: "{get_local_now().isoformat()}"',
            "---",
            "",
            f"# 🏋️ Nhật ký tập luyện: {name}",
            "",
            "> ℹ️ *Hồ sơ được tự động đồng bộ từ Agent Gym. Dữ liệu này dùng để theo dõi cá nhân trong Obsidian và được đánh dấu KHÔNG nạp lại vào semantic AI memory.*",
            "",
            "## 📌 Thông tin hồ sơ",
            f"- **Tên hồ sơ:** {name}",
            f"- **Mã hồ sơ (ID):** `{profile_id}`",
            f"- **Ngày khởi tạo:** {created_at_val}",
            f"- **Cập nhật gần nhất:** {now_str}",
            "",
            "## 📊 Chỉ số tổng quan (90 ngày)",
            f"- **Số buổi tập:** {stats.get('workout_count', 0)} buổi",
            f"- **Tổng volume:** {stats.get('volume_kg', 0):,} kg",
            f"- **Cân nặng gần nhất:** {stats.get('bodyweight_latest_kg') or 'Chưa ghi nhận'} kg",
            "",
        ]

        best_1rm = stats.get("estimated_1rm_kg", {})
        if best_1rm:
            lines.extend([
                "### 🏆 Ước tính 1RM (Epley)",
                "| Bài tập | Ước tính 1RM (kg) |",
                "|---|---|",
            ])
            for ex_name, rm_val in best_1rm.items():
                lines.append(f"| {ex_name} | {rm_val} kg |")
            lines.append("")

        lines.extend([
            "## 🏋️ Các buổi tập gần nhất",
            "| Ngày tập | Bài tập | Chi tiết Sets (Reps × Kg) | Volume (kg) |",
            "|---|---|---|---|",
        ])
        if history:
            for w in history:
                sets_desc = ", ".join(f"{s.get('reps')}x{s.get('weight_kg', 0)}kg" for s in w.get("sets", []))
                vol = sum(s.get("reps", 0) * s.get("weight_kg", 0) for s in w.get("sets", []))
                lines.append(f"| {w.get('trained_on')} | {w.get('exercise')} | {sets_desc} | {vol:,} kg |")
        else:
            lines.append("| — | Chưa có buổi tập nào | — | — |")
        lines.append("")

        lines.extend([
            "## ⚖️ Nhật ký cân nặng",
            "| Ngày đo | Cân nặng (kg) |",
            "|---|---|",
        ])
        if weights:
            for r in weights:
                lines.append(f"| {r['measured_on']} | {r['weight_kg']} kg |")
        else:
            lines.append("| — | Chưa có dữ liệu cân nặng |")
        lines.append("")

        lines.extend([
            "## 🎯 Theo dõi thói quen (14 ngày)",
            "| Thói quen | Đã hoàn thành | Tỷ lệ | Chuỗi hiện tại (Streak) |",
            "|---|---|---|---|",
        ])
        habits_list = habits_summary.get("habits", [])
        if habits_list:
            for h in habits_list:
                lines.append(f"| {h.get('habit')} | {h.get('completed_days')}/{h.get('tracked_days', 14)} ngày | {h.get('completion_percent')}% | {h.get('current_streak_days')} ngày |")
        else:
            lines.append("| — | Chưa theo dõi thói quen nào | — | — |")
        lines.append("")

        wiki_file.write_text("\n".join(lines), encoding="utf-8")
        return wiki_file
    except Exception as exc:
        log.warning("Gym wiki sync failed for profile %s: %s", profile_id, exc)
        return None


def sync_all_profiles_to_wiki(user_id: str | None = None) -> int:
    """Lúc khởi động: tạo lại tệp wiki cho mọi hồ sơ (tệp chỉ được ghi khi có hoạt động mới; bị xoá thì mất hẳn)."""
    return sum(sync_profile_to_wiki(p["profile_id"], user_id=user_id) is not None for p in list_profiles(user_id=user_id))


def list_all_gym_records(q: str = "", limit: int = 50, offset: int = 0, user_id: str | None = None) -> dict:
    """Liệt kê toàn bộ các bản ghi Gym (hồ sơ, buổi tập, cân nặng, thói quen)
    để hiển thị và quản lý trong Settings → Memory Control Center."""
    items = []
    profiles = list_profiles(user_id=user_id)
    needle = q.strip().lower()

    for p in profiles:
        pid = p["profile_id"]
        pname = p.get("name", "Chưa đặt tên")
        created_at = p.get("created_at", "")

        # 1. Bản ghi hồ sơ
        if not needle or needle in pname.lower() or needle in "hồ sơ" or needle in "profile":
            items.append({
                "id": f"profile_{pid}",
                "type": "profile",
                "record_type": "profile",
                "profile_id": pid,
                "profile_name": pname,
                "title": f"Hồ sơ Gym: {pname}",
                "content": f"Hồ sơ tập luyện của {pname}. Khởi tạo: {created_at[:16].replace('T', ' ')}.",
                "date": created_at[:10] if created_at else "",
                "created_at": created_at,
            })

        # 2. Buổi tập
        try:
            with _connect(pid, user_id=user_id) as conn:
                w_rows = conn.execute("SELECT * FROM workouts ORDER BY trained_on DESC, id DESC").fetchall()
                for w in w_rows:
                    sets = json.loads(w["sets_json"])
                    sets_text = ", ".join(f"{s.get('reps')}x{s.get('weight_kg')}kg" for s in sets)
                    vol = sum(s.get("reps", 0) * s.get("weight_kg", 0) for s in sets)
                    if not needle or needle in w["exercise"].lower() or needle in pname.lower() or needle in w["trained_on"]:
                        items.append({
                            "id": f"workout_{pid}_{w['id']}",
                            "type": "workout",
                            "record_type": "workout",
                            "item_id": w["id"],
                            "profile_id": pid,
                            "profile_name": pname,
                            "title": f"[{pname}] {w['exercise']}",
                            "content": f"Ngày tập: {w['trained_on']}. Bài: {w['exercise']} ({sets_text}). Tổng volume: {vol:,} kg.",
                            "date": w["trained_on"],
                            "created_at": w["created_at"],
                        })

                # 3. Cân nặng
                bw_rows = conn.execute("SELECT * FROM bodyweight ORDER BY measured_on DESC, id DESC").fetchall()
                for b in bw_rows:
                    if not needle or needle in str(b["weight_kg"]) or needle in pname.lower() or needle in b["measured_on"] or "cân" in needle:
                        items.append({
                            "id": f"bodyweight_{pid}_{b['id']}",
                            "type": "bodyweight",
                            "record_type": "bodyweight",
                            "item_id": b["id"],
                            "profile_id": pid,
                            "profile_name": pname,
                            "title": f"[{pname}] Cân nặng: {b['weight_kg']} kg",
                            "content": f"Ngày đo: {b['measured_on']}. Khối lượng: {b['weight_kg']} kg.",
                            "date": b["measured_on"],
                            "created_at": b["measured_on"],
                        })

                # 4. Thói quen
                h_rows = conn.execute("SELECT * FROM habits ORDER BY day DESC, id DESC").fetchall()
                for h in h_rows:
                    status_text = "Đã hoàn thành" if h["done"] else "Chưa hoàn thành"
                    note_str = f" - Ghi chú: {h['note']}" if h['note'] else ""
                    if not needle or needle in h["habit"].lower() or needle in pname.lower() or needle in h["day"] or "thói quen" in needle:
                        items.append({
                            "id": f"habit_{pid}_{h['id']}",
                            "type": "habit",
                            "record_type": "habit",
                            "item_id": h["id"],
                            "profile_id": pid,
                            "profile_name": pname,
                            "title": f"[{pname}] Thói quen: {h['habit']} ({status_text})",
                            "content": f"Ngày: {h['day']}. Thói quen: {h['habit']}. Trạng thái: {status_text}{note_str}.",
                            "date": h["day"],
                            "created_at": h["day"],
                        })
        except Exception:
            pass

    items.sort(key=lambda x: str(x.get("date") or x.get("created_at") or ""), reverse=True)
    return {"success": True, "items": items[offset:offset + limit], "total": len(items)}


def delete_gym_memory_item(full_id: str, user_id: str | None = None) -> bool:
    """Xóa một bản ghi Gym Memory theo ID và đồng bộ lại tệp Wiki Obsidian."""
    if full_id.startswith("profile_"):
        pid = full_id[len("profile_"):]
        try:
            profile_dir = _profile_dir(pid, user_id=user_id)
            if profile_dir.is_dir():
                profile_meta = profile_dir / "profile.json"
                pname = ""
                if profile_meta.is_file():
                    try:
                        pname = json.loads(profile_meta.read_text(encoding="utf-8")).get("name", "")
                    except Exception:
                        pass
                shutil.rmtree(profile_dir)
                if pname:
                    wiki_file = _wiki_gym_dir(user_id=user_id) / f"{pname}.md"
                    if wiki_file.is_file():
                        wiki_file.unlink(missing_ok=True)
                return True
        except Exception:
            return False

    parts = full_id.split("_")
    if len(parts) < 3:
        return False
    rec_type, pid, raw_id_str = parts[0], parts[1], parts[2]
    try:
        raw_id = int(raw_id_str)
    except ValueError:
        return False

    with _connect(pid, user_id=user_id) as conn:
        if rec_type == "workout":
            conn.execute("DELETE FROM workouts WHERE id = ?", (raw_id,))
        elif rec_type == "bodyweight":
            conn.execute("DELETE FROM bodyweight WHERE id = ?", (raw_id,))
        elif rec_type == "habit":
            conn.execute("DELETE FROM habits WHERE id = ?", (raw_id,))
        else:
            return False

    sync_profile_to_wiki(pid, user_id=user_id)
    return True


def count_all_gym_records(user_id: str | None = None) -> int:
    """Đếm tổng số bản ghi gym để báo cáo Memory Control Center summary."""
    data = list_all_gym_records(limit=1000, user_id=user_id)
    return data.get("total", 0)


def infer_gym_action(arguments: dict) -> tuple[str, dict]:
    """Tự động suy luận action và tham số từ user_text/query nếu action chưa được truyền."""
    action = arguments.get("action")
    if action:
        return action, arguments

    user_text = str(arguments.get("user_text") or arguments.get("query") or "").strip()
    # Loại bỏ mention @gym / @agent_gym nếu còn sót
    user_text = re.sub(r"^@(gym|agent_gym)\s*", "", user_text, flags=re.IGNORECASE).strip()
    t_lower = user_text.lower()

    # 1. Tạo hồ sơ (create_profile)
    create_kw = ("tạo hồ sơ", "tạo profile", "lập hồ sơ", "thêm hồ sơ", "đăng ký hồ sơ", "create_profile", "create profile")
    if any(k in t_lower for k in create_kw) or (
        any(k in t_lower for k in ("hồ sơ", "profile")) and any(v in t_lower for v in ("tạo", "lập", "thêm", "mới", "đăng ký"))
    ):
        name = arguments.get("name", "")
        if not name:
            cleaned = re.sub(
                r"^(?:action\s+)?(?:create_profile|create\s+profile|(?:tạo|lập|thêm|đăng ký)\s+(?:hồ sơ|profile)(?:\s+gym)?(?:\s+mới)?)\s*(?:tên\s+là|tên\s*:|tên|=)?\s*",
                "",
                user_text,
                flags=re.IGNORECASE
            ).strip()
            cleaned = re.sub(r"^(là|cho|của)\s+", "", cleaned, flags=re.IGNORECASE).strip()
            name = cleaned.strip(" :\"'.,")
        return "create_profile", {**arguments, "name": name}

    # 2. Chọn/đổi hồ sơ (select_profile)
    select_kw = ("chọn hồ sơ", "đổi hồ sơ", "chuyển hồ sơ", "select_profile", "select profile", "chọn profile", "đổi profile")
    if any(k in t_lower for k in select_kw):
        target = arguments.get("profile_id", "")
        if not target:
            cleaned = re.sub(
                r"^(?:action\s+)?(?:select_profile|select\s+profile|(?:chọn|đổi|chuyển\s+sang)\s+(?:hồ sơ|profile)(?:\s+gym)?)\s*(?:sang|qua|là|:|=)?\s*",
                "",
                user_text,
                flags=re.IGNORECASE
            ).strip()
            target = cleaned.strip(" :\"'.,")
        profiles = list_profiles()
        matched_id = target
        for p in profiles:
            if p["profile_id"] == target or p["name"].lower() == target.lower():
                matched_id = p["profile_id"]
                break
        return "select_profile", {**arguments, "profile_id": matched_id}

    # 3. Danh sách hồ sơ (list_profiles)
    list_kw = ("danh sách hồ sơ", "danh sách profile", "list profiles", "list_profiles", "xem hồ sơ", "các hồ sơ")
    if any(k in t_lower for k in list_kw):
        return "list_profiles", arguments

    # 4. Hướng dẫn sử dụng & menu lệnh (guide)
    guide_kw = ("hướng dẫn", "trợ giúp", "help", "menu", "các lệnh", "lệnh gì", "làm gì", "cách dùng", "bước tiếp theo")
    if any(k in t_lower for k in guide_kw):
        return "guide", arguments

    # Date inference từ câu nói tự nhiên (hôm nay, hôm qua, ngày DD/MM...)
    detected_date = parse_natural_date(user_text)
    if "trained_on" not in arguments:
        arguments["trained_on"] = detected_date
    if "measured_on" not in arguments:
        arguments["measured_on"] = detected_date
    if "day" not in arguments:
        arguments["day"] = detected_date

    # 5. Ghi nhận buổi tập tự nhiên
    log_workout_kw = ("vừa tập", "đã tập", "tập xong", "ghi bài tập", "ghi buổi tập", "log workout", "log_workout")
    if any(k in t_lower for k in log_workout_kw) or (
        ("tập" in t_lower or "workout" in t_lower) and any(u in t_lower for u in ("reps", "kg", "hiệp", "set", "lần"))
    ):
        if "exercises" not in arguments or not arguments["exercises"]:
            matched_ex = None
            for ex in EXERCISES:
                if ex["name"].lower() in t_lower:
                    matched_ex = ex["name"]
                    break
            if not matched_ex:
                for common_name in ["bench press", "squat", "deadlift", "overhead press", "barbell row", "lat pulldown", "biceps curl", "pull up", "push up", "hít đất", "kéo xà"]:
                    if common_name in t_lower:
                        matched_ex = common_name.title()
                        break
            if not matched_ex:
                m_ex = re.search(r"(?:vừa\s+tập|đã\s+tập|ghi\s+bài\s+tập|tập\s+bài|tập)\s+([a-zA-Z\s]+?)(?:\s+\d|\s+với|\s+\b\d|$)", user_text, re.IGNORECASE)
                if m_ex:
                    matched_ex = m_ex.group(1).strip()

            reps_m = re.search(r"(\d+)\s*(?:reps|lần|cái)", t_lower)
            weight_m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:kg|kí|cân)", t_lower)
            sets_m = re.search(r"(\d+)\s*(?:hiệp|sets|set)", t_lower)

            reps = int(reps_m.group(1)) if reps_m else 10
            weight = float(weight_m.group(1).replace(",", ".")) if weight_m else 0.0
            num_sets = int(sets_m.group(1)) if sets_m else 3

            if matched_ex:
                sets_list = [{"reps": reps, "weight_kg": weight} for _ in range(num_sets)]
                return "log_workout", {**arguments, "trained_on": detected_date, "exercises": [{"name": matched_ex, "sets": sets_list}]}

    if any(k in t_lower for k in ("ăn uống", "dinh dưỡng", "calo", "protein", "thực đơn", "nutrition")):
        goal = "eat_food"
        if any(k in t_lower for k in ("tăng cơ", "gain muscle", "tăng cân")):
            goal = "gain_muscle"
        elif any(k in t_lower for k in ("giảm mỡ", "giảm cân", "fat loss", "siết cơ", "siết mỡ")):
            goal = "fat_loss"
        elif any(k in t_lower for k in ("duy trì", "maintain", "giữ cân")):
            goal = "maintain"
        return "nutrition_guide", {**arguments, "goal": arguments.get("goal") or goal}

    if any(k in t_lower for k in ("bài tập", "video", "hướng dẫn tập", "squat", "bench press", "deadlift", "row", "curl", "press", "ngực", "lưng", "vai", "tay", "chân")):
        query = arguments.get("query", "")
        if not query or query == user_text:
            cleaned = re.sub(r"^(tìm|xem|cho tôi|hướng dẫn|tra cứu|các)\s+(bài tập|video)?\s*", "", t_lower).strip()
            query = cleaned or user_text
        return "search_exercises", {**arguments, "query": query}

    if any(k in t_lower for k in ("thống kê", "tiến độ", "volume", "tổng kết", "stats")):
        return "stats", arguments
    if any(k in t_lower for k in ("lịch sử", "nhật ký", "đã tập", "history")):
        return "history", arguments

    if any(k in t_lower for k in ("thói quen", "habit")):
        return "habit_summary", arguments

    weight_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:kg|kí|cân)", t_lower)
    if any(k in t_lower for k in ("cân nặng", "nặng", "cân được")) and weight_match:
        val = float(weight_match.group(1).replace(",", "."))
        return "record_bodyweight", {**arguments, "weight_kg": val, "measured_on": detected_date}

    return "list_profiles", arguments


def run_gym_tool(arguments: dict, user_id: str | None = None) -> dict:
    user_id = _resolve_user_id(user_id)
    arguments = dict(arguments)
    if isinstance(arguments.get("exercises"), str):  # schema tool khai mọi tham số là string
        try:
            arguments["exercises"] = json.loads(arguments["exercises"])
        except Exception:
            pass
    if isinstance(arguments.get("done"), str):
        arguments["done"] = {"true": True, "false": False}.get(arguments["done"].strip().lower(), arguments["done"])

    action, arguments = infer_gym_action(arguments)
    arguments["action"] = action

    if action == "nutrition_guide":
        return nutrition_guide(arguments.get("goal", "eat_food"))
    if action in ("list_profiles", "guide"):
        active = get_active_profile(user_id=user_id)
        profiles = list_profiles(user_id=user_id)
        status_msg = (
            f"Hồ sơ gym hiện hành: {active['name']} (ID: {active['profile_id']})."
            if active else
            "Chưa có hồ sơ gym. Ngài có thể tạo hồ sơ mới bằng cú pháp: `@gym tạo hồ sơ [Tên]`."
            if not profiles else
            "Có nhiều hồ sơ gym và chưa chọn hồ sơ hiện hành. Hãy chọn bằng: `@gym chọn hồ sơ [Tên]`."
        )
        return {
            "profiles": profiles,
            "active_profile": active,
            "active_profile_id": active["profile_id"] if active else None,
            "commands_guide": GYM_COMMAND_GUIDE,
            "message": status_msg
        }
    if action == "create_profile":
        name = str(arguments.get("name", "")).strip()
        if not name:
            return {
                "needs_name": True,
                "message": "Vui lòng cung cấp tên hồ sơ muốn tạo (Ví dụ: `@gym tạo hồ sơ [Tên của bạn]`)."
            }
        try:
            profile = create_profile(name, user_id=user_id)
            return {
                **profile,
                "commands_guide": GYM_COMMAND_GUIDE,
                "message": (
                    f"Đã tạo và kích hoạt thành công hồ sơ gym cho '{profile['name']}' (ID: {profile['profile_id']}).\n\n"
                    "Gợi ý các bước tiếp theo ngài có thể thực hiện ngay:\n"
                    "- 🏋️ Ghi buổi tập: `@gym vừa tập Bench Press 3 hiệp 10 reps 60kg`\n"
                    "- ⚖️ Ghi cân nặng: `@gym hôm nay cân nặng 72kg`\n"
                    "- 🔍 Tra cứu bài tập: `@gym tìm bài tập ngực`\n"
                    "- 📊 Xem thống kê: `@gym thống kê tiến độ`"
                )
            }
        except Exception as e:
            return {"error": str(e), "message": f"Không thể tạo hồ sơ: {e}"}
    if action == "select_profile":
        pid = str(arguments.get("profile_id", "")).strip()
        if not pid:
            profiles = list_profiles(user_id=user_id)
            return {
                "needs_profile_selection": True,
                "profiles": profiles,
                "message": "Vui lòng chọn hồ sơ theo ID hoặc tên: " + ", ".join(f"{p['name']} ({p['profile_id'][:8]})" for p in profiles) if profiles else "Chưa có hồ sơ nào."
            }
        profiles = list_profiles(user_id=user_id)
        for p in profiles:
            if p["profile_id"] == pid or p["name"].lower() == pid.lower():
                pid = p["profile_id"]
                break
        try:
            profile = select_profile(pid, user_id=user_id)
            return {
                **profile,
                "commands_guide": GYM_COMMAND_GUIDE,
                "message": (
                    f"Đã chọn hồ sơ gym '{profile['name']}' (ID: {profile['profile_id']}).\n"
                    "Ngài có thể bắt đầu ghi buổi tập (`@gym vừa tập...`) hoặc xem thống kê (`@gym thống kê tiến độ`)."
                )
            }
        except Exception as e:
            return {"error": str(e), "message": f"Không thể chọn hồ sơ: {e}"}
    if action == "search_exercises":
        q = arguments.get("query", "")
        exs = search_exercises(q)
        if exs:
            lines = []
            for ex in exs:
                vn_name = ex.get("vietnamese_name") or ex["name"]
                muscles = ", ".join(ex.get("muscles", []))
                url = ex.get("video_url", "")
                title = ex.get("video_title", "Xem video YouTube")
                lines.append(f"- 🎥 **{vn_name}** ({ex['name']})\n  • Nhóm cơ: {muscles}\n  • Kỹ thuật: [{title}]({url})")
            msg = f"Tìm thấy {len(exs)} bài tập phù hợp:\n\n" + "\n\n".join(lines)
        else:
            msg = f"Chưa tìm thấy bài tập phù hợp với từ khóa '{q}'. Ngài có thể tìm theo nhóm cơ như: ngực, lưng, vai, tay, chân, bụng."
        return {"exercises": exs, "message": msg, "count": len(exs)}
    explicit_id = arguments.get("profile_id", "")
    active = select_profile(explicit_id, user_id=user_id) if explicit_id else get_active_profile(user_id=user_id)
    if not active:
        profiles = list_profiles(user_id=user_id)
        if not profiles:
            return {"needs_profile_creation": True, "profiles": [], "message": "Chưa có hồ sơ gym. Hỏi người dùng có muốn tạo hồ sơ không; chỉ tạo sau khi họ đồng ý."}
        return {"needs_profile_selection": True, "profiles": profiles, "message": "Có nhiều hồ sơ và chưa chọn hồ sơ hiện hành. Hỏi người dùng chọn theo tên hoặc ID."}
    profile_id = active["profile_id"]
    if action == "log_workout":
        return log_workout(profile_id, arguments.get("trained_on", date.today().isoformat()), arguments.get("exercises", []), user_id=user_id)
    if action == "record_bodyweight":
        return record_bodyweight(profile_id, arguments.get("measured_on", date.today().isoformat()), arguments.get("weight_kg"), user_id=user_id)
    if action == "log_habit":
        return log_habit(profile_id, arguments.get("day", date.today().isoformat()), arguments.get("habit", ""), arguments.get("done"), arguments.get("note", ""), user_id=user_id)
    if action == "habit_summary":
        return get_habit_summary(profile_id, arguments.get("days", 7), user_id=user_id)
    if action == "history":
        return {"profile_id": profile_id, "workouts": get_history(profile_id, arguments.get("limit", 20), user_id=user_id)}
    if action == "stats":
        return get_training_stats(profile_id, user_id=user_id)
    raise ValueError("Thao tác gym không hợp lệ.")

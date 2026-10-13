import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from engine.tools import gym_engine


@pytest.fixture(autouse=True)
def _wiki_in_tmp(tmp_path, monkeypatch):
    """2026-10-13: test chỉ đổi GYM_DATA_DIR nên create_profile ghi hồ sơ giả (An, Lan, Minh, erikpuw) vào
    data/wiki/Gym thật, đè cả tệp của hồ sơ thật. Mọi test gym ghi wiki vào thư mục tạm."""
    monkeypatch.setattr(gym_engine, "WIKI_GYM_DIR", tmp_path / "wiki-default" / "Gym")


def test_profiles_isolate_workout_and_weight_data(tmp_path, monkeypatch):
    monkeypatch.setattr(gym_engine, "GYM_DATA_DIR", tmp_path / "gym")

    profile = gym_engine.create_profile("Lan")
    other = gym_engine.create_profile("Lan")
    assert profile["profile_id"] != other["profile_id"]
    assert (tmp_path / "gym" / profile["profile_id"]).is_dir()

    workout = gym_engine.log_workout(
        profile["profile_id"],
        "2026-10-07",
        [{"name": "Bench press", "sets": [
            {"reps": 5, "weight_kg": 60},
            {"reps": 5, "weight_kg": 60},
        ]}],
    )
    gym_engine.record_bodyweight(profile["profile_id"], "2026-10-07", 70.5)

    assert workout["volume_kg"] == 600
    stats = gym_engine.get_training_stats(profile["profile_id"], days=30)
    assert stats["session_count"] == 1
    assert stats["total_volume_kg"] == 600
    assert stats["bodyweight_latest_kg"] == 70.5
    assert gym_engine.get_training_stats(other["profile_id"], days=30)["session_count"] == 0


def test_profile_id_is_validated_before_path_access(tmp_path, monkeypatch):
    monkeypatch.setattr(gym_engine, "GYM_DATA_DIR", tmp_path / "gym")

    try:
        gym_engine.get_training_stats("../outside", days=30)
    except ValueError as exc:
        assert "profile" in str(exc).lower()
    else:
        raise AssertionError("unsafe profile id should be rejected")


def test_active_profile_persists_until_user_selects_another(tmp_path, monkeypatch):
    monkeypatch.setattr(gym_engine, "GYM_DATA_DIR", tmp_path / "gym")
    first = gym_engine.create_profile("Lan")
    second = gym_engine.create_profile("Minh")

    assert gym_engine.get_active_profile()["profile_id"] == first["profile_id"]
    gym_engine.select_profile(second["profile_id"])
    assert gym_engine.run_gym_tool({"action": "stats"})["profile_id"] == second["profile_id"]


def test_exercises_provide_clickable_video_links():
    items = gym_engine.search_exercises()
    assert all(item["video_url"].startswith("https://www.youtube.com/watch?v=") for item in items)
    assert all("image_url" not in item for item in items)


def test_nutrition_guide_is_general_and_links_authoritative_sources():
    result = gym_engine.run_gym_tool({"action": "nutrition_guide", "goal": "maintain"})
    assert result["goal"] == "maintain"
    assert "calorie_target" not in result
    assert any("who.int" in source for source in result["sources"])


def test_habits_are_saved_per_profile_and_summarized(tmp_path, monkeypatch):
    monkeypatch.setattr(gym_engine, "GYM_DATA_DIR", tmp_path / "gym")
    first = gym_engine.create_profile("Lan")
    second = gym_engine.create_profile("Minh")
    today = gym_engine.date.today().isoformat()

    entry = gym_engine.run_gym_tool({"action": "log_habit", "habit": "Ăn rau trong bữa trưa", "done": True, "day": today})
    assert entry["profile_id"] == first["profile_id"]
    summary = gym_engine.run_gym_tool({"action": "habit_summary", "days": 7})
    assert summary["habits"][0]["completed_days"] == 1

    gym_engine.select_profile(second["profile_id"])
    assert gym_engine.run_gym_tool({"action": "habit_summary"})["habits"] == []


def test_run_gym_tool_accepts_string_typed_arguments(tmp_path, monkeypatch):
    """Schema khai mọi tham số là string nên model có thể gửi exercises dạng JSON và done dạng "true"."""
    monkeypatch.setattr(gym_engine, "GYM_DATA_DIR", tmp_path / "gym")
    gym_engine.create_profile("An")
    out = gym_engine.run_gym_tool({"action": "log_workout", "trained_on": "2026-10-01",
                                   "exercises": '[{"name": "Squat", "sets": [{"reps": 5, "weight_kg": 100}]}]'})
    assert out["volume_kg"] == 500
    habit = gym_engine.run_gym_tool({"action": "log_habit", "day": "2026-10-01", "habit": "đi bộ", "done": "true"})
    assert habit["done"] is True
    assert gym_engine.run_gym_tool({"action": "record_bodyweight", "weight_kg": "70", "measured_on": "2026-10-01"})["weight_kg"] == 70


def test_gym_manage_registered_and_in_direct_tools():
    """Kiểm tra tool gym được đăng ký chuẩn trong registry."""
    from engine.tools import registry
    assert "gym" in registry.names()
    spec = registry.get("gym")
    assert spec is not None
    assert spec.kind == "change"


def test_run_gym_tool_handles_empty_or_inferred_action(tmp_path, monkeypatch):
    """Khi người dùng chỉ gõ @agent_gym (user_text rỗng hoặc không có action rõ ràng),
    run_gym_tool tự động suy luận action phù hợp thay vì văng ValueError."""
    monkeypatch.setattr(gym_engine, "GYM_DATA_DIR", tmp_path / "gym")

    # 1. Rỗng hoặc chỉ có user_text="" (mặc định list_profiles)
    res_empty = gym_engine.run_gym_tool({"user_text": "", "query": ""})
    assert "profiles" in res_empty

    # 2. user_text hỏi dinh dưỡng
    res_nutrition = gym_engine.run_gym_tool({"user_text": "tư vấn dinh dưỡng tăng cơ", "query": "tư vấn dinh dưỡng tăng cơ"})
    assert res_nutrition.get("goal") in ["gain_muscle", "eat_food"]

    # 3. user_text hỏi bài tập
    res_exercise = gym_engine.run_gym_tool({"user_text": "tìm bài tập squat", "query": "squat"})
    assert "exercises" in res_exercise




def test_infer_and_create_profile_natural_language(tmp_path, monkeypatch):
    """Kiểm tra tạo và chọn hồ sơ bằng ngôn ngữ tự nhiên thông qua run_gym_tool."""
    monkeypatch.setattr(gym_engine, "GYM_DATA_DIR", tmp_path / "gym")

    # 1. Tạo hồ sơ với tên
    res1 = gym_engine.run_gym_tool({"user_text": "@gym tạo hồ sơ erikpuw", "query": "@gym tạo hồ sơ erikpuw"})
    assert res1.get("name") == "erikpuw"
    assert "profile_id" in res1
    assert "thành công" in res1.get("message", "").lower()

    # 2. Tạo hồ sơ với cú pháp khác
    res2 = gym_engine.run_gym_tool({"user_text": "tạo hồ sơ tên là Minh", "query": "tạo hồ sơ tên là Minh"})
    assert res2.get("name") == "Minh"

    # 3. Tạo hồ sơ cú pháp create_profile Lan
    res3 = gym_engine.run_gym_tool({"user_text": "create_profile Lan", "query": "create_profile Lan"})
    assert res3.get("name") == "Lan"

    # 4. Tạo hồ sơ không kèm tên -> hỏi tên thay vì rơi vào list_profiles
    res4 = gym_engine.run_gym_tool({"user_text": "@gym tạo hồ sơ", "query": "@gym tạo hồ sơ"})
    assert res4.get("needs_name") is True
    assert "vui lòng cung cấp tên" in res4.get("message", "").lower()

    # 5. Lệnh action create_profile không kèm tên
    res5 = gym_engine.run_gym_tool({"user_text": "@gym action create_profile", "query": "@gym action create_profile"})
    assert res5.get("needs_name") is True

    # 6. Chọn hồ sơ theo tên
    res_select = gym_engine.run_gym_tool({"user_text": "@gym chọn hồ sơ erikpuw", "query": "@gym chọn hồ sơ erikpuw"})
    assert res_select.get("name") == "erikpuw"
    assert res_select.get("profile_id") == res1["profile_id"]

    # 7. Xem danh sách hồ sơ
    res_list = gym_engine.run_gym_tool({"user_text": "@gym danh sách hồ sơ", "query": "@gym danh sách hồ sơ"})
    assert "profiles" in res_list
    assert len(res_list["profiles"]) == 3


def test_local_timezone_and_natural_date_parsing(tmp_path, monkeypatch):
    """Kiểm tra xử lý chuẩn giờ địa phương và các mốc thời gian tự nhiên."""
    from datetime import date, timedelta
    monkeypatch.setattr(gym_engine, "GYM_DATA_DIR", tmp_path / "gym")

    today = date.today()
    yesterday = today - timedelta(days=1)
    day_before_yesterday = today - timedelta(days=2)

    assert gym_engine.parse_natural_date("vừa tập hôm nay") == today.isoformat()
    assert gym_engine.parse_natural_date("tập hôm qua 3 hiệp") == yesterday.isoformat()
    assert gym_engine.parse_natural_date("cân sáng hôm kia") == day_before_yesterday.isoformat()
    assert gym_engine.parse_natural_date("buổi tập ngày 25/12/2026") == "2026-12-25"
    assert gym_engine.parse_natural_date("tập squat bình thường") == today.isoformat()

    now_local = gym_engine.get_local_now()
    assert now_local.tzinfo is not None


def test_gym_wiki_sync_and_semantic_exclusion(tmp_path, monkeypatch):
    """Kiểm tra đồng bộ nhật ký ra data/wiki/Gym/<name>.md và loại trừ khỏi semantic memory."""
    wiki_dir = tmp_path / "wiki"
    monkeypatch.setattr(gym_engine, "GYM_DATA_DIR", tmp_path / "gym")
    monkeypatch.setattr(gym_engine, "WIKI_GYM_DIR", wiki_dir / "Gym")

    # 1. Tạo hồ sơ và ghi log
    profile = gym_engine.create_profile("John Doe")
    pid = profile["profile_id"]
    gym_engine.log_workout(pid, "2026-10-07", [{"name": "Bench Press", "sets": [{"reps": 10, "weight_kg": 60}]}])
    gym_engine.record_bodyweight(pid, "2026-10-07", 75.0)
    gym_engine.run_gym_tool({"action": "log_habit", "habit": "Uống 2L nước", "done": True, "day": "2026-10-07"})

    wiki_file = wiki_dir / "Gym" / "John Doe.md"
    assert wiki_file.is_file()
    content = wiki_file.read_text(encoding="utf-8")
    assert "no_index: true" in content
    assert "type: gym_log" in content
    assert "Bench Press" in content
    assert "75.0 kg" in content
    assert "Uống 2L nước" in content

    # 2. Kiểm tra wiki_sync loại trừ file
    from engine.core import wiki_sync
    monkeypatch.setattr(wiki_sync, "WIKI_DIR", wiki_dir)
    assert wiki_file.relative_to(wiki_dir).as_posix().lower().startswith("gym/")


def test_gym_memory_control_and_endpoints(tmp_path, monkeypatch):
    """Kiểm tra các hàm quản trị Gym Memory: list_all, count, delete, và API endpoints."""
    import asyncio
    monkeypatch.setattr(gym_engine, "GYM_DATA_DIR", tmp_path / "gym")
    wiki_dir = tmp_path / "wiki"
    monkeypatch.setattr(gym_engine, "WIKI_GYM_DIR", wiki_dir / "Gym")

    # Tạo hồ sơ & bản ghi
    profile = gym_engine.create_profile("Alice")
    pid = profile["profile_id"]
    gym_engine.log_workout(pid, "2026-10-07", [{"name": "Squat", "sets": [{"reps": 5, "weight_kg": 100}]}])
    gym_engine.record_bodyweight(pid, "2026-10-07", 55.0)
    gym_engine.run_gym_tool({"action": "log_habit", "habit": "Ngủ đủ 8 tiếng", "done": True, "day": "2026-10-07"})

    # 1. Đếm và liệt kê
    count = gym_engine.count_all_gym_records()
    assert count >= 4  # 1 profile + 1 workout + 1 weight + 1 habit

    listed = gym_engine.list_all_gym_records()
    assert listed["success"] is True
    assert listed["total"] == count
    item_types = {item["type"] for item in listed["items"]}
    assert "profile" in item_types
    assert "workout" in item_types
    assert "bodyweight" in item_types
    assert "habit" in item_types

    # 2. Test API endpoints trong ui_engine
    from engine.UIUX.ui_engine import api_gym_list, api_gym_delete, api_memory_control_summary

    api_list_res = asyncio.run(api_gym_list())
    assert api_list_res["success"] is True
    assert api_list_res["total"] == count

    summary_res = asyncio.run(api_memory_control_summary())
    assert summary_res["success"] is True
    assert summary_res["counts"]["gym"] == count

    # 3. Test Xóa 1 bản ghi workout qua api_gym_delete
    workout_item = next(item for item in listed["items"] if item["type"] == "workout")
    del_res = asyncio.run(api_gym_delete(workout_item["id"]))
    assert del_res["success"] is True
    assert gym_engine.count_all_gym_records() == count - 1


def test_vietnamese_exercise_search_and_unicode_formatting():
    """Kiểm tra tìm bài tập bằng tiếng Việt (có dấu và không dấu) và định dạng UTF-8 không escape."""
    import json
    from engine.server.text_streamer import clean_latex_math

    # 1. Tìm kiếm bài tập ngực (có dấu và không dấu)
    ex_nguc = gym_engine.search_exercises("ngực")
    assert len(ex_nguc) >= 2
    assert any("bench press" in ex["name"].lower() for ex in ex_nguc)

    ex_nguc_kodau = gym_engine.search_exercises("tim bai tap nguc")
    assert len(ex_nguc_kodau) >= 2
    assert any("bench press" in ex["name"].lower() for ex in ex_nguc_kodau)

    # 2. Tìm kiếm các nhóm cơ khác
    ex_lung = gym_engine.search_exercises("bài tập lưng")
    assert any("pull up" in ex["name"].lower() or "row" in ex["name"].lower() for ex in ex_lung)

    ex_vai = gym_engine.search_exercises("tìm bài tập vai")
    assert any("overhead press" in ex["name"].lower() or "lateral raise" in ex["name"].lower() for ex in ex_vai)

    ex_bung = gym_engine.search_exercises("bụng")
    assert any("crunch" in ex["name"].lower() or "abs" in ex.get("muscles", []) for ex in ex_bung)

    # 3. Test run_gym_tool với câu lệnh tự nhiên tìm bài tập ngực
    res_tool = gym_engine.run_gym_tool({"user_text": "@gym tìm bài tập ngực", "query": "@gym tìm bài tập ngực"})
    assert "exercises" in res_tool
    assert len(res_tool["exercises"]) >= 2
    assert "Bench Press" in res_tool["message"]
    assert "https://www.youtube.com" in res_tool["message"]

    # 4. Kiểm tra JSON không chứa mã escape \uXXXX
    formatted = json.dumps(res_tool, ensure_ascii=False)
    assert "\\u" not in formatted
    assert "Bench Press" in formatted

    # 5. Kiểm tra clean_latex_math tự giải mã chuỗi unicode escape nếu có
    dirty_text = r"@gym v\u1eeba t\u1eadp Bench Press 3 hi\u1ec7p 10 reps 60kg"
    cleaned = clean_latex_math(dirty_text)
    assert cleaned == "@gym vừa tập Bench Press 3 hiệp 10 reps 60kg"






def test_sync_all_profiles_recreates_missing_wiki(tmp_path, monkeypatch):
    """Ngài 2026-10-13: hồ sơ gym có trong data/gym nhưng không có trong wiki — tệp chỉ ghi khi có hoạt động mới.
    Khởi động đồng bộ lại mọi hồ sơ, kể cả hồ sơ chưa có buổi tập nào."""
    monkeypatch.setattr(gym_engine, "GYM_DATA_DIR", tmp_path / "gym")
    monkeypatch.setattr(gym_engine, "WIKI_GYM_DIR", tmp_path / "wiki" / "Gym")
    gym_engine.create_profile("erikpuw")
    wiki = tmp_path / "wiki" / "Gym" / "erikpuw.md"
    wiki.unlink()
    assert gym_engine.sync_all_profiles_to_wiki() == 1
    assert wiki.is_file() and "erikpuw" in wiki.read_text(encoding="utf-8")


def test_sync_failure_is_logged_not_silent(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(gym_engine, "GYM_DATA_DIR", tmp_path / "gym")
    monkeypatch.setattr(gym_engine, "WIKI_GYM_DIR", tmp_path / "wiki" / "Gym")
    profile = gym_engine.create_profile("Lan")

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(gym_engine, "get_training_stats", boom)
    with caplog.at_level("WARNING"):
        assert gym_engine.sync_profile_to_wiki(profile["profile_id"]) is None
    assert "disk full" in caplog.text

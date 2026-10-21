import os
import shutil
from engine.turn import prompt as P
from engine.core.memory import _get_db
import sys
import uuid
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.UIUX import ui_engine, memory_lock
from engine.core.memory import init_db, save_message
from engine.core.learning import get_learning_engine

app = FastAPI()
app.include_router(ui_engine.router)
app.include_router(memory_lock.lock_router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-pass-123")
    init_db()
    get_learning_engine()._init_db()
    memory_lock._tokens.clear()
    yield
    memory_lock._tokens.clear()
    from engine.core.session_context import set_current_user_id
    set_current_user_id("admin")
    with _get_db() as conn:
        conn.execute("DELETE FROM learnings WHERE semantic_key = 'rule1' OR content LIKE 'Admin learning rule%'")
        conn.execute("DELETE FROM messages WHERE session_id = 'admin-session' OR content = 'Admin secret message'")
        conn.execute("DELETE FROM session_devices WHERE session_id = 'admin-session'")
        # Dọn dẹp triệt để toàn bộ user rác phát sinh từ test
        junk_users = conn.execute("SELECT id FROM users WHERE username LIKE 'member_%' OR username LIKE 'user_%' OR username LIKE 'lan_%' OR id LIKE 'mem_%'").fetchall()
        for u in junk_users:
            uid = u[0]
            conn.execute("DELETE FROM users WHERE id = ?", (uid,))
            conn.execute("DELETE FROM learnings WHERE user_id = ?", (uid,))
            conn.execute("DELETE FROM messages WHERE user_id = ?", (uid,))
            shutil.rmtree(Path("data/users") / uid, ignore_errors=True)
        conn.commit()
    get_learning_engine()._sync_learning_wiki()


def test_member_memory_and_history_isolation():
    # 1. Admin login
    res_adm = client.post("/api/auth/login", json={"username": "admin", "password": "admin-pass-123"})
    assert res_adm.status_code == 200
    token_admin = res_adm.json()["token"]

    # 2. Member login
    member_user = f"member_{uuid.uuid4().hex[:6]}"
    res_mem = client.post("/api/auth/login", json={"username": member_user})
    assert res_mem.status_code == 200
    mem_data = res_mem.json()
    token_mem = mem_data["token"]
    user_id = mem_data["user"]["id"]

    # Ensure admin has learnings
    learning_engine = get_learning_engine()
    learning_engine._store_learning("Admin learning rule: Luon ngan gon.", "feedback_lesson", "rule1", user_id="admin")

    # 3. Member queries learnings -> should NOT see admin's learnings
    res_mem_learn = client.get("/api/learnings/list", headers={"Authorization": f"Bearer {token_mem}"})
    assert res_mem_learn.status_code == 200
    mem_learnings = res_mem_learn.json()
    assert mem_learnings["success"] is True
    assert mem_learnings["total"] == 0
    assert len(mem_learnings["learnings"]) == 0

    # Admin queries learnings -> sees learnings
    res_adm_learn = client.get("/api/learnings/list", headers={"Authorization": f"Bearer {token_admin}"})
    assert res_adm_learn.status_code == 200
    adm_learnings = res_adm_learn.json()
    assert adm_learnings["total"] >= 1

    # 4. Evolution isolation:
    # Member evolution should be separate from system STYLE.md
    res_mem_evo = client.get("/api/evolution/list", headers={"Authorization": f"Bearer {token_mem}"})
    assert res_mem_evo.status_code == 200
    mem_evo_items = res_mem_evo.json()["items"]
    mem_style = next(i for i in mem_evo_items if i["id"] == "style")
    # Member style path should point to users folder, not root skills/self_evolution/STYLE.md
    assert f"data/users/{user_id}/STYLE.md" in mem_style["path"]

    res_adm_evo = client.get("/api/evolution/list", headers={"Authorization": f"Bearer {token_admin}"})
    assert res_adm_evo.status_code == 200
    adm_evo_items = res_adm_evo.json()["items"]
    adm_style = next(i for i in adm_evo_items if i["id"] == "style")
    assert adm_style["path"].endswith("STYLE.md")
    assert "data/users/" not in adm_style["path"]

    # 5. Summary counts isolation
    res_mem_sum = client.get("/api/memory-control/summary", headers={"Authorization": f"Bearer {token_mem}"})
    assert res_mem_sum.status_code == 200
    mem_counts = res_mem_sum.json()["counts"]
    assert mem_counts["learnings"] == 0
    assert mem_counts["conversations"] == 0

    # 6. History and conversations isolation
    save_message("user", "Admin secret message", session_id="admin-session")
    res_mem_hist = client.get("/api/history", headers={"Authorization": f"Bearer {token_mem}"})
    assert res_mem_hist.status_code == 200
    assert len(res_mem_hist.json()["history"]) == 0

    res_adm_hist = client.get("/api/history", headers={"Authorization": f"Bearer {token_admin}"})
    assert res_adm_hist.status_code == 200
    assert len(res_adm_hist.json()["history"]) >= 1


def test_member_gym_data_isolation(tmp_path, monkeypatch):
    from engine.tools import gym_engine
    admin_gym_dir = tmp_path / "gym"
    monkeypatch.setattr(gym_engine, "GYM_DATA_DIR", admin_gym_dir)
    monkeypatch.setattr(gym_engine, "WIKI_GYM_DIR", tmp_path / "wiki" / "Gym")

    # 1. Admin login
    res_adm = client.post("/api/auth/login", json={"username": "admin", "password": "admin-pass-123"})
    token_admin = res_adm.json()["token"]

    # 2. Member login
    member_user = f"member_{uuid.uuid4().hex[:6]}"
    res_mem = client.post("/api/auth/login", json={"username": member_user})
    token_mem = res_mem.json()["token"]
    user_id = res_mem.json()["user"]["id"]

    user_gym_dir = tmp_path / "users" / user_id / "gym"
    def mock_gym_data_dir(uid=None):
        resolved = gym_engine._resolve_user_id(uid)
        if resolved and resolved != "admin":
            return tmp_path / "users" / resolved / "gym"
        return admin_gym_dir

    monkeypatch.setattr(gym_engine, "_gym_data_dir", mock_gym_data_dir)

    # Admin creates profile & workout
    adm_prof = gym_engine.create_profile("AdminFit", user_id="admin")
    gym_engine.log_workout(adm_prof["profile_id"], "2026-10-08", [{"name": "Bench Press", "sets": [{"reps": 10, "weight_kg": 80}]}], user_id="admin")

    # Member creates profile & workout
    mem_prof = gym_engine.create_profile("MemberCardio", user_id=user_id)
    gym_engine.log_workout(mem_prof["profile_id"], "2026-10-08", [{"name": "Running", "sets": [{"reps": 1, "weight_kg": 0}]}], user_id=user_id)

    # 3. Member queries gym list -> sees MemberCardio, NOT AdminFit
    res_mem_gym = client.get("/api/gym/list", headers={"Authorization": f"Bearer {token_mem}"})
    assert res_mem_gym.status_code == 200
    mem_items = res_mem_gym.json()["items"]
    assert any(i["title"] == "Hồ sơ Gym: MemberCardio" for i in mem_items)
    assert not any("AdminFit" in i["title"] for i in mem_items)

    # 4. Admin queries gym list -> sees AdminFit, NOT MemberCardio
    res_adm_gym = client.get("/api/gym/list", headers={"Authorization": f"Bearer {token_admin}"})
    assert res_adm_gym.status_code == 200
    adm_items = res_adm_gym.json()["items"]
    assert any(i["title"] == "Hồ sơ Gym: AdminFit" for i in adm_items)
    assert not any("MemberCardio" in i["title"] for i in adm_items)

    # 5. Member summary count matches member's gym records
    res_mem_sum = client.get("/api/memory-control/summary", headers={"Authorization": f"Bearer {token_mem}"})
    assert res_mem_sum.status_code == 200
    assert res_mem_sum.json()["counts"]["gym"] == len(mem_items)




def test_admin_prompt_reads_env_and_system_files(monkeypatch):
    monkeypatch.setenv("HONORIFIC", "Chủ tịch")
    monkeypatch.setenv("USER_NAME", "Erik Boss")

    # Call system prompt for admin
    s = P.system_prompt(["open_app"], user_id="admin")

    assert "chủ tịch Erik Boss" in s or "Chủ tịch Erik Boss" in s
    assert 'gọi người dùng là "chủ tịch"' in s
    assert 'Xưng hô với người dùng là "tôi"' in s


def test_member_prompt_reads_db_and_user_scoped_files(tmp_path, monkeypatch):
    member_id = f"mem_{uuid.uuid4().hex[:6]}"
    username = f"lan_{uuid.uuid4().hex[:6]}"

    # Insert member profile into DB
    with _get_db() as conn:
        conn.execute(
            """INSERT INTO users (id, username, display_name, user_pronoun, ai_pronoun, role, created_at)
               VALUES (?, ?, ?, ?, ?, 'member', 1700000000)""",
            (member_id, username, "Hoàng Lan", "Chị", "Em")
        )
        conn.execute(
            """INSERT INTO learnings (user_id, content, type, created_at)
               VALUES (?, 'Thích uống trà đào', 'preference', 1700000000)""",
            (member_id,)
        )
        conn.execute(
            """INSERT INTO learnings (user_id, content, type, created_at)
               VALUES (?, 'Không thích nói chuyện lan man', 'lesson', 1700000000)""",
            (member_id,)
        )

    # Set up user-scoped folder
    user_dir = P.ROOT / "data" / "users" / member_id
    user_dir.mkdir(parents=True, exist_ok=True)
    try:
        (user_dir / "STYLE.md").write_text("- Luôn dạ thưa lễ phép.\n- Trả lời dịu dàng.", encoding="utf-8")

        # Call system prompt for member
        s = P.system_prompt(["open_app"], user_id=member_id)

        # 1. Identity & Honorifics
        assert "chị Hoàng Lan" in s or "Chị Hoàng Lan" in s
        assert 'gọi người dùng là "chị"' in s
        assert 'Xưng hô với người dùng là "Em"' in s
        assert "erikpuw" not in s

        # 2. Tone / Evolution
        assert "<giong_dieu>" in s
        assert "Luôn dạ thưa lễ phép." in s
        assert "Trả lời dịu dàng." in s

        # 3. Preferences & Learnings
        assert "<nguoi_dung>" in s
        assert "Thích uống trà đào" in s

        # 4. Lessons
        assert "<bai_hoc>" in s
        assert "Không thích nói chuyện lan man" in s

    finally:
        shutil.rmtree(user_dir, ignore_errors=True)
        with _get_db() as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (member_id,))
            conn.execute("DELETE FROM learnings WHERE user_id = ?", (member_id,))


def test_admin_user_management_and_deletion(tmp_path):
    # 1. Admin login
    res_adm = client.post("/api/auth/login", json={"username": "admin", "password": "admin-pass-123"})
    token_admin = res_adm.json()["token"]

    # 2. Member login to create a member user
    mem_name = f"user_{uuid.uuid4().hex[:6]}"
    res_mem = client.post("/api/auth/login", json={"username": mem_name})
    token_mem = res_mem.json()["token"]
    mem_id = res_mem.json()["user"]["id"]

    # Create dummy user folder and learning
    user_folder = Path(__file__).resolve().parents[1] / "data" / "users" / mem_id
    user_folder.mkdir(parents=True, exist_ok=True)
    (user_folder / "STYLE.md").write_text("- Test style.", encoding="utf-8")

    with _get_db() as conn:
        conn.execute("INSERT INTO learnings (user_id, content, type, created_at) VALUES (?, 'Test fact', 'preference', 1700000000)", (mem_id,))

    try:
        # 3. Member cannot access users list or delete
        res_forbidden = client.get("/api/users/list", headers={"Authorization": f"Bearer {token_mem}"})
        assert res_forbidden.status_code == 403

        res_del_forbidden = client.delete(f"/api/users/delete?id={mem_id}", headers={"Authorization": f"Bearer {token_mem}"})
        assert res_del_forbidden.status_code == 403

        # 4. Admin lists users
        res_list = client.get("/api/users/list", headers={"Authorization": f"Bearer {token_admin}"})
        assert res_list.status_code == 200
        users_list = res_list.json()["items"]
        assert any(u["id"] == mem_id for u in users_list)
        assert any(u["id"] == "admin" for u in users_list)

        # 5. Admin cannot delete admin
        res_del_admin = client.delete("/api/users/delete?id=admin", headers={"Authorization": f"Bearer {token_admin}"})
        assert res_del_admin.status_code == 400

        # 6. Admin deletes member
        res_del = client.delete(f"/api/users/delete?id={mem_id}", headers={"Authorization": f"Bearer {token_admin}"})
        assert res_del.status_code == 200
        assert res_del.json()["success"] is True

        # Verify DB and folder cleanup
        with _get_db() as conn:
            assert conn.execute("SELECT COUNT(*) FROM users WHERE id = ?", (mem_id,)).fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM learnings WHERE user_id = ?", (mem_id,)).fetchone()[0] == 0
        assert not user_folder.exists()

        # Admin lists users again -> member is gone
        res_list_after = client.get("/api/users/list", headers={"Authorization": f"Bearer {token_admin}"})
        assert not any(u["id"] == mem_id for u in res_list_after.json()["items"])
    finally:
        shutil.rmtree(user_folder, ignore_errors=True)

def test_delete_session_messages():
    # 1. Admin login
    res_adm = client.post("/api/auth/login", json={"username": "admin", "password": "admin-pass-123"})
    token_admin = res_adm.json()["token"]

    # 2. Member login
    res_mem = client.post("/api/auth/login", json={"username": f"user_{uuid.uuid4().hex[:6]}"})
    token_mem = res_mem.json()["token"]
    mem_id = res_mem.json()["user"]["id"]

    test_sid = f"web-test-{uuid.uuid4().hex[:6]}"
    try:
        from engine.core.memory import record_session_device, save_message, _get_db
        from engine.core.session_context import set_current_user_id
        
        # Save messages for admin & member in test_sid
        set_current_user_id("admin")
        save_message("user", "Admin message in test session", session_id=test_sid)
        
        set_current_user_id(mem_id)
        save_message("user", "Member message in test session", session_id=test_sid)

        # Verify messages exist
        with _get_db() as conn:
            c = conn.execute("SELECT COUNT(*) FROM messages WHERE session_id = ?", (test_sid,)).fetchone()[0]
            assert c == 2

        # Member deletes session -> should only delete member's message
        del_mem = client.delete(f"/api/conversations/session/{test_sid}", headers={"Authorization": f"Bearer {token_mem}"})
        assert del_mem.status_code == 200
        assert del_mem.json()["success"] is True

        with _get_db() as conn:
            # Member message gone, admin message remains
            rem = conn.execute("SELECT user_id FROM messages WHERE session_id = ?", (test_sid,)).fetchall()
            assert len(rem) == 1
            assert rem[0]["user_id"] == "admin"

        # Admin deletes session -> deletes all remaining messages in session
        del_adm = client.delete(f"/api/conversations/session/{test_sid}", headers={"Authorization": f"Bearer {token_admin}"})
        assert del_adm.status_code == 200
        assert del_adm.json()["success"] is True

        with _get_db() as conn:
            assert conn.execute("SELECT COUNT(*) FROM messages WHERE session_id = ?", (test_sid,)).fetchone()[0] == 0
    finally:
        with _get_db() as conn:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (test_sid,))
            conn.execute("DELETE FROM session_devices WHERE session_id = ?", (test_sid,))
            conn.commit()


def test_admin_update_user_and_permissions():
    # 1. Login admin & member
    res_adm = client.post("/api/auth/login", json={"username": "admin", "password": "admin-pass-123"})
    token_admin = res_adm.json()["token"]

    member_uname = f"member_{uuid.uuid4().hex[:6]}"
    res_mem = client.post("/api/auth/login", json={"username": member_uname})
    token_mem = res_mem.json()["token"]
    mem_id = res_mem.json()["user"]["id"]

    try:
        # 2. Member calls update -> 403 Forbidden
        res_forbidden = client.post(
            "/api/users/update",
            json={"id": mem_id, "values": {"display_name": "Hacked"}},
            headers={"Authorization": f"Bearer {token_mem}"},
        )
        assert res_forbidden.status_code == 403

        # 3. Admin calls with missing ID -> 400
        res_noid = client.post(
            "/api/users/update",
            json={"id": "", "values": {"display_name": "Test"}},
            headers={"Authorization": f"Bearer {token_admin}"},
        )
        assert res_noid.status_code == 400

        # 4. Admin tries to change root admin's username or role -> 400
        res_adm_rename = client.post(
            "/api/users/update",
            json={"id": "admin", "values": {"username": "superadmin"}},
            headers={"Authorization": f"Bearer {token_admin}"},
        )
        assert res_adm_rename.status_code == 400

        res_adm_demote = client.post(
            "/api/users/update",
            json={"id": "admin", "values": {"role": "member"}},
            headers={"Authorization": f"Bearer {token_admin}"},
        )
        assert res_adm_demote.status_code == 400

        # 5. Admin updates member profile
        new_uname = f"member_renamed_{uuid.uuid4().hex[:4]}"
        res_update = client.post(
            "/api/users/update",
            json={
                "id": mem_id,
                "values": {
                    "username": new_uname,
                    "display_name": "Nguyễn Văn A",
                    "user_pronoun": "anh",
                    "ai_pronoun": "em",
                    "role": "admin",
                    "tts_voice_id": "vi-VN-Standard-A",
                },
            },
            headers={"Authorization": f"Bearer {token_admin}"},
        )
        assert res_update.status_code == 200
        assert res_update.json()["success"] is True

        # Verify DB changes
        with _get_db() as conn:
            row = conn.execute(
                "SELECT username, display_name, user_pronoun, ai_pronoun, role, tts_voice_id FROM users WHERE id = ?",
                (mem_id,),
            ).fetchone()
            assert row is not None
            assert row["username"] == new_uname
            assert row["display_name"] == "Nguyễn Văn A"
            assert row["user_pronoun"] == "anh"
            assert row["ai_pronoun"] == "em"
            assert row["role"] == "admin"
            assert row["tts_voice_id"] == "vi-VN-Standard-A"

    finally:
        # Dọn dẹp sạch sẽ tài khoản test
        with _get_db() as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (mem_id,))
            conn.commit()
        shutil.rmtree(Path("data/users") / mem_id, ignore_errors=True)


def test_member_learning_api_ownership_permissions():
    # 1. Login admin & member
    res_adm = client.post("/api/auth/login", json={"username": "admin", "password": "admin-pass-123"})
    token_admin = res_adm.json()["token"]

    member_uname = f"member_{uuid.uuid4().hex[:6]}"
    res_mem = client.post("/api/auth/login", json={"username": member_uname})
    token_mem = res_mem.json()["token"]
    mem_id = res_mem.json()["user"]["id"]

    learning_engine = get_learning_engine()
    # Create learning for admin
    learning_engine._store_learning("Admin learning secret", "feedback_lesson", "adm_sec_1", user_id="admin")
    # Create learning for member
    learning_engine._store_learning("Member learning info", "feedback_lesson", "mem_info_1", user_id=mem_id)

    with _get_db() as conn:
        adm_row = conn.execute("SELECT id FROM learnings WHERE semantic_key = 'adm_sec_1'").fetchone()
        mem_row = conn.execute("SELECT id FROM learnings WHERE semantic_key = 'mem_info_1'").fetchone()
        adm_lid = adm_row["id"]
        mem_lid = mem_row["id"]

    try:
        # 2. Member tries to update Admin learning -> 403 Forbidden
        res_upd_forbidden = client.post(
            "/api/learnings/update",
            json={"id": adm_lid, "content": "Hacked content", "type_name": "feedback_lesson", "importance": 1},
            headers={"Authorization": f"Bearer {token_mem}"},
        )
        assert res_upd_forbidden.status_code == 403

        # 3. Member tries to delete Admin learning -> 403 Forbidden
        res_del_forbidden = client.delete(
            f"/api/learnings/delete?id={adm_lid}",
            headers={"Authorization": f"Bearer {token_mem}"},
        )
        assert res_del_forbidden.status_code == 403

        # 4. Member tries to update via /api/memory-control/update -> 403 Forbidden
        res_mc_upd_forbidden = client.post(
            "/api/memory-control/update",
            json={"kind": "learning", "id": adm_lid, "values": {"content": "Hacked mc"}},
            headers={"Authorization": f"Bearer {token_mem}"},
        )
        assert res_mc_upd_forbidden.status_code == 403

        # 5. Member tries to delete via /api/memory-control/delete -> 403 Forbidden
        res_mc_del_forbidden = client.post(
            "/api/memory-control/delete",
            json={"kind": "learning", "id": adm_lid},
            headers={"Authorization": f"Bearer {token_mem}"},
        )
        assert res_mc_del_forbidden.status_code == 403

        # 6. Member tries to update non-learning system kind (e.g. workflow) -> 403 Forbidden
        res_mc_wf_forbidden = client.post(
            "/api/memory-control/update",
            json={"kind": "workflow", "id": 1, "values": {"intent": "test"}},
            headers={"Authorization": f"Bearer {token_mem}"},
        )
        assert res_mc_wf_forbidden.status_code == 403

        # 7. Member tries to reembed all learnings -> 403 Forbidden
        res_reembed_all = client.post(
            "/api/learnings/reembed",
            json={"id": None},
            headers={"Authorization": f"Bearer {token_mem}"},
        )
        assert res_reembed_all.status_code == 403

        # 8. Member tries to reembed admin learning -> 403 Forbidden
        res_reembed_adm = client.post(
            "/api/learnings/reembed",
            json={"id": adm_lid},
            headers={"Authorization": f"Bearer {token_mem}"},
        )
        assert res_reembed_adm.status_code == 403

        # 9. Member updates own learning -> 200 OK
        res_upd_ok = client.post(
            "/api/learnings/update",
            json={"id": mem_lid, "content": "Updated member learning content", "type_name": "feedback_lesson", "importance": 2},
            headers={"Authorization": f"Bearer {token_mem}"},
        )
        assert res_upd_ok.status_code == 200
        assert res_upd_ok.json()["success"] is True

        # Verify DB updated
        with _get_db() as conn:
            check_mem = conn.execute("SELECT content FROM learnings WHERE id = ?", (mem_lid,)).fetchone()
            assert check_mem["content"] == "Updated member learning content"

        # 10. Member deletes own learning -> 200 OK
        res_del_ok = client.delete(
            f"/api/learnings/delete?id={mem_lid}",
            headers={"Authorization": f"Bearer {token_mem}"},
        )
        assert res_del_ok.status_code == 200
        assert res_del_ok.json()["success"] is True

        with _get_db() as conn:
            assert conn.execute("SELECT COUNT(*) FROM learnings WHERE id = ?", (mem_lid,)).fetchone()[0] == 0
            # Admin learning remains intact
            assert conn.execute("SELECT COUNT(*) FROM learnings WHERE id = ?", (adm_lid,)).fetchone()[0] == 1

    finally:
        with _get_db() as conn:
            conn.execute("DELETE FROM learnings WHERE id IN (?, ?)", (adm_lid, mem_lid))
            conn.execute("DELETE FROM users WHERE id = ?", (mem_id,))
            conn.commit()
        shutil.rmtree(Path("data/users") / mem_id, ignore_errors=True)
        get_learning_engine()._sync_learning_wiki()


def test_conversation_learning_and_evolution_user_isolation(monkeypatch):
    from engine.core.evolution import _evolution_path, _run_cognitive_evolution

    # 1. Create member
    member_uname = f"member_{uuid.uuid4().hex[:6]}"
    res_mem = client.post("/api/auth/login", json={"username": member_uname})
    mem_id = res_mem.json()["user"]["id"]

    try:
        # Check evolution paths
        mem_style_path = _evolution_path("style", mem_id)
        mem_log_path = _evolution_path("log", mem_id)
        adm_style_path = _evolution_path("style", "admin")

        assert str(mem_id) in str(mem_style_path)
        assert str(mem_id) in str(mem_log_path)
        assert "skills" in str(adm_style_path)

        # Store member learning
        learning_engine = get_learning_engine()
        learning_engine._store_learning("Tôn trọng quyền riêng tư của thành viên", "behaviour_lesson", "mem_priv_1", user_id=mem_id)
        learning_engine._sync_learning_wiki()

        # Verify file data/users/{mem_id}/Learning.md exists and contains the learning
        mem_learning_file = Path("data/users") / mem_id / "Learning.md"
        assert mem_learning_file.exists()
        assert "Tôn trọng quyền riêng tư của thành viên" in mem_learning_file.read_text(encoding="utf-8")

        # Mock LLM generation in evolution
        async def mock_ask(prompt: str, name: str, schema: dict) -> dict:
            if name == "evolution":
                return {"cleanup": []}
            return {"style": ["Tôn trọng quyền riêng tư của thành viên."]}

        import asyncio
        import engine.core.evolution as evo_module
        monkeypatch.setattr(evo_module, "_ask", mock_ask)

        # Run cognitive evolution for member
        res = asyncio.run(_run_cognitive_evolution(user_id=mem_id))
        assert res["success"] is True

        # Member style file should be created/updated
        assert mem_style_path.exists()
        content = mem_style_path.read_text(encoding="utf-8")
        assert "Tôn trọng quyền riêng tư của thành viên" in content

        # Admin style should NOT have been touched by member's evolution
        if adm_style_path.exists():
            adm_content = adm_style_path.read_text(encoding="utf-8")
            assert "Phong cách riêng của Member" not in adm_content

    finally:
        with _get_db() as conn:
            conn.execute("DELETE FROM learnings WHERE user_id = ?", (mem_id,))
            conn.execute("DELETE FROM users WHERE id = ?", (mem_id,))
            conn.commit()
        shutil.rmtree(Path("data/users") / mem_id, ignore_errors=True)
        get_learning_engine()._sync_learning_wiki()



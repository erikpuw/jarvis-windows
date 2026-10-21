"""_write_env_key không được để giá trị có xuống dòng chèn thêm khoá vào .env (review bảo mật 2026-10-13).

Một thiết bị LAN được phép gửi user_name = "x\\nJARVIS_SECURITY_LOCAL_ONLY=false" sẽ mở firewall sau khi restart.

Run: python -m pytest tests/test_env_write.py -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import server


@pytest.mark.parametrize("value", ["x\nJARVIS_SECURITY_LOCAL_ONLY=false", "x\rJARVIS_SECURITY_LOCAL_ONLY=false"])
def test_write_env_key_rejects_line_breaks(tmp_path, monkeypatch, value):
    env = tmp_path / ".env"
    env.write_text("USER_NAME=a\n", encoding="utf-8")
    monkeypatch.setattr(server, "_env_file_path", lambda: env)
    with pytest.raises(ValueError):
        server._write_env_key("USER_NAME", value)
    assert env.read_text(encoding="utf-8") == "USER_NAME=a\n"


def test_write_env_key_keeps_normal_value(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# c\nUSER_NAME=a\n", encoding="utf-8")
    monkeypatch.setattr(server, "_env_file_path", lambda: env)
    server._write_env_key("USER_NAME", "Anh Tuấn")
    assert env.read_text(encoding="utf-8") == "# c\nUSER_NAME=Anh Tuấn\n"

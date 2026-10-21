import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.server.ws_sessions import ActiveSessions


def test_latest_falls_back_to_older_tab_when_newest_closes():
    sessions = ActiveSessions()
    a, b = object(), object()
    sessions.add(a)
    sessions.add(b)
    assert sessions.latest is b
    assert len(sessions) == 2
    sessions.remove(b)
    assert sessions.latest is a
    sessions.remove(a)
    assert sessions.latest is None


def test_removing_twice_is_harmless():
    sessions = ActiveSessions()
    a = object()
    sessions.add(a)
    sessions.remove(a)
    sessions.remove(a)
    assert len(sessions) == 0

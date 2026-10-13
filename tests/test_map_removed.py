"""The map feature was removed on 2026-10-13 (rarely used): no map panel or MapLibre in the
WebUI, no pin storage on the server, no boundary GeoJSON pushed by the admin lookup tool.

Run: python -m pytest tests/test_map_removed.py -q
"""
from pathlib import Path

ROOT = Path(__file__).parent.parent


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_webui_has_no_map():
    assert 'id="map-panel"' not in read("frontend/index.html")
    assert 'id="btn-map"' not in read("frontend/index.html")
    main = read("frontend/src/main.ts")
    assert "maplibre" not in main.lower()
    assert "map_admin_boundary" not in main
    css = read("frontend/src/style.css")
    assert "#map-panel" not in css and "maplibregl" not in css


def test_server_has_no_pins():
    server = read("server.py")
    for t in ("save_pin", "delete_pin", "get_pins", "geolocation"):
        assert f'"{t}"' not in server
    memory = read("engine/core/memory.py")
    assert "pin_to_db" not in memory and "get_pins_from_db" not in memory


def test_admin_lookup_is_not_in_the_public_build():
    assert "handle_vietnam_data_query" not in read("engine/tools/search_engine.py")
    assert not (ROOT / "prompt" / "tools" / "vn_admin_lookup.md").exists()

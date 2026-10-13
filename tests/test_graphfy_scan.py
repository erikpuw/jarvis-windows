"""Graphfy map is generated from the code (AST imports), not hand-drawn.

Run: python -m pytest tests/test_graphfy_scan.py -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from engine.UIUX.graphfy import scan


def _tree(tmp_path, files: dict[str, str]):
    for rel, src in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src, encoding="utf-8")
    return tmp_path


def test_packages_merge_but_core_and_server_split_per_file(tmp_path):
    root = _tree(tmp_path, {
        "server.py": "from engine.router import handle_turn\n",
        "engine/__init__.py": "",
        "engine/router/__init__.py": "from .decide import decide\n",
        "engine/router/decide.py": "from engine.core import memory\nimport engine.core.learning as l\n",
        "engine/core/__init__.py": "",
        "engine/core/memory.py": "",
        "engine/core/learning.py": "def f():\n    from engine.server.llm_server import call_llm\n",
        "engine/server/__init__.py": "",
        "engine/server/llm_server.py": "",
        "engine/core/lonely.py": "",
    })
    g = scan(root)
    ids = {n["id"] for n in g["nodes"]}
    assert {"server", "router", "core/memory", "core/learning", "server/llm_server"} <= ids
    assert "router/decide" not in ids, "non-split packages are one node"
    assert "core/lonely" not in ids, "nodes without edges are dropped"
    edges = {(e["from"], e["to"], e["kind"]) for e in g["edges"]}
    assert ("server", "router", "import") in edges
    assert ("router", "core/memory", "import") in edges, "from pkg import module resolves to the module"
    assert ("router", "core/learning", "import") in edges
    assert ("core/learning", "server/llm_server", "llm") in edges, "imports inside functions count; LLM edges are marked"
    assert not any(a == b for a, b, _ in edges), "no self loops (router/__init__ -> router/decide)"


def test_lanes_and_unknown_modules(tmp_path):
    root = _tree(tmp_path, {
        "engine/__init__.py": "",
        "engine/core/__init__.py": "",
        "engine/core/dream.py": "from engine.server.llm_server import call_llm\n",
        "engine/server/__init__.py": "",
        "engine/server/llm_server.py": "",
        "engine/newpkg/__init__.py": "from engine.core import dream\n",
    })
    lanes = {n["id"]: n["lane"] for n in scan(root)["nodes"]}
    assert lanes["core/dream"] == "background"
    assert lanes["server/llm_server"] == "llm"
    assert lanes["newpkg"] == "other", "a new module shows up by itself, in 'other' until given a lane"


def test_real_repo_map_is_readable():
    g = scan(Path(__file__).parent.parent)
    ids = {n["id"] for n in g["nodes"]}
    assert {"turn", "tools", "server/llm_server", "core/dream"} <= ids
    assert 10 <= len(g["nodes"]) <= 60, len(g["nodes"])
    llm_callers = {e["from"] for e in g["edges"] if e["kind"] == "llm"}
    assert {"turn"} <= llm_callers, llm_callers


def test_api_graphfy_serves_the_repo_map():
    import asyncio
    from engine.UIUX import ui_engine
    res = asyncio.run(ui_engine.api_graphfy())
    assert res["success"] is True and len(res["nodes"]) >= 15 and res["edges"]

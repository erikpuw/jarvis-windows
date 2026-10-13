"""Graphfy: the JARVIS structure map, generated from the code instead of drawn by hand.

One node per package under engine/, except the grab-bag packages (core, server)
which get one node per file. An edge A -> B means a module of A imports B
(anywhere, including inside functions). Imports of the LLM client are marked
kind="llm" so the map shows every place that calls the model. New modules show
up by themselves in lane "other" until LANES gives them a home.
"""
from __future__ import annotations

import ast
from pathlib import Path

SPLIT = {"core", "server"}
LLM_NODE = "server/llm_server"

# node id (or package) -> lane; the only hand-kept part of the map
LANES = {
    "server": "input", "server/telegram_bot": "input", "server/slash_commands": "input",
    "server/whisper_server": "input", "security": "input", "UIUX": "input",
    "router": "turn", "tools": "turn",
    "prompts": "turn", "main": "turn",
    "server/mcp_server": "turn", "core/guardrails": "input",
    LLM_NODE: "llm",
    "server/voice_streamer": "output", "server/tts_manager": "output",
    "server/stream_tts": "output", "server/tts_engine": "output",
    "core/memory": "memory", "core/learning": "memory", "core/memory_tree": "memory",
    "core/evolution": "memory",
    "core/rag_engine": "ingestion", "core/rag_watcher": "ingestion", "chunking": "ingestion",
    "core/dream": "background", "core/self_healing": "background",
    "core/attachment_store": "input", "server/ws_dispatcher": "input",
    "core/mcp_context": "turn",
    "server/text_streamer": "output", "server/tts_server": "output", "server/vieneu_tts": "output",
    "core/wiki_sync": "memory", "core/evolution_parser": "memory",
    "core/rag_document_store": "ingestion", "core/rag_pdf_ingest": "ingestion",
    # shared helpers: drawn dimmed so they do not bury the real flows
    "core/json_parser": "support", "core/trace_logger": "support", "core/activity_gate": "support",
    "core/process_tree": "support", "server/redis_server": "support",
}


def _node_of_module(mod: str) -> str | None:
    parts = mod.split(".")
    if parts[0] == "server" and len(parts) == 1:
        return "server"
    if parts[0] != "engine" or len(parts) < 2:
        return None
    pkg = parts[1]
    if pkg in SPLIT:
        return f"{pkg}/{parts[2]}" if len(parts) > 2 else None
    return pkg


def _module_name(root: Path, path: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(tree: ast.AST, mod: str, is_pkg: bool, known: set[str]) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom):
            base = n.module or ""
            if n.level:
                pkg = mod.split(".") if is_pkg else mod.split(".")[:-1]
                pkg = pkg[: len(pkg) - (n.level - 1)]
                base = ".".join(pkg + ([base] if base else []))
            for a in n.names:  # "from engine.core import memory" -> engine.core.memory
                sub = f"{base}.{a.name}"
                out.add(sub if sub in known else base)
    return out


def scan(root: Path) -> dict:
    root = Path(root)
    files = [root / "server.py"] if (root / "server.py").exists() else []
    files += [p for p in (root / "engine").rglob("*.py") if "__pycache__" not in p.parts]
    known = {_module_name(root, p) for p in files}

    edges: set[tuple[str, str, str]] = set()
    for path in files:
        mod = _module_name(root, path)
        src_node = _node_of_module(mod)
        if not src_node:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for imp in _imports(tree, mod, path.name == "__init__.py", known):
            dst = _node_of_module(imp)
            if dst and dst != src_node:
                edges.add((src_node, dst, "llm" if dst == LLM_NODE else "import"))

    used = {a for a, _, _ in edges} | {b for _, b, _ in edges}
    nodes = [{"id": n, "label": n.split("/")[-1], "lane": LANES.get(n, "other")} for n in sorted(used)]
    return {"nodes": nodes, "edges": [{"from": a, "to": b, "kind": k} for a, b, k in sorted(edges)]}

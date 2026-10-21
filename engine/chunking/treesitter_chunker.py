"""
engine/chunking/treesitter_chunker.py — AST-based code chunker
=========================================================
Uses tree-sitter to split files into function/class-level chunks.
Falls back to file-level chunking for unsupported languages or if libraries are missing.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import os
import uuid

# ── Token counting ────────────────────────────────────────────────────────────
try:
    import tiktoken as _tiktoken
    _ENCODER = _tiktoken.get_encoding("cl100k_base")
    _HAS_TIKTOKEN = True
except Exception:
    _HAS_TIKTOKEN = False
    _ENCODER = None


def count_tokens(text: str) -> int:
    """Count tokens in text. Falls back to len/3.5 heuristic if tiktoken is unavailable."""
    if not text:
        return 0
    if _HAS_TIKTOKEN and _ENCODER is not None:
        return len(_ENCODER.encode(text, disallowed_special=()))
    return max(1, int(len(text) / 3.5))


# ── Chunk dataclass ───────────────────────────────────────────────────────────
@dataclass
class Chunk:
    id: str
    path: str
    type: str
    symbol: str
    content: str
    summary: str
    tokens: int
    embedding: list[float] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    priority: int = 5


# ── AST Chunker ───────────────────────────────────────────────────────────────
class ASTChunker:
    def __init__(self):
        try:
            import tree_sitter_python
            import tree_sitter_javascript
            import tree_sitter_typescript
            import tree_sitter
            self.ts = tree_sitter
            self.lang_py = tree_sitter.Language(tree_sitter_python.language())
            self.lang_js = tree_sitter.Language(tree_sitter_javascript.language())
            self.lang_ts = tree_sitter.Language(tree_sitter_typescript.language_typescript())
        except ImportError:
            self.ts = None

    def get_parser(self, ext: str):
        if not self.ts:
            return None
        parser = self.ts.Parser()
        if ext == ".py":
            parser.language = self.lang_py
        elif ext in [".js", ".jsx"]:
            parser.language = self.lang_js
        elif ext in [".ts", ".tsx"]:
            parser.language = self.lang_ts
        else:
            return None
        return parser

    def chunk_paths(self, paths: list[str]) -> list[Chunk]:
        chunks = []
        for path in paths:
            if not os.path.exists(path):
                continue
            if os.path.isdir(path):
                for root, _, files in os.walk(path):
                    for file in files:
                        filepath = os.path.join(root, file)
                        chunks.extend(self._chunk_file(filepath))
            else:
                chunks.extend(self._chunk_file(path))
        return chunks

    def _chunk_file(self, filepath: str) -> list[Chunk]:
        chunks = []
        ext = os.path.splitext(filepath)[1]
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            return []

        parser = self.get_parser(ext)
        if parser is None:
            # Fallback to file-level chunk
            return [
                Chunk(
                    id=str(uuid.uuid4()),
                    path=filepath,
                    type="file",
                    symbol="module",
                    content=content,
                    summary="",
                    tokens=count_tokens(content),
                )
            ]

        tree = parser.parse(bytes(content, "utf8"))
        root_node = tree.root_node
        content_bytes = bytes(content, "utf8")

        def traverse(node):
            if node.type in [
                "class_definition",
                "function_definition",
                "class_declaration",
                "function_declaration",
                "method_definition",
            ]:
                chunk_content = content_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")
                symbol_name = "unknown"
                for child in node.children:
                    if child.type == "identifier":
                        symbol_name = content_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="ignore")
                        break

                chunks.append(Chunk(
                    id=str(uuid.uuid4()),
                    path=filepath,
                    type=node.type,
                    symbol=symbol_name,
                    content=chunk_content,
                    summary=f"{node.type} {symbol_name}",
                    tokens=count_tokens(chunk_content),
                ))
            for child in node.children:
                traverse(child)

        traverse(root_node)

        # If no chunks extracted, add file as a module chunk
        if not chunks:
            chunks.append(Chunk(
                id=str(uuid.uuid4()),
                path=filepath,
                type="module",
                symbol="module",
                content=content,
                summary="",
                tokens=count_tokens(content),
            ))

        return chunks

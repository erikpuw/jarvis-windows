import os
import json
import logging
import asyncio
from pathlib import Path
from typing import Optional, Any, List, Dict
from collections import Counter

import numpy as np
from turbovec import IdMapIndex
from rank_bm25 import BM25Okapi

import re
import unicodedata

log = logging.getLogger("jarvis.rag_engine")

PROJECT_ROOT = Path(__file__).parent.parent.parent
RAG_DATA_DIR = PROJECT_ROOT / "data" / "rag_index"
RAG_DATA_DIR.mkdir(parents=True, exist_ok=True)

INDEX_FILE_PATH = RAG_DATA_DIR / "rag_vectors.tq"
METADATA_FILE_PATH = RAG_DATA_DIR / "rag_metadata.json"


def clean_document_text(text: str) -> str:
    """Lọc và chuẩn hóa ký tự lỗi trong tài liệu (null bytes, control chars, broken dashes)."""
    if not text:
        return ""
    # 1. Thay thế null byte \x00 giữa 2 chữ/số thành dấu gạch nối '-'
    text = re.sub(r'(?<=\w)\x00(?=\w)', '-', text)
    text = text.replace('\x00', ' ')

    # 2. Xóa các ký tự điều khiển ASCII vô hiệu (giữ lại \t, \n, \r)
    text = re.sub(r'[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]', ' ', text)

    # 3. Chuẩn hóa khoảng trắng đặc biệt & zero-width
    text = re.sub(r'[\u200b\u200c\u200d\ufeff]', '', text)
    text = text.replace('\u00a0', ' ')

    # 4. Loại bỏ lone surrogate code points
    text = text.encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')

    # 5. Dọn dẹp khoảng trắng thừa nhưng giữ dòng
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)

    return unicodedata.normalize("NFC", text.strip())

class RAGEngine:
    """HyperRAG Engine combining turbovec Dense Search, BM25 Sparse Search and RRF Fusion."""
    def __init__(self, dim: int = 768, persistent: bool = True):
        self.dim = dim
        self.persistent = persistent
        self.openai_client: Optional[Any] = None
        self.embed_client: Optional[Any] = None
        self.chunks: List[Dict[str, Any]] = []
        self.vector_index: Optional[IdMapIndex] = None
        self.bm25_index: Optional[BM25Okapi] = None
        self.enabled = False
        self._needs_rebuild = False
        # Guards _rebuild_vector_index() so concurrent callers (e.g. two
        # status endpoints hit around the same time) never run it in
        # parallel against the same self.vector_index - that raced and
        # threw "id already present in index" from add_with_ids.
        self._rebuild_lock = asyncio.Lock()
        # Monotonic chunk id counter, independent of self.chunks' list
        # position — lets remove_document()/sync_lifecycle() delete
        # individual ids from the turbovec index (IdMapIndex.remove) without
        # renumbering (and re-embedding) every remaining chunk.
        self._next_id: Optional[int] = None
        if persistent:
            self._load_index()
        else:
            self.vector_index = IdMapIndex(dim=self.dim, bit_width=4)
        self._ensure_next_id()

    def set_client(self, client: Any):
        """Set the main LLM client."""
        self.openai_client = client

    def set_embed_client(self, client: Any):
        """Set the embedding client."""
        self.embed_client = client

    def _ensure_next_id(self):
        """Derive next_id from the chunks when metadata doesn't carry it.

        Metadata written before ids became stable has no `next_id`, which left
        `self._next_id` as None and made the next `self._next_id += 1` raise
        TypeError. Every path that loads metadata must run this.
        """
        if self._next_id is None:
            self._next_id = (
                max((c.get("id", -1) for c in self.chunks), default=-1) + 1
            ) if self.chunks else 0

    def _load_index(self):
        """Load index from persistent storage if exists."""
        try:
            if METADATA_FILE_PATH.exists():
                with open(METADATA_FILE_PATH, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    self.chunks = meta.get("chunks", [])
                    self.dim = meta.get("dim", self.dim)
                    self._next_id = meta.get("next_id")
                    for c in self.chunks:
                        content = c.get("content", "")
                        if "\x00" in content:
                            c["content"] = clean_document_text(content)
        except Exception as e:
            log.error(f"Failed to load RAG metadata: {e}", exc_info=True)
            self.chunks = []

        try:
            if INDEX_FILE_PATH.exists() and self.chunks:
                # Load the turbovec Index
                self.vector_index = IdMapIndex.load(str(INDEX_FILE_PATH))
                log.info(f"Loaded existing vector index with {len(self.chunks)} chunks")
                self.enabled = True
            else:
                # Initialize new Index with 4-bit compression
                self.vector_index = IdMapIndex(dim=self.dim, bit_width=4)
                log.info("Initialized new turbovec 4-bit index")
        except Exception as e:
            # Vector index file is unreadable (e.g. incompatible turbovec format
            # after a library upgrade). Keep the chunk metadata - it's still valid -
            # and rebuild the vector index by re-embedding once an embed client is set.
            log.error(f"Failed to load vector index, will rebuild from chunks: {e}", exc_info=True)
            self.vector_index = IdMapIndex(dim=self.dim, bit_width=4)
            self._needs_rebuild = bool(self.chunks)
            self.enabled = bool(self.chunks)

        self._ensure_next_id()
        self._rebuild_bm25()

    def _save_index(self):
        """Save vector and metadata index to disk.

        Blocking disk I/O — every caller must run this via
        `asyncio.to_thread` so a large index write never stalls the shared
        event loop (and the live voice WebSocket) for its duration.
        """
        try:
            # Save vector index
            if self.vector_index is not None and len(self.chunks) > 0:
                self.vector_index.write(str(INDEX_FILE_PATH))

            # Save metadata atomically: write to a temp file in the same
            # directory then os.replace it in. A crash mid-write with a plain
            # open()/json.dump() would corrupt rag_metadata.json, and
            # _load_index() silently resets self.chunks = [] on a bad read —
            # wiping the whole RAG knowledge base while the paired vector
            # index file may still reference the now-orphaned chunk ids.
            meta = {
                "dim": self.dim,
                "chunks": self.chunks,
                "next_id": self._next_id,
            }
            tmp_path = METADATA_FILE_PATH.with_suffix(".json.tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            os.replace(str(tmp_path), str(METADATA_FILE_PATH))

            log.info(f"Saved RAG index with {len(self.chunks)} chunks to disk")
        except Exception as e:
            log.error(f"Failed to save RAG index: {e}", exc_info=True)

    def _rebuild_bm25(self):
        """Build/rebuild the BM25 index from current chunks."""
        if not self.chunks:
            self.bm25_index = None
            return
            
        corpus = [c["content"].lower().split() for c in self.chunks]
        self.bm25_index = BM25Okapi(corpus)
        log.info("Rebuilt BM25 index")

    def _chunk_text(self, text: str, chunk_size: int = 800, overlap: int = 150) -> List[str]:
        """Simple character-based chunking with overlap."""
        chunks = []
        if not text:
            return chunks
            
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunks.append(text[start:end])
            start += chunk_size - overlap
            
        return chunks

    async def _get_embedding(self, text: str) -> List[float]:
        """Fetch embedding from client."""
        if self.embed_client is None:
            raise ValueError("Embedding client not set. Call set_embed_client first.")
            
        model = os.getenv("LOCAL_EMBED_MODEL")
        
        # Run synchronous call in thread pool to prevent blocking the async loop
        embed_timeout = float(os.getenv("LOCAL_EMBED_TIMEOUT_SECONDS", "30"))
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self.embed_client.embeddings.create(input=[text], model=model, timeout=embed_timeout)
        )
        embedding = response.data[0].embedding

        # Adjust embedding dimension if mismatched - but only when the current
        # vector_index is still empty. _rebuild_vector_index() intentionally
        # points self.vector_index at a fresh empty index while self.chunks
        # still holds the metadata to re-embed, so an empty vector_index is
        # the correct "safe to adapt" signal - not an empty self.chunks.
        # Once the vector_index already holds live entries (from earlier
        # documents, or from earlier chunks already added this same
        # process_document() loop), swapping in a fresh empty vector_index
        # would silently orphan those vectors while their metadata survives
        # in self.chunks.
        if len(embedding) != self.dim:
            if self.vector_index is not None and len(self.vector_index) > 0:
                raise RuntimeError(
                    f"Embedding dimension changed from {self.dim} to {len(embedding)} "
                    f"while the vector index already holds {len(self.vector_index)} "
                    "entries at the old dimension. Refusing to reset the vector index "
                    "- that would orphan the existing entries. Re-index explicitly if "
                    "the embedding model was intentionally changed."
                )
            log.warning(f"Embedding dimension mismatch: got {len(embedding)}, expected {self.dim}. Adjusting engine.")
            self.dim = len(embedding)
            self.vector_index = IdMapIndex(dim=self.dim, bit_width=4)
            # Refit/re-initialize vector index with new dim (will be populated on next index)

        return embedding

    async def _ensure_vector_index_ready(self):
        """Rebuild the vector index from chunk metadata if a previous load failed."""
        if not (self._needs_rebuild and self.embed_client is not None):
            return
        async with self._rebuild_lock:
            # Re-check: another caller may have already rebuilt (or be
            # rebuilding) while we were waiting for the lock.
            if not (self._needs_rebuild and self.embed_client is not None):
                return
            log.info(f"Rebuilding vector index from {len(self.chunks)} chunks after load failure")
            self._needs_rebuild = not await self._rebuild_vector_index()

    async def try_self_heal(self, embed_client: Optional[Any] = None):
        """Attach an embed client if this instance doesn't have one yet, then rebuild
        the vector index on disk if a previous load left it stale (e.g. an incompatible
        turbovec format from a library upgrade). Safe to call repeatedly/from status
        endpoints - it's a no-op once the index is healthy."""
        if embed_client is not None and self.embed_client is None:
            self.embed_client = embed_client
        await self._ensure_vector_index_ready()

    async def process_document(self, file_path: str) -> Dict[str, Any]:
        """Process and index a document into the RAG engine."""
        path = Path(file_path)
        if not path.exists():
            return {"success": False, "error": f"File {file_path} does not exist."}

        # RAGFolderWatcher guards against re-indexing an unchanged file via
        # rag_watch.db, but that guard doesn't exist for any other caller -
        # a retry or a duplicate call here used to append a second full set
        # of chunks for the same file every time. Mirrors the document_id
        # dedup already done in index_prepared_pages().
        resolved_path = str(path.resolve())
        if any(c.get("file_path") == resolved_path for c in self.chunks):
            return {"success": True, "chunks": 0, "reused": True}

        try:
            content = ""
            if not content:
                supported_extensions = {".docx", ".pptx", ".xlsx", ".pdf", ".html", ".htm", ".zip"}
                if path.suffix.lower() in supported_extensions:
                    try:
                        from markitdown import MarkItDown
                        
                        vision_api_key = os.getenv("VISION_API_KEY") or os.getenv("LOCAL_API_KEY") or "dummy"
                        vision_url = os.getenv("VISION_URL") or os.getenv("LOCAL_URL")
                        from engine.server.llm_server import vision_model_name
                        vision_model = vision_model_name()
                        
                        md_args = {}
                        if vision_url:
                            from openai import OpenAI
                            vision_client = OpenAI(api_key=vision_api_key, base_url=vision_url)
                            md_args["enable_plugins"] = True
                            md_args["llm_client"] = vision_client
                            md_args["llm_model"] = vision_model
                            
                        md = MarkItDown(**md_args)
                        result = md.convert(str(path))
                        content = result.text_content
                    except Exception as me:
                        log.warning(f"MarkItDown failed to convert {path.name}: {me}. Falling back to basic text reader.")
                        content = path.read_text(encoding="utf-8", errors="ignore")
                elif path.suffix.lower() in {".txt", ".md", ".csv", ".json"}:
                    content = path.read_text(encoding="utf-8", errors="ignore")
                else:
                    content = path.read_text(encoding="utf-8", errors="ignore")
                    
            # Dọn dẹp toàn bộ dữ liệu ảnh Base64 nhúng để tránh tràn token embedding
            content = re.sub(r'!\[.*?\]\(data:image\/.*?;base64,[\s\S]*?\)', '', content)
            content = re.sub(r'data:image\/[a-zA-Z]*;base64,[a-zA-Z0-9+/=\s\n\r]*', '', content)
            content = clean_document_text(content)
            
            if not content or not content.strip():
                return {"success": False, "error": "Document content is empty."}

                
            # 1. Chunking
            # Chỉ dùng ASTChunker cho các file mã nguồn code
            source_code_extensions = {".py", ".js", ".ts", ".go", ".java", ".cpp", ".c", ".h", ".cs", ".rs", ".php", ".rb"}
            text_chunks = []
            if path.suffix.lower() in source_code_extensions:
                try:
                    from engine.chunking.treesitter_chunker import ASTChunker
                    chunker = ASTChunker()
                    extracted_chunks = chunker.chunk_paths([str(path)])
                    text_chunks = [c.content for c in extracted_chunks]
                except Exception as e:
                    log.warning(f"AST Chunker failed, falling back to char-based chunking: {e}")
                    
            if not text_chunks:
                text_chunks = self._chunk_text(content)
                
            if not text_chunks:
                return {"success": False, "error": "No chunks generated."}

            await self._ensure_vector_index_ready()

            # 2. Get embeddings & add to indexes
            new_chunks_count = 0

            for doc_index, chunk_text in enumerate(text_chunks):
                chunk_id = self._next_id
                self._next_id += 1

                # Fetch embedding
                embedding = await self._get_embedding(chunk_text)
                
                # Add to turbovec
                embedding_np = np.array([embedding], dtype=np.float32)
                self.vector_index.add_with_ids(embedding_np, np.array([chunk_id], dtype=np.uint64))
                
                # Add to metadata database
                self.chunks.append({
                    "id": chunk_id,
                    "doc_index": doc_index,
                    "file_path": str(path.resolve()),
                    "filename": path.name,
                    "content": chunk_text,
                    "token_est": self._estimate_tokens(chunk_text),
                })
                new_chunks_count += 1
                
            # 3. Save persistent indexes only for the shared RAG workflow.
            if self.persistent:
                await asyncio.to_thread(self._save_index)
            self._rebuild_bm25()
            
            self.enabled = True
            return {
                "success": True,
                "chunks": new_chunks_count,
                "message": f"Successfully indexed {new_chunks_count} chunks from {path.name}"
            }
            
        except Exception as e:
            log.error(f"Error processing document {file_path}: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def index_prepared_pages(
        self,
        document_id: str,
        source_filename: str,
        page_paths: List[Path],
        page_methods: Dict[int, str],
    ) -> Dict[str, Any]:
        """Index page-scoped Markdown prepared by the upload RAG workflow."""
        if any(
            chunk.get("document_id") == document_id
            for chunk in self.chunks
        ):
            return {
                "success": True,
                "chunks": 0,
                "reused": True,
            }
        if not page_paths:
            return {
                "success": False,
                "error": "No prepared Markdown pages found.",
            }

        original_count = len(self.chunks)
        added = 0
        try:
            await self._ensure_vector_index_ready()
            for page_path in sorted(Path(path) for path in page_paths):
                page_number = int(page_path.stem.rsplit("-", 1)[1])
                markdown = clean_document_text(page_path.read_text(encoding="utf-8"))
                for chunk_text in self._chunk_text(markdown):
                    embedding = await self._get_embedding(chunk_text)
                    chunk_id = self._next_id
                    self._next_id += 1
                    self.vector_index.add_with_ids(
                        np.array([embedding], dtype=np.float32),
                        np.array([chunk_id], dtype=np.uint64),
                    )
                    self.chunks.append({
                        "id": chunk_id,
                        "doc_index": added,
                        "document_id": document_id,
                        "file_path": str(page_path.resolve()),
                        "filename": source_filename,
                        "page_number": page_number,
                        "conversion_method": page_methods.get(
                            page_number,
                            "unknown",
                        ),
                        "content": chunk_text,
                        "token_est": self._estimate_tokens(chunk_text),
                    })
                    added += 1

            if self.persistent:
                await asyncio.to_thread(self._save_index)
            self._rebuild_bm25()
            self.enabled = bool(self.chunks)
            return {
                "success": True,
                "chunks": added,
                "reused": False,
            }
        except Exception as exc:
            self.chunks = self.chunks[:original_count]
            if self.persistent:
                self._load_index()
            elif original_count == 0:
                self.vector_index = IdMapIndex(
                    dim=self.dim,
                    bit_width=4,
                )
            self._rebuild_bm25()
            log.error(
                "Failed to index prepared RAG pages: %s",
                exc,
                exc_info=True,
            )
            return {"success": False, "error": str(exc)}

    def _estimate_tokens(self, text: str) -> int:
        """Ước lượng token (~3 ký tự/token)."""
        if not text:
            return 0
        return max(1, len(text) // 3)

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        max_tokens: int = 0,
        rerank_pool: int = 50,
        min_score: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """
        HyperRAG retrieval: TurboVec dense → BM25 sparse → RRF fusion → rerank → budget trim.

        Args:
            query: User query string.
            top_k: Số chunk trả về sau rerank.
            max_tokens: Nếu >0, trim chunks để tổng token ≤ max_tokens.
            rerank_pool: Pool size trước rerank (lớn hơn giúp rerank có nhiều ứng viên).
        """
        if not self.chunks:
            return []

        try:
            await self._ensure_vector_index_ready()

            # ── 1. DENSE VECTOR SEARCH ──
            query_embedding = await self._get_embedding(query)
            query_np = np.array([query_embedding], dtype=np.float32)

            search_k = min(len(self.chunks), rerank_pool)
            dense_scores, dense_indices = self.vector_index.search(query_np, k=search_k)

            dense_results = []
            if len(dense_indices) > 0 and len(dense_indices[0]) > 0:
                for idx, score in zip(dense_indices[0], dense_scores[0]):
                    if idx != -1:
                        dense_results.append(int(idx))

            # ── 2. SPARSE KEYWORD SEARCH (BM25) ──
            sparse_results = []
            tokenized_query = query.lower().split()
            q_word_counts = Counter(tokenized_query)

            if self.bm25_index is not None:
                bm25_scores = self.bm25_index.get_scores(tokenized_query)
                sorted_indices = np.argsort(bm25_scores)[::-1]
                # sorted_indices are positions in the BM25 corpus (built
                # positionally from self.chunks), not chunk["id"] — chunk ids
                # are stable across removals and no longer equal list
                # position, so translate through self.chunks here.
                for pos in sorted_indices[:search_k]:
                    if bm25_scores[pos] > 0:
                        sparse_results.append(int(self.chunks[pos]["id"]))

            # ── 3. RECIPROCAL RANK FUSION (RRF) ──
            k_rrf = 60.0
            rrf_scores: Dict[int, float] = {}

            for rank, chunk_id in enumerate(dense_results):
                rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + (1.0 / (k_rrf + rank))

            for rank, chunk_id in enumerate(sparse_results):
                rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + (1.0 / (k_rrf + rank))

            sorted_rrf = sorted(rrf_scores.items(), key=lambda item: item[1], reverse=True)

            # ── 4. MULTI-SIGNAL RERANKER ──
            q_words = set(q_word_counts.keys())
            q_len = len(q_words)

            chunks_by_id = {c["id"]: c for c in self.chunks}
            reranked_results = []
            for chunk_id, rrf_score in sorted_rrf[:rerank_pool]:
                chunk_entry = chunks_by_id.get(chunk_id)
                if chunk_entry is None:
                    continue
                chunk_meta = chunk_entry.copy()
                content = chunk_meta["content"]
                content_lower = content.lower()
                c_words = content_lower.split()
                c_word_set = set(c_words)

                # Signal 1: Query term coverage (% query words xuất hiện trong chunk)
                coverage = len(q_words.intersection(c_word_set)) / max(q_len, 1)

                # Signal 2: Keyword density (tần suất query words / total words)
                c_word_counts = Counter(c_words)
                density = sum(c_word_counts.get(w, 0) for w in q_words) / max(len(c_words), 1)

                # Signal 3: Position bias (chunk đầu tài liệu có score nhẹ).
                # Uses the chunk's position inside its own document. This read
                # chunk_id back when ids were list positions; once ids became
                # stable and monotonic, every chunk past the first 100 ever
                # indexed scored a flat 0.5 and the signal was dead. Chunks
                # without the field (pre-doc_index metadata) get the midpoint.
                pos_bonus = 1.0 - min(chunk_meta.get("doc_index", 50), 100) / 200.0

                # Signal 4: Length normalization
                token_est = self._estimate_tokens(content)
                if token_est < 15 or token_est > 600:
                    len_penalty = 0.5
                elif token_est < 30:
                    len_penalty = 0.8
                else:
                    len_penalty = 1.0

                # Hybrid score: RRF 45% + coverage 25% + density 15% + position 10% + length 5%
                hybrid_score = (
                    rrf_score * 0.45
                    + coverage * 0.25
                    + density * 0.15
                    + pos_bonus * 0.10
                    + len_penalty * 0.05
                )

                chunk_meta["rrf_score"] = rrf_score
                chunk_meta["hybrid_score"] = round(hybrid_score, 4)
                chunk_meta["coverage"] = round(coverage, 3)
                chunk_meta["token_est"] = token_est
                reranked_results.append(chunk_meta)

            reranked_results.sort(key=lambda x: x["hybrid_score"], reverse=True)
            if min_score > 0:
                reranked_results = [r for r in reranked_results if r["hybrid_score"] >= min_score]

            # ── 5. TOKEN BUDGET TRIM ──
            if max_tokens > 0:
                trimmed = []
                used = 0
                for cm in reranked_results:
                    needed = cm["token_est"]
                    if used + needed <= max_tokens:
                        trimmed.append(cm)
                        used += needed
                    else:
                        # Thử thêm chunk nhỏ hơn nếu còn slot
                        if needed <= max_tokens // 2 and used + needed <= max_tokens * 1.1:
                            trimmed.append(cm)
                            used += needed
                        break
                reranked_results = trimmed[:top_k]
            else:
                reranked_results = reranked_results[:top_k]

            return reranked_results

        except Exception as e:
            log.error(f"Error during RAG retrieval: {e}", exc_info=True)
            return []

    def get_indexed_files(self) -> list:
        """Trả về danh sách các file đã được index (duy nhất theo file_path)."""
        seen = {}
        for chunk in self.chunks:
            fp = chunk.get("file_path", "")
            fn = chunk.get("filename", "")
            if fp and fp not in seen:
                seen[fp] = {"file_path": fp, "filename": fn, "chunks": 0}
            if fp in seen:
                seen[fp]["chunks"] += 1
        return list(seen.values())

    async def _rebuild_vector_index(self) -> bool:
        """Rebuild the turbovec vector index from scratch using self.chunks.

        Returns False (and persists nothing) if any chunk failed to
        re-embed - e.g. the embedding backend is unreachable - so the
        caller keeps retrying later instead of saving a partially-empty
        index and never trying again.
        """
        self.vector_index = IdMapIndex(dim=self.dim, bit_width=4)
        if not self.chunks:
            self.enabled = False
            if self.persistent:
                await asyncio.to_thread(self._save_index)
            self._rebuild_bm25()
            return True

        failed = 0
        max_attempts = 3
        for i, chunk in enumerate(self.chunks):
            chunk["id"] = i
            for attempt in range(1, max_attempts + 1):
                try:
                    embedding = await self._get_embedding(chunk["content"])
                    embedding_np = np.array([embedding], dtype=np.float32)
                    self.vector_index.add_with_ids(embedding_np, np.array([i], dtype=np.uint64))
                    break
                except Exception as e:
                    if attempt == max_attempts:
                        failed += 1
                        log.warning(f"Failed to re-embed chunk {i} during index rebuild after {max_attempts} attempts: {e}")
                    else:
                        await asyncio.sleep(1.0)

        # Ids were just renumbered to 0..len(chunks)-1 above; resume
        # allocation past the highest one in use so future adds never
        # collide with them.
        self._next_id = len(self.chunks)

        if failed > 0:
            log.error(
                f"Vector index rebuild incomplete: {failed}/{len(self.chunks)} chunks "
                "failed to re-embed (embedding backend unreachable?); not persisting, will retry later"
            )
            return False

        if self.persistent:
            await asyncio.to_thread(self._save_index)
        self._rebuild_bm25()
        self.enabled = bool(self.chunks)
        return True

    def _remove_chunk_ids(self, removed_ids: List[int]) -> None:
        """Delete specific chunk ids from the turbovec index in place.

        Uses IdMapIndex.remove(id) instead of rebuilding the whole index,
        so dropping a document's chunks no longer re-embeds every remaining
        chunk over HTTP. Chunk ids are stable (see self._next_id) and are
        never renumbered on removal, so no other chunk's id changes.
        """
        if self.vector_index is None:
            return
        for chunk_id in removed_ids:
            try:
                self.vector_index.remove(chunk_id)
            except Exception as e:
                log.warning(f"Failed to remove vector id={chunk_id}: {e}")

    async def remove_document(self, file_path: str) -> int:
        """Xóa tất cả chunks của một file khỏi index bằng cách xoá từng id
        trong turbovec — không rebuild (và không re-embed) toàn bộ index."""
        resolved_fp = str(Path(file_path).resolve())
        raw_fp = str(file_path).replace("\\", "/").lower()
        target_name = Path(file_path).name.lower()

        def _matches(c: Dict[str, Any]) -> bool:
            return (
                c.get("file_path") == resolved_fp
                or str(c.get("file_path", "")).replace("\\", "/").lower() == raw_fp
                or c.get("filename", "").lower() == target_name
            )

        removed_ids = [c["id"] for c in self.chunks if _matches(c)]
        if not removed_ids:
            return 0

        self.chunks = [c for c in self.chunks if not _matches(c)]
        self._remove_chunk_ids(removed_ids)

        if self.persistent:
            await asyncio.to_thread(self._save_index)
        self._rebuild_bm25()
        self.enabled = bool(self.chunks)
        log.info(f"Removed {len(removed_ids)} chunks for: {file_path}")
        return len(removed_ids)

    async def sync_lifecycle(self, active_file_paths: List[str]) -> int:
        """Dọn dẹp tất cả orphaned chunks của các file không còn tồn tại trong
        active_file_paths bằng cách xoá từng id trong turbovec — không rebuild
        (và không re-embed) toàn bộ index."""
        active_set = {str(Path(p).resolve()) for p in active_file_paths}
        active_names = {Path(p).name.lower() for p in active_file_paths}

        def _active(c: Dict[str, Any]) -> bool:
            return (
                str(Path(c.get("file_path", "")).resolve()) in active_set
                or c.get("filename", "").lower() in active_names
            )

        removed_ids = [c["id"] for c in self.chunks if not _active(c)]
        if not removed_ids:
            return 0

        self.chunks = [c for c in self.chunks if _active(c)]
        self._remove_chunk_ids(removed_ids)

        if self.persistent:
            await asyncio.to_thread(self._save_index)
        self._rebuild_bm25()
        self.enabled = bool(self.chunks)
        log.info(f"Pruned {len(removed_ids)} orphaned chunks during RAG lifecycle sync")
        return len(removed_ids)


# Singleton instances
_rag_instance: Optional[RAGEngine] = None

def get_rag_engine() -> RAGEngine:
    """Get or create the global RAGEngine singleton."""
    global _rag_instance
    if _rag_instance is None:
        # nomic-embed-text-v1.5 has 768 dimensions
        _rag_instance = RAGEngine(dim=768)
    return _rag_instance

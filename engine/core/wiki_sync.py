# -*- coding: utf-8 -*-
"""
WikiSync — Tự động đồng bộ hóa các file Markdown từ data/wiki vào SemanticMemoryEngine.
Hỗ trợ kiểm tra sự thay đổi của file bằng hàm băm MD5 để tối ưu hóa hiệu năng nạp vector.
"""

import os
import json
import hashlib
import logging
from pathlib import Path
from engine.core.memory import SemanticMemoryEngine

log = logging.getLogger("jarvis.wiki_sync")

WIKI_DIR = Path(__file__).parent.parent.parent / "data" / "wiki"
SYNC_STATE_PATH = WIKI_DIR / ".sync_state.json"

def get_file_hash(filepath: Path) -> str:
    """Tính mã băm MD5 của một file để nhận diện thay đổi."""
    try:
        content = filepath.read_bytes()
        return hashlib.md5(content).hexdigest()
    except Exception as e:
        log.warning(f"Failed to calculate hash for {filepath}: {e}")
        return ""

def load_sync_state() -> dict:
    """Tải trạng thái đồng bộ trước đó."""
    if SYNC_STATE_PATH.exists():
        try:
            with open(SYNC_STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.warning(f"Failed to load sync state: {e}")
    return {}

def save_sync_state(state: dict):
    """Lưu trạng thái đồng bộ hiện tại."""
    try:
        SYNC_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SYNC_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning(f"Failed to save sync state: {e}")

def sync_wiki_to_semantic_memory(force: bool = False):
    """
    Quét toàn bộ thư mục data/wiki/ và đồng bộ các file markdown mới hoặc thay đổi vào SemanticMemoryEngine.
    """
    log.info("Wiki Sync skipped: Obsidian remains a separate retrieval source")
    return

    if not WIKI_DIR.exists():
        log.info("Wiki directory does not exist, skipping sync.")
        return

    log.info("🔄 Starting Wiki Sync to Semantic Memory...")
    state = load_sync_state()
    new_state = {}
    
    engine = SemanticMemoryEngine.get_instance()
    # Chắc chắn rằng cache đã được khởi tạo
    engine.initialize_cache()
    
    updated_files_count = 0
    
    # Quét tất cả các file markdown trong data/wiki
    for root, _, files in os.walk(WIKI_DIR):
        for file in files:
            if not file.endswith(".md"):
                continue
            file_path = Path(root) / file
            
            # Bỏ qua các file ẩn/temp nếu có
            if file.startswith("."):
                continue
                
            relative_path = file_path.relative_to(WIKI_DIR).as_posix()
            
            # Loại trừ thư mục Gym/ và các tài liệu người dùng chỉ định không nạp vào AI
            if relative_path.lower().startswith("gym/"):
                continue

            current_hash = get_file_hash(file_path)
            new_state[relative_path] = current_hash
            
            # Nếu file mới, có sự thay đổi hash hoặc chạy chế độ ép buộc (force)
            if force or relative_path not in state or state[relative_path] != current_hash:
                try:
                    content = file_path.read_text(encoding="utf-8")
                    if "no_index: true" in content or 'no_index: "true"' in content:
                        continue
                    # Tách nội dung thành các khối
                    chunks = content.split("### ")
                    for i, chunk in enumerate(chunks):
                        chunk = chunk.strip()
                        if not chunk:
                            continue
                        
                        chunk_text = chunk if i == 0 else f"### {chunk}"
                        # Bọc thêm ngữ cảnh nguồn gốc của file
                        augmented_content = f"[Nguồn Obsidian Wiki: {relative_path}]\n{chunk_text}"
                        
                        # Sinh ID giả lập dựa trên đường dẫn file và index của chunk
                        # Sử dụng hàm băm chuỗi để tránh trùng lặp ID
                        chunk_id_str = f"{relative_path}_{i}"
                        # Chuyển hash 32 ký tự MD5 hex thành một ID nguyên uint64 cho turbovec (sử dụng 8 byte đầu)
                        hash_int = int(hashlib.md5(chunk_id_str.encode("utf-8")).hexdigest()[:16], 16) & 0xFFFFFFFFFFFFFFFF
                        
                        # Nạp trực tiếp vào SemanticMemoryEngine
                        # Xóa vector index cũ nếu đã tồn tại để tránh rác (nếu cần)
                        engine.add_memory(hash_int, augmented_content, "wiki")
                        
                    updated_files_count += 1
                    log.info(f"Synced file: {relative_path}")
                except Exception as ex:
                    log.error(f"Failed to sync file {relative_path}: {ex}")
            else:
                # Giữ nguyên các hash của file không đổi
                new_state[relative_path] = state[relative_path]
                
    save_sync_state(new_state)
    log.info(f"🔄 Wiki Sync completed. {updated_files_count} files synchronized.")

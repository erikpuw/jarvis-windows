import os
import re
import json
import asyncio
import logging
import zipfile
import io
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger("jarvis.extension_installer")

# Plugin/hook code runs on the host as soon as it's approved. The approval
# card must show every byte the user is agreeing to — a truncated preview
# lets a malicious payload hide past the visible portion while still getting
# a real "Đồng ý" click. If content is too large to show in full, refuse
# rather than show a partial/blind preview.
MAX_EXTENSION_PREVIEW_CHARS = 8000

async def install_extension(arguments: dict, ws: Any = None, safe_send: Any = None) -> str:
    """Tải, giải nén và nạp nóng các plugin/skill/hook mở rộng cho JARVIS."""
    ext_type = arguments.get("ext_type")
    ext_name = arguments.get("name", "").strip()
    url = arguments.get("url", "").strip()
    code_content = arguments.get("code_content", "")

    if not ext_type or ext_type not in ["plugin", "skill", "hook"]:
        return "Lỗi: Loại mở rộng (ext_type) không hợp lệ. Phải là 'plugin', 'skill', hoặc 'hook'."
        
    # Chuẩn hóa cú pháp github:owner/repo
    if url.startswith("github:"):
        repo_part = url.split("github:")[1].strip("/")
        url = f"https://github.com/{repo_part}"

    # Tự động trích xuất tên nếu rỗng
    if not ext_name and url:
        parsed_url = urlparse(url)
        path_parts = [p for p in parsed_url.path.strip("/").split("/") if p]
        if len(path_parts) >= 2:
            ext_name = path_parts[1].replace(".git", "")
        else:
            ext_name = parsed_url.path.split('/')[-1].split('.')[0]

    if not ext_name:
        return "Lỗi: Tên mở rộng (name) không được để trống."

    # Bảo mật cơ bản chống Path Traversal
    ext_name = os.path.basename(ext_name)

    content = ""
    file_ext = ""

    # Nhận diện nếu url trỏ tới 1 GitHub Repo (chứ không phải 1 file raw cụ thể)
    is_github_repo = False
    if url and "github.com" in url and not url.endswith((".py", ".ts", ".js", ".md", ".json")):
        parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
        if len(parts) >= 2:
            is_github_repo = True

    # Hàm helper tải URL an toàn bằng urllib (do httpx thi thoảng bị block/timeout trên môi trường Windows)
    def download_url(download_url: str) -> bytes:
        import urllib.request
        req = urllib.request.Request(
            download_url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        )
        with urllib.request.urlopen(req, timeout=20.0) as response:
            return response.read()

    resolved_commit_sha = ""
    if url and is_github_repo:
        # Flow tải Zip và Giải nén tìm code
        repo_path = urlparse(url).path.strip("/")

        def resolve_commit_sha(branch: str) -> str:
            """Phân giải SHA commit thật của nhánh qua GitHub API — chỉ để
            hiển thị cho người dùng biết chính xác họ đang duyệt commit nào
            (không có bước này trước đây: không pin commit, không có gì để
            đối chiếu nếu repo bị compromise giữa 2 lần cài cùng 1 URL)."""
            try:
                api_url = f"https://api.github.com/repos/{repo_path}/commits/{branch}"
                data = download_url(api_url)
                return json.loads(data).get("sha", "")[:12]
            except Exception:
                return ""

        zip_urls = [
            ("main", f"https://github.com/{repo_path}/archive/refs/heads/main.zip"),
            ("master", f"https://github.com/{repo_path}/archive/refs/heads/master.zip"),
        ]

        zip_content = None
        for branch, zip_url in zip_urls:
            try:
                zip_content = download_url(zip_url)
                if zip_content:
                    resolved_commit_sha = resolve_commit_sha(branch)
                    break
            except Exception:
                continue

        if not zip_content:
            return f"Lỗi: Không thể tải mã nguồn Zip từ GitHub Repository ({url}) qua nhánh main hoặc master."
        
        # Giải nén trong bộ nhớ & Tìm file phù hợp
        try:
            with zipfile.ZipFile(io.BytesIO(zip_content)) as z:
                namelist = z.namelist()
                target_file_in_zip = None
                
                if ext_type == "skill":
                    md_files = [f for f in namelist if f.endswith(".md")]
                    for name_pattern in ["SKILL.md", "README.md", "README_vi.md"]:
                        matched = [f for f in md_files if f.lower().endswith(name_pattern.lower())]
                        if matched:
                            target_file_in_zip = matched[0]
                            break
                    if not target_file_in_zip and md_files:
                        target_file_in_zip = md_files[0]
                        
                elif ext_type in ["plugin", "hook"]:
                    code_files = [f for f in namelist if f.endswith((".py", ".ts", ".js", ".mjs", ".cjs"))]
                    matched = [f for f in code_files if f.lower().endswith(f"/{ext_name.lower()}.py") or f.lower().endswith(f"/{ext_name.lower()}.ts")]
                    if matched:
                        target_file_in_zip = matched[0]
                    elif code_files:
                        py_files = [f for f in code_files if f.endswith(".py")]
                        target_file_in_zip = py_files[0] if py_files else code_files[0]
                
                if not target_file_in_zip:
                    return f"Lỗi: Không tìm thấy tệp code/markdown phù hợp nào trong Repository cho kiểu '{ext_type}'."
                
                content = z.read(target_file_in_zip).decode("utf-8", errors="ignore")
                _, file_ext = os.path.splitext(target_file_in_zip)
        except Exception as zip_err:
            return f"Lỗi xử lý giải nén zip từ GitHub: {zip_err}"
    
    elif url:
        try:
            content_bytes = download_url(url)
            content = content_bytes.decode("utf-8", errors="ignore")
        except Exception as e:
            return f"Lỗi kết nối khi tải extension: {e}"
    else:
        content = code_content

    if not content or not content.strip():
        return "Lỗi: Nội dung mã nguồn (code_content) hoặc dữ liệu từ URL trống."

    root_dir = Path(__file__).resolve().parent.parent.parent

    # Skill là markdown thuần (không có code chạy) nên xử lý riêng: phải nằm
    # đúng chỗ skill_manager quét (skills/{name}/SKILL.md, không phải commands/)
    # để tạo xong là dùng lại được ngay, và tự thêm frontmatter/description nếu
    # nội dung chưa có, để skill match được từ khóa thay vì rơi vào "tạo ra
    # nhưng không bao giờ được dùng".
    if ext_type == "skill":
        from engine.tools.skill_manager import create_skill as _create_skill, get_skill_manager, SKILLS_DIR
        name_clean = re.sub(r'[^a-zA-Z0-9_-]', '', ext_name).lower()
        dest_path = SKILLS_DIR / name_clean / "SKILL.md"

        if content.lstrip("﻿").startswith("---"):
            if dest_path.exists():
                return f"Lỗi: Skill '{name_clean}' đã tồn tại tại `{dest_path.relative_to(root_dir)}`."
            try:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                dest_path.write_text(content, encoding="utf-8")
            except Exception as io_err:
                return f"Lỗi ghi file skill: {io_err}"
        else:
            result = _create_skill(name=name_clean, content=content)
            if not result.get("success"):
                return f"Lỗi tạo skill: {result.get('error')}"

        get_skill_manager().scan_skills()
        commit_line = f"\n- **Commit nguồn**: `{resolved_commit_sha}`" if resolved_commit_sha else ""
        return (
            "✅ **Cài đặt extension thành công!**\n"
            "- **Loại**: `skill`\n"
            f"- **Đường dẫn**: `{dest_path.relative_to(root_dir)}`{commit_line}\n"
            "- **Trạng thái**: Quét và nạp skill thành công — dùng lại được ngay."
        )

    # Plugin/Hook chứa code thực thi thật: Plugin chạy ngay khi nạp (import
    # module), Hook còn tự động chạy lại trên mọi sự kiện tương lai
    # (on_startup/on_message_receive/...). Khác với skill (chỉ là văn bản),
    # 2 loại này bắt buộc phải được người dùng xác nhận rõ ràng — không tự
    # động hoá — trước khi bất kỳ dòng code nào được ghi ra đĩa và nạp chạy.
    if ext_type in ("plugin", "hook"):
        if not ws or not safe_send:
            return (
                f"Lỗi: Cài {ext_type} '{ext_name}' cần phiên giao diện đang hoạt động để xin "
                "xác nhận trước khi chạy code — không thể tự cài khi không có phiên người dùng."
            )

        from engine.main.ask_verifi import ask_user_confirmation

        preview = content.strip()
        if len(preview) > MAX_EXTENSION_PREVIEW_CHARS:
            return (
                f"Lỗi: Nội dung {ext_type} '{ext_name}' dài {len(preview)} ký tự, vượt quá giới hạn "
                f"{MAX_EXTENSION_PREVIEW_CHARS} ký tự có thể hiển thị đầy đủ để xin xác nhận an toàn. "
                "Vì lý do bảo mật, Jarvis không bao giờ xin duyệt một phần nội dung code rồi chạy toàn "
                "bộ — vui lòng rút gọn/chia nhỏ nội dung, hoặc cài đặt thủ công sau khi tự kiểm tra."
            )
        kind_label = (
            "Plugin (code sẽ chạy ngay khi nạp)" if ext_type == "plugin"
            else "Hook (code sẽ tự động chạy lại trên các sự kiện hệ thống trong tương lai, ví dụ mỗi tin nhắn)"
        )
        source_line = ('URL ' + url) if url else 'code do Jarvis tự viết (code_content)'
        if resolved_commit_sha:
            source_line += f" (commit {resolved_commit_sha})"
        message = (
            f"Jarvis muốn cài {kind_label}, tên '{ext_name}'.\n"
            f"Nguồn: {source_line}.\n"
            f"Toàn bộ nội dung ({len(preview)} ký tự, không ẩn phần nào) sắp ghi ra đĩa và chạy:\n```\n{preview}\n```"
        )
        log.info("Yêu cầu xác nhận cài %s '%s'. Nội dung đầy đủ:\n%s", ext_type, ext_name, content)
        approved = await ask_user_confirmation(
            ws, safe_send, f"install_extension:{ext_type}", message, timeout=300.0
        )
        if not approved:
            log.warning("Người dùng từ chối hoặc hết hạn xác nhận cài %s '%s'.", ext_type, ext_name)
            return f"Đã hủy: cài đặt {ext_type} '{ext_name}' bị từ chối hoặc hết thời gian chờ xác nhận."

    # Xác định thư mục và phần mở rộng file
    dest_dir = None

    if ext_type == "plugin":
        dest_dir = root_dir / "plugins"
        if not file_ext:
            if url:
                _, url_ext = os.path.splitext(url.split("?")[0])
                if url_ext.lower() in [".py", ".js", ".ts", ".cjs", ".mjs"]:
                    file_ext = url_ext.lower()
            
            if not file_ext:
                if "import " in content or "def " in content:
                    file_ext = ".py"
                else:
                    file_ext = ".ts"
    elif ext_type == "hook":
        dest_dir = root_dir / "hooks"
        if not file_ext:
            if url:
                _, url_ext = os.path.splitext(url.split("?")[0])
                if url_ext.lower() in [".py", ".js", ".ts", ".cjs", ".mjs"]:
                    file_ext = url_ext.lower()
            
            if not file_ext:
                if "import " in content or "def " in content:
                    file_ext = ".py"
                else:
                    file_ext = ".ts"

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{ext_name}{file_ext}"

    try:
        dest_path.write_text(content, encoding="utf-8")
    except Exception as io_err:
        return f"Lỗi ghi file extension: {io_err}"

    # Hot Reload (nạp nóng)
    reload_msg = ""
    try:
        if ext_type == "plugin":
            from engine.tools.load_plugin import PluginLoader
            PluginLoader.get_instance().unload(ext_name)
            try:
                ok = await asyncio.wait_for(
                    asyncio.to_thread(PluginLoader.get_instance().load_plugin, ext_name),
                    timeout=45.0,
                )
            except asyncio.TimeoutError:
                ok = False
                reload_msg = f"Nạp nóng plugin '{ext_name}': Thất bại (quá thời gian chờ 45s khi nạp plugin)"
            else:
                reload_msg = f"Nạp nóng plugin '{ext_name}': {'Thành công' if ok else 'Thất bại'}"
        elif ext_type == "hook":
            from engine.tools.load_hook import HookLoader
            ok = HookLoader.get_instance().load_hook(ext_name)
            reload_msg = f"Nạp nóng hook '{ext_name}': {'Thành công' if ok else 'Thất bại'}"
    except Exception as reload_err:
        reload_msg = f"Extension đã ghi thành công nhưng nạp nóng thất bại: {reload_err}"

    commit_line = f"\n- **Commit nguồn**: `{resolved_commit_sha}`" if resolved_commit_sha else ""
    log.info("Extension installed: type=%s name=%s commit=%s", ext_type, ext_name, resolved_commit_sha or "n/a")
    return (
        f"✅ **Cài đặt extension thành công!**\n- **Loại**: `{ext_type}`\n"
        f"- **Đường dẫn**: `{dest_path.relative_to(root_dir)}`{commit_line}\n- **Trạng thái**: {reload_msg}"
    )

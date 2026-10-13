"""
Skill Manager — Load and manage skills and commands from markdown files

Handles:
1. Scan skills/ and commands/ directories recursively
2. Parse markdown files for skill/command definitions
3. Load into system memory (NO communication with llm_server.py)
4. Only operates at server.py layer
"""

import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
import re
import types

log = logging.getLogger("jarvis.skill_manager")

# Paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
SKILLS_DIR = PROJECT_ROOT / "skills"


@dataclass
class Skill:
    """Skill definition from markdown"""
    name: str
    description: str
    category: str = "general"
    tags: list[str] = field(default_factory=list)
    content: str = ""
    file_path: str = ""
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "tags": self.tags,
            "file_path": self.file_path,
            "enabled": self.enabled,
        }


class SkillManager:
    """Manages skills loaded from markdown files"""

    def __init__(self):
        self.skills: dict[str, Skill] = {}
        self.skill_modules: dict[str, types.ModuleType] = {}
        self._ensure_directories()

    def _ensure_directories(self):
        """Create skills directory if it doesn't exist"""
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        log.info("Skill directories ready")

    def _parse_markdown_frontmatter(self, content: str) -> tuple[dict, str]:
        """Parse YAML frontmatter from markdown file"""
        content = content.lstrip('\ufeff')
        frontmatter = {}
        body = content

        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                yaml_str = parts[1].strip()
                body = parts[2].strip()

                for line in yaml_str.split("\n"):
                    if ":" in line:
                        key, value = line.split(":", 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")

                        if key == "tags" and value.startswith("["):
                            value = [t.strip().strip('"').strip("'") for t in value.strip("[]").split(",")]
                        elif key in ["enabled"]:
                            value = value.lower() in ["true", "yes", "1"]

                        frontmatter[key] = value

        return frontmatter, body

    def _extract_metadata_from_content(self, content: str) -> dict:
        """Extract metadata from markdown content (headings, etc.)"""
        metadata = {}

        heading_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if heading_match:
            metadata["name"] = heading_match.group(1).strip()

        para_match = re.search(r"^(?:#+\s+.+\n)*\n?(.+?)(?:\n\n|$)", content, re.MULTILINE)
        if para_match:
            metadata["description"] = para_match.group(1).strip()

        return metadata

    def load_skill_from_file(self, file_path: Path) -> Optional[Skill]:
        """Load a single skill from markdown file"""
        try:
            content = file_path.read_text(encoding="utf-8")
            frontmatter, body = self._parse_markdown_frontmatter(content)
            metadata = self._extract_metadata_from_content(content)

            skill_data = {**metadata, **frontmatter}

            skill = Skill(
                name=skill_data.get("name", file_path.stem),
                description=skill_data.get("description", ""),
                category=skill_data.get("category", "general"),
                tags=skill_data.get("tags", []),
                content=body,
                file_path=str(file_path),
                enabled=skill_data.get("enabled", True),
            )

            return skill

        except Exception as e:
            log.error(f"Failed to load skill from {file_path}: {e}")
            return None

    def scan_skills(self, recursive: bool = True) -> int:
        """Scan and load skills from skills/ — chỉ load file SKILL.md, bỏ rác."""
        if not SKILLS_DIR.exists():
            log.warning("Skills directory not found")
            return 0

        pattern = "**/*.md" if recursive else "*.md"
        md_files = [f for f in SKILLS_DIR.glob(pattern) if f.name.lower() in ("skill.md", "skills.md")]

        loaded_count = 0
        for file_path in md_files:
            skill = self.load_skill_from_file(file_path)
            if skill:
                self.skills[skill.name] = skill
                loaded_count += 1

        log.info(f"Loaded {loaded_count} skills")
        return loaded_count

    def get_skill(self, skill_name: str) -> Optional[Skill]:
        """Get a skill by name"""
        return self.skills.get(skill_name)

    def list_skills(self, enabled_only: bool = True, category: Optional[str] = None) -> list[Skill]:
        """List all loaded skills"""
        skills = list(self.skills.values())

        if enabled_only:
            skills = [s for s in skills if s.enabled]

        if category:
            skills = [s for s in skills if s.category == category]

        return skills

    def search_skills(self, query: str) -> list[Skill]:
        """Search skills by name, description, or tags"""
        query_lower = query.lower()
        results = []

        for skill in self.skills.values():
            if (query_lower in skill.name.lower() or
                query_lower in skill.description.lower() or
                any(query_lower in tag.lower() for tag in skill.tags)):
                results.append(skill)

        return results

    def enable_skill(self, skill_name: str) -> bool:
        """Enable a skill"""
        if skill_name not in self.skills:
            return False
        self.skills[skill_name].enabled = True
        log.info(f"Enabled skill: {skill_name}")
        return True

    def disable_skill(self, skill_name: str) -> bool:
        """Disable a skill"""
        if skill_name not in self.skills:
            return False
        self.skills[skill_name].enabled = False
        log.info(f"Disabled skill: {skill_name}")
        return True

    def get_stats(self) -> dict:
        """Get statistics about loaded skills"""
        return {
            "total_skills": len(self.skills),
            "enabled_skills": sum(1 for s in self.skills.values() if s.enabled),
        }

    def get_all_skills_dict(self, enabled_only: bool = True) -> dict:
        """Get all skills as dictionary"""
        skills = self.list_skills(enabled_only=enabled_only)
        return {skill.name: skill.to_dict() for skill in skills}


_skill_manager: Optional[SkillManager] = None


def get_skill_manager() -> SkillManager:
    """Get or create the global skill manager instance"""
    global _skill_manager
    if _skill_manager is None:
        _skill_manager = SkillManager()
    return _skill_manager


def initialize_skills() -> SkillManager:
    """Initialize skill manager and scan directories"""
    manager = get_skill_manager()
    manager.scan_skills(recursive=True)
    stats = manager.get_stats()
    log.info(f"Skills initialized: {stats['total_skills']} skills")
    return manager


def _auto_skill_description(content: str, fallback: str, max_len: int = 150) -> str:
    """Rút mô tả ngắn từ dòng đầu tiên có nội dung của skill (bỏ dấu # heading).

    Mô tả cụ thể giúp _matches() tìm đúng skill theo từ khóa; mô tả chung
    chung kiểu "Auto-created skill for X" không mang từ khóa nào nên skill
    gần như không bao giờ được match lại (mất luôn khả năng "tái dùng").
    """
    for line in content.splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            line = line.replace("\n", " ").replace('"', "'")
            return line[:max_len]
    return fallback


def create_skill(name: str, content: str, category: str = "general", tags: list[str] = None,
                  description: str = "") -> dict:
    """Tạo kỹ năng mới dạng `skills/{name}/SKILL.md`. Chỉ load file SKILL.md."""
    import json
    if not name or not content:
        return {"success": False, "error": "Name and content are required"}

    name_clean = re.sub(r'[^a-zA-Z0-9_-]', '', name).lower()
    skill_dir = SKILLS_DIR / name_clean
    file_path = skill_dir / "SKILL.md"

    if file_path.exists():
        return {"success": False, "error": f"Skill '{name_clean}' already exists"}

    desc = (description or "").strip().replace("\n", " ").replace('"', "'")
    if not desc:
        desc = _auto_skill_description(content, f"Kỹ năng {name_clean}")

    yaml_header = "---\n"
    yaml_header += f"name: {name_clean}\n"
    yaml_header += f"description: {desc}\n"
    yaml_header += f"category: {category}\n"
    if tags:
        yaml_header += f"tags: {json.dumps(tags)}\n"
    yaml_header += "enabled: true\n"
    yaml_header += "---\n\n"
    
    full_content = yaml_header + content
    
    try:
        skill_dir.mkdir(parents=True, exist_ok=True)
        file_path.write_text(full_content, encoding="utf-8")
        get_skill_manager().scan_skills()
        log.info("Agent created new skill: %s", name_clean)
        return {"success": True, "message": f"Skill '{name_clean}' created successfully at {file_path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def patch_skill(name: str, old_content: str, new_content: str) -> dict:
    """Sửa đổi một phần nội dung kỹ năng hiện có dưới dạng markdown trong skills/ để tự tối ưu hóa.
    
    Args:
        name: Tên kỹ năng (ví dụ: 'git-rebase')
        old_content: Nội dung cũ cần tìm để thay thế
        new_content: Nội dung mới dùng để thay thế
    """
    if not name or not old_content:
        return {"success": False, "error": "Name and old_content are required"}
        
    skill_manager = get_skill_manager()
    skill = skill_manager.get_skill(name)
    if not skill:
        for s in skill_manager.skills.values():
            if s.name.lower() == name.lower():
                skill = s
                break
                
    if not skill or not skill.file_path:
        return {"success": False, "error": f"Skill '{name}' not found"}
        
    file_path = Path(skill.file_path)
    if not file_path.exists():
        return {"success": False, "error": f"Skill file does not exist: {file_path}"}
        
    content = file_path.read_text(encoding="utf-8")
    if old_content not in content:
        return {"success": False, "error": "old_content not found in skill file"}
        
    updated_content = content.replace(old_content, new_content)
    
    try:
        file_path.write_text(updated_content, encoding="utf-8")
        skill_manager.scan_skills()
        log.info("Agent patched skill: %s", name)
        return {"success": True, "message": f"Skill '{name}' patched successfully"}
    except Exception as e:
        return {"success": False, "error": str(e)}




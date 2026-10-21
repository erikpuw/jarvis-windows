"""2026-10-13: test_workflow_sample_filter ghi rỗng data/wiki/System/Learning.md thật (đường dẫn wiki tính sẵn lúc
import, đổi PROJECT_ROOT không đủ); trước đó hub Workflows/Công cụ.md cũng vậy. conftest.py chuyển mọi đường dẫn wiki
sang thư mục tạm cho MỌI test."""
from engine.core import evolution, learning

REAL = learning.Path(__file__).resolve().parents[1] / "data"


def test_wiki_paths_point_outside_real_data():
    for path in (learning.WORKFLOWS_WIKI_DIR, learning.PREFERENCES_WIKI_PATH, learning.LESSONS_WIKI_PATH,
                 learning.WORKFLOWS_HUB_WIKI_PATH, learning.LEARNING_HUB_WIKI_PATH, evolution.EVOLUTION_LOG,
                 evolution.STYLE_FILE):
        assert REAL not in path.resolve().parents, path
        assert "skills" not in path.parts or "self_evolution" not in path.parts, path

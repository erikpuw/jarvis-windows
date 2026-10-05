"""Settings → Bộ nhớ → Evolution: đọc và sửa luật tiến hóa ngay trong giao diện.

Hai file, một chỗ duy nhất trong UI:
- skills/self_evolution/STYLE.md   luật giọng điệu ĐANG ÁP DỤNG (được nạp vào system prompt mỗi lượt chat)
- data/wiki/System/Evolution.md    nhật ký luật tiến hóa đã thêm (Routing = đề xuất chờ duyệt, Giao tiếp)

GET /api/evolution/list và POST /api/evolution/update (engine/UIUX/ui_engine.py). STYLE.md bị chặn quá dài vì nó vào prompt mỗi lượt.

Run: python tests/test_evolution_files_api.py   (hoặc pytest)
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import engine.core.evolution as evolution
from engine.UIUX import ui_engine
from engine.UIUX.ui_engine import api_evolution_list, api_evolution_update


def _body(resp):
    return json.loads(resp.body) if hasattr(resp, "body") else resp


class _Files:
    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.style = root / "skills" / "self_evolution" / "STYLE.md"
        self.log = root / "data" / "wiki" / "System" / "Evolution.md"
        self.style.parent.mkdir(parents=True)
        self.style.write_text("# Self Evolution Style Rules\n- **[MỚI]** Xưng hô thân mật.\n", encoding="utf-8")
        self._old = (evolution.STYLE_FILE, evolution.EVOLUTION_LOG)
        evolution.STYLE_FILE, evolution.EVOLUTION_LOG = self.style, self.log
        return self

    def __exit__(self, *exc):
        evolution.STYLE_FILE, evolution.EVOLUTION_LOG = self._old
        self.tmp.cleanup()


def test_list_has_both_files_even_when_the_log_does_not_exist_yet():
    with _Files() as f:
        data = asyncio.run(api_evolution_list())
        assert data["success"] is True
        ids = [i["id"] for i in data["items"]]
        assert ids == ["style", "log"]
        style = data["items"][0]
        assert "Xưng hô thân mật" in style["content"]
        assert style["path"].endswith("STYLE.md") and style["editable"] is True
        assert data["items"][1]["content"] == "" and data["items"][1]["exists"] is False
        assert data["total"] == 2


def test_search_filters_by_title_and_content():
    with _Files():
        hit = asyncio.run(api_evolution_list(q="thân mật"))
        assert [i["id"] for i in hit["items"]] == ["style"]
        none = asyncio.run(api_evolution_list(q="không-có-từ-này"))
        assert none["items"] == [] and none["total"] == 0


def test_update_style_writes_the_live_file():
    with _Files() as f:
        r = _body(asyncio.run(api_evolution_update(ui_engine.EvolutionUpdateBody(id="style", content="# Rules\n- Gọn, thẳng.\n"))))
        assert r["success"] is True
        assert f.style.read_text(encoding="utf-8") == "# Rules\n- Gọn, thẳng.\n"
        assert not f.style.with_suffix(".md.tmp").exists()  # ghi nguyên tử, không để file tạm


def test_update_log_creates_missing_file_and_folder():
    with _Files() as f:
        r = _body(asyncio.run(api_evolution_update(ui_engine.EvolutionUpdateBody(id="log", content="# Jarvis Evolution Log\n"))))
        assert r["success"] is True
        assert f.log.read_text(encoding="utf-8") == "# Jarvis Evolution Log\n"


def test_style_too_long_is_refused_because_it_goes_into_every_prompt():
    with _Files() as f:
        before = f.style.read_text(encoding="utf-8")
        r = _body(asyncio.run(api_evolution_update(ui_engine.EvolutionUpdateBody(id="style", content="x" * 5000))))
        assert r["success"] is False and r["code"] == "too_long"
        assert f.style.read_text(encoding="utf-8") == before


def test_unknown_id_is_404():
    with _Files():
        resp = asyncio.run(api_evolution_update(ui_engine.EvolutionUpdateBody(id="../../etc/passwd", content="x")))
        assert resp.status_code == 404


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok  ", name)
    print("ALL PASS")

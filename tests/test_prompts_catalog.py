"""Test chống lệch danh mục Agent & Tool một nguồn (Spec 2026-09-25 mục 1)."""
from pathlib import Path
import re
import pytest

from engine.orchestrator.registry import AGENT_REGISTRY

EXPECTED_OFFERABLE_TOOLS = {
    "open_app": ("desktop", "mở ứng dụng"),
    "close_app": ("desktop", "đóng ứng dụng"),
    "check_mail": ("email", "xem email"),
    "check_calendar": ("email", "xem lịch hẹn"),
    "weather_search": ("weather", "tra thời tiết"),
    "search_news": ("news", "tìm tin tức"),
    "get_market_data": ("market", "giá vàng/xăng/tỷ giá"),
    "get_cgv_movies": ("cinema", "lịch chiếu phim"),
    "get_epic_free_games": ("games", "game miễn phí"),
    "search_media": ("media", "mở nhạc/phim/video"),
    "cap_screen": ("vision", "chụp màn hình"),
    "read_screen": ("vision", "xem màn hình"),
    "take_note": ("notes", "ghi chú"),
    "query_history": ("history", "xem lại lịch sử trò chuyện"),
    "get_vannien_data": ("lunar", "lịch vạn niên"),
    "legal_lookup": ("legal", "tra cứu pháp luật"),
    "get_zodiac_data": ("zodiac", "tra cứu cung hoàng đạo"),
    "search_products": ("shop", "tra cứu giá sản phẩm"),
    "vietlott_analysis": ("vietlott", "phân tích vietlott"),
}

EXPECTED_AGENT_CRITERIA = """
- goose: Chỉ mở giao diện ứng dụng Goose (Windows GUI) để người dùng tự thao tác — KHÔNG tự động gửi lệnh sửa/viết code qua CLI.
- office: Chỉ khi có tệp đính kèm Word/Excel/PowerPoint đáng tin cậy VÀ người dùng yêu cầu tạo/sửa/định dạng nội dung file đó. KHÔNG chọn chỉ vì nhắc tới Word/Excel/PowerPoint — mở/đóng ứng dụng là desktop.
- email: Chỉ khi kiểm tra 10 email gần nhất hoặc lịch hẹn 7 ngày tới trong Outlook.
- desktop: Mở, đóng, bật, tắt ứng dụng Windows (bao gồm cả Word/Excel/PowerPoint/Outlook-email khi chỉ là mở/đóng ứng dụng, không phải đọc nội dung).
- weather: Thời tiết, nhiệt độ, dự báo của một nơi.
- news: Tin tức, bản tin thời sự trên báo trong nước, kể cả tin về giá cả, kinh tế.
- market: Chỉ giá vàng, tỷ giá ngoại tệ, giá xăng dầu, giá gas, giá điện nước hôm nay (giá tổng hợp thị trường). Giá hàng hóa, thực phẩm, sản phẩm là mua sắm.
- shop: Mua sắm: tra giá, đánh giá, so sánh, chọn sản phẩm và hàng hóa (điện tử, đồ gia dụng, thực phẩm).
- route: Chỉ đường đi từ nơi này đến nơi khác.
- places: Tìm địa điểm, quán xung quanh.
- cinema: Phim đang chiếu và sắp chiếu ở rạp CGV (không phải xem video hay phim trực tuyến).
- games: Game miễn phí trên Epic Games Store.
- lunar: Lịch vạn niên hôm nay gồm ngày âm lịch kèm can chi, giờ hoàng đạo, mệnh ngày, tuổi xung khắc, hướng xuất hành.
- zodiac: Tử vi hằng ngày của 12 cung hoàng đạo (cung theo ngày sinh dương lịch), không phải tử vi theo năm sinh/tuổi âm lịch.
- vn_data: Đơn vị hành chính Việt Nam: tỉnh, huyện, xã, mã hành chính.
- vietlott: Phân tích kết quả Mega 6/45, Power 6/55.
- vision: Chỉ khi người dùng yêu cầu chụp/xem màn hình ngay bây giờ.
- webcam: Chỉ khi người dùng yêu cầu xem/dùng webcam hoặc camera trực tiếp.
- media: Nghe nhạc, xem phim, xem livestream, xem video Youtube.
- history: Chỉ khi người dùng chủ động yêu cầu xem lại lịch sử trò chuyện cũ. KHÔNG dùng cho chat/phản hồi/nối tiếp thông thường.
- notes: Ghi lại, hiển thị danh sách, hoặc xoá note.
- project: Kiểm tra project, quét lỗi cú pháp, báo cáo sức khỏe, lịch sử vá lỗi.
- security: Kiểm tra an ninh mạng, quét cổng, giám sát firewall, nhật ký xâm nhập.
- system: Xem hoạt động hệ thống máy tính: CPU, RAM, ổ đĩa, tiến trình đang chạy, tình trạng máy.
- image: Tăng độ phân giải ảnh bằng AI Upscayl.
- legal: Tra cứu văn bản pháp luật Việt Nam.
- win_control: Chỉ khi người dùng gọi rõ điều khiển UI/Explorer Windows.
- rag: Chỉ khi có tệp đính kèm đáng tin cậy VÀ người dùng yêu cầu đọc/tóm tắt/phân tích nội dung file đó.
- dream: Chỉ khi người dùng chủ động yêu cầu dọn dẹp/tóm tắt hội thoại cũ hoặc kích hoạt chu kỳ Dream ngay.
""".strip()


def test_agent_sets_are_identical():
    """Tập agent trong tools.md = tập agent trong agents.md = AGENT_REGISTRY."""
    from engine.prompts import catalog

    agent_names = set(catalog.agents().keys())
    registry_names = set(AGENT_REGISTRY.keys())
    assert agent_names == registry_names, f"tools.md diff: {agent_names ^ registry_names}"
    from engine.orchestrator.registry import PLAN_ONLY_AGENTS
    registry_names -= PLAN_ONLY_AGENTS   # chỉ vào bằng chế độ mục tiêu, không cho classifier

    # Kiểm tra trong agents.md
    criteria_lines = catalog.agent_criteria().strip().splitlines()
    criteria_agents = {line.split(":")[0].replace("-", "").strip() for line in criteria_lines if ":" in line}
    assert criteria_agents == registry_names, f"agents.md diff: {criteria_agents ^ registry_names}"


def test_every_tool_in_tools_md_has_command_file():
    """Mỗi tool trong tools.md có file commands/<tool>.md."""
    from engine.prompts import catalog

    root = Path(__file__).resolve().parents[1]
    commands_dir = root / "commands"
    assert commands_dir.is_dir()

    all_tools = catalog.all_tools()
    missing_files = []
    for tool_name in all_tools:
        cmd_file = commands_dir / f"{tool_name}.md"
        if not cmd_file.is_file():
            missing_files.append(tool_name)
    assert not missing_files, f"Tools missing command markdown file: {missing_files}"


def test_every_command_file_belongs_to_agent_or_system():
    """Mỗi file trong commands/ thuộc đúng một agent hoặc thuộc mục hệ thống."""
    from engine.prompts import catalog

    root = Path(__file__).resolve().parents[1]
    commands_dir = root / "commands"
    cmd_files = {p.stem for p in commands_dir.glob("*.md")}

    tool_to_agent = catalog.tool_to_agent_map()
    system_tools = catalog.system_tools()

    unmapped = []
    for cmd in cmd_files:
        if cmd not in tool_to_agent and cmd not in system_tools:
            unmapped.append(cmd)
    assert not unmapped, f"Commands not mapped to agent or system: {unmapped}"
    assert system_tools == {"install_extension", "mcp_call"}


def test_tool_agent_matches_agent_module():
    """Agent của mỗi tool khớp với agent thật sự dùng tool đó trong engine/agents/."""
    from engine.prompts import catalog

    root = Path(__file__).resolve().parents[1]
    tool_to_agent = catalog.tool_to_agent_map()

    for tool_name, agent_name in tool_to_agent.items():
        if "tool" in AGENT_REGISTRY[agent_name]:   # agent tra cứu: runner dùng chung, tool nằm ở registry
            assert AGENT_REGISTRY[agent_name]["tool"] == tool_name
            continue
        module_path = root / AGENT_REGISTRY[agent_name]["module"].replace(".", "/")
        py_file = Path(f"{module_path}.py")
        assert py_file.is_file(), f"Missing agent file for {agent_name}: {py_file}"
        code = py_file.read_text(encoding="utf-8")
        assert tool_name in code, f"Tool '{tool_name}' not referenced in {py_file}"


def test_offerable_tools_matches_spec():
    """offerable_tools() giống hệt OFFERABLE_TOOLS hiện tại (15 tool)."""
    from engine.prompts import catalog

    offers = catalog.offerable_tools()
    assert offers == EXPECTED_OFFERABLE_TOOLS, f"Difference: {set(offers.items()) ^ set(EXPECTED_OFFERABLE_TOOLS.items())}"
    assert len(offers) == 19


def test_agent_criteria_matches_spec_verbatim():
    """agent_criteria() giống từng ký tự với _AGENT_CRITERIA hiện tại."""
    from engine.prompts import catalog

    criteria = catalog.agent_criteria().strip()
    assert criteria == EXPECTED_AGENT_CRITERIA


def test_resolve_alias():
    """resolve_alias giải quyết đúng alias chính và phụ."""
    from engine.prompts import catalog

    assert catalog.resolve_alias("@officecli") == "office"
    assert catalog.resolve_alias("officecli") == "office"
    assert catalog.resolve_alias("@mail") == "email"
    assert catalog.resolve_alias("@calendar") == "email"
    assert catalog.resolve_alias("@control") == "win_control"
    assert catalog.resolve_alias("@upscale") == "image"
    assert catalog.resolve_alias("@agent_desktop") == "desktop"
    assert catalog.resolve_alias("desktop") == "desktop"
    assert catalog.resolve_alias("@unknown") is None

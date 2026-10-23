import '../chat/lucide_glyphs.dart';
import '../chat/morph_icon.dart';

const memberHiddenPages = {'prompts', 'logs'};

class SettingsPageDef {
  const SettingsPageDef({
    required this.id,
    required this.label,
    required this.description,
    required this.icon,
    required this.activeIcon,
    required this.needsKey,
    this.lockTitle,
  });

  final String id;
  final String label;
  final String description;
  final MorphGlyph icon;
  final MorphGlyph activeIcon;
  final bool needsKey;

  /// pages.ts lockScreen(id, title): the heading of the password card (only the pages that need the key).
  final String? lockTitle;
}

/// The app's version for the menu footer (web shows its VERSION file); keep in step with `version:` in pubspec.yaml.
const appVersion = '1.0.0';

/// pages.ts NAV_GROUPS: the menu's groups in order.
const navGroups = <(String, List<String>)>[
  ('Chung', ['overview', 'user', 'voice', 'connect']),
  ('Dữ liệu', ['memory', 'logs']),
  (
    'Công cụ',
    ['agents', 'commands', 'skills', 'prompts', 'hooks', 'plugins', 'mcp'],
  ),
  ('Hệ thống', ['system', 'graphfy', 'info']),
];

const List<SettingsPageDef> settingsPages = [
  SettingsPageDef(
    id: 'overview',
    label: 'Tổng quan',
    description: 'Tình trạng phần cứng, dịch vụ và dữ liệu của JARVIS.',
    icon: layoutDashboardGlyph,
    activeIcon: layoutGridGlyph,
    needsKey: false,
  ),
  SettingsPageDef(
    id: 'connect',
    label: 'Kết nối & API',
    description: 'Khoá API và địa chỉ máy chủ mô hình.',
    icon: keyRoundGlyph,
    activeIcon: keyGlyph,
    needsKey: false,
  ),
  SettingsPageDef(
    id: 'voice',
    label: 'Giọng đọc',
    description: 'Chọn giọng đọc và tạo giọng clone.',
    icon: audioLinesGlyph,
    activeIcon: volume2Glyph,
    needsKey: false,
  ),
  SettingsPageDef(
    id: 'user',
    label: 'Người dùng',
    description: 'Tên, cách xưng hô và tài khoản lịch.',
    icon: userRoundGlyph,
    activeIcon: userCheckGlyph,
    needsKey: false,
  ),
  SettingsPageDef(
    id: 'system',
    label: 'Hệ thống',
    description: 'Chi tiết phần cứng, dịch vụ và ứng dụng đang chạy.',
    icon: cpuGlyph,
    activeIcon: activityGlyph,
    needsKey: false,
  ),
  SettingsPageDef(
    id: 'memory',
    label: 'Bộ nhớ',
    description: 'Xem, sửa và xoá có kiểm tra quan hệ toàn bộ dữ liệu học và bộ nhớ của JARVIS.',
    icon: databaseGlyph,
    activeIcon: hardDriveGlyph,
    needsKey: false,
  ),
  SettingsPageDef(
    id: 'logs',
    label: 'Nhật ký',
    description: 'Lịch sử chat, Jarvis log, log bảo mật và log TTS. Một trang riêng, không kiểm tra kết nối nên không tự ghi thêm dòng vào log.',
    icon: fileClockGlyph,
    activeIcon: scrollTextGlyph,
    needsKey: false,
  ),
  SettingsPageDef(
    id: 'agents',
    label: 'Gọi tên (@)',
    description: 'Gõ @tên trong command-bar để gọi đúng một công cụ; @rag hỏi kho tài liệu đã nạp.',
    icon: botGlyph,
    activeIcon: botMessageSquareGlyph,
    needsKey: false,
  ),
  SettingsPageDef(
    id: 'hooks',
    label: 'Móc sự kiện',
    description:
        'Các hooks xử lý vòng đời sự kiện quét trực tiếp từ thư mục hooks/.',
    icon: webhookGlyph,
    activeIcon: anchorGlyph,
    needsKey: false,
  ),
  SettingsPageDef(
    id: 'skills',
    label: 'Kỹ năng',
    description:
        'Các kỹ năng chuyên môn tự động hóa quét trực tiếp từ thư mục skills/.',
    icon: sparklesGlyph,
    activeIcon: flameGlyph,
    needsKey: false,
  ),
  SettingsPageDef(
    id: 'prompts',
    label: 'Lời nhắc hệ thống',
    description: 'Các khuôn mẫu prompt hệ thống định nghĩa hành vi quét từ thư mục prompt/.',
    icon: scrollTextGlyph,
    activeIcon: fileTextGlyph,
    needsKey: false,
  ),
  SettingsPageDef(
    id: 'commands',
    label: 'Lệnh (/)',
    description: 'Gõ /tên_lệnh trong command-bar để chạy đúng một công cụ; /help liệt kê mọi lệnh.',
    icon: terminalGlyph,
    activeIcon: squareCodeGlyph,
    needsKey: false,
  ),
  SettingsPageDef(
    id: 'plugins',
    label: 'Tiện ích mở rộng',
    description: 'Quản lý và kích hoạt các plugin mở rộng chức năng hệ thống từ plugins/.',
    icon: puzzleGlyph,
    activeIcon: plugGlyph,
    needsKey: false,
  ),
  SettingsPageDef(
    id: 'mcp',
    label: 'Kết nối MCP',
    description: 'Quản lý kết nối các máy chủ Model Context Protocol nạp từ config/mcp_config.json.',
    icon: boxesGlyph,
    activeIcon: networkGlyph,
    needsKey: false,
  ),
  SettingsPageDef(
    id: 'graphfy',
    label: 'Bản đồ mã',
    description: 'Bản đồ cấu trúc JARVIS tự sinh từ code: module nào gọi module nào, và mọi chỗ gọi LLM.',
    icon: workflowGlyph,
    activeIcon: gitForkGlyph,
    needsKey: false,
  ),
  SettingsPageDef(
    id: 'info',
    label: 'Thông tin',
    description: 'Kiến trúc hệ thống, hướng dẫn sử dụng và tài liệu chi tiết từ README.md.',
    icon: bookOpenGlyph,
    activeIcon: infoGlyph,
    needsKey: false,
  ),
];

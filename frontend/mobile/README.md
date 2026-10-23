# JARVIS Mobile

Ứng dụng di động Flutter (iOS + Android) mang trải nghiệm JARVIS WebUI lên điện thoại.

## Tính năng
- **Trò chuyện thời gian thực**: WebSocket 2 chiều với streaming markdown, island trạng thái, status orb và capsule controls.
- **Giọng nói tiếng Việt**: Nhận diện giọng nói STT (`vi_VN` hoặc Whisper fallback qua `/api/stt`) và phát âm thanh TTS streaming (`pcm16le` / chunk encoded).
- **Cài đặt & Cấu hình**: Đầy đủ 16 trang cấu hình, quản lý kết nối server, quản lý bộ nhớ (/api/memory-control), nhật ký hệ thống, danh mục công cụ, MCP servers và bản đồ module.
- **Đăng nhập & Xác thực**: Màn hình Auth Gate 2 tab (Thành viên / Quản trị), cô lập dữ liệu theo người dùng, hỗ trợ token bearer cho API và WebSocket. Bộ nhớ truy cập trực tiếp bằng phiên Auth Gate; Nhật ký chỉ dành cho admin.
- **Phân quyền người dùng & Cài đặt**: Tự động ẩn trang lời nhắc hệ thống, Nhật ký và các danh mục admin đối với tài khoản Thành viên; Quản trị viên toàn quyền quản lý tài khoản và 8 danh mục bộ nhớ.
- **Ghi nhớ trạng thái Cài đặt**: Tự động lưu và khôi phục trang cài đặt cuối cùng, tab nhật ký và danh mục bộ nhớ đang mở.
- **Xóa phiên chat & Quản lý người dùng**: Hỗ trợ xóa lịch sử từng phiên hội thoại và xóa tài khoản thành viên trực tiếp trong cài đặt.
- **Badge trong tài liệu**: badge Shields dùng endpoint PNG tương đương, cao 20 px để chữ không bị phóng to/cắt trên app. SVG từ nguồn khác vẫn dùng `flutter_svg`, giữ kích thước gốc và xếp cùng dòng.

## Phiên chat

- Nút ngôi nhà ở góc trái mở ngăn kéo phiên, chia nhóm Hôm nay / Hôm qua / Cũ hơn. Chọn phiên để đọc lại và chat tiếp; **Phiên mới** mở chat trống kèm lớp chào. **Bảng điều khiển** mở từ đáy ngăn phiên; control chỉ giữ nút thanh nhập, TTS và mic.
- ID phiên do server cấp, chỉ giữ trong bộ nhớ app. Socket nối lại dùng phiên đã xác nhận; phiên chỉ xuất hiện sau tin nhắn đầu tiên.
- Khóa đổi phiên và tạo phiên mới khi LLM đang chạy, TTS đang đọc hoặc audio đang phát. **Bảng điều khiển** vẫn mở được.
- **Nhật ký** chỉ dành cho admin, xem/xóa theo phiên, có tên phiên, chủ phiên và bộ lọc người dùng. Thành viên không thấy trang Nhật ký hoặc Prompts.

## Cài đặt & Build Local

### Yêu cầu
- Flutter SDK 3.47+ (Dart 3.13+)
- JDK 21 (ví dụ JetBrains Runtime: `flutter config --jdk-dir="<path_to_jdk21>"`)
- Android SDK (Platform 35, Build-Tools 34+)

### Cài đặt dependencies
```powershell
cd mobile
rtk flutter pub get
```

### Kiểm thử & Phân tích
```powershell
rtk flutter test
rtk flutter analyze
```

### Build Android APK Debug
```powershell
rtk flutter build apk --debug --android-skip-build-dependency-validation
```
File APK xuất ra tại:
`mobile/build/app/outputs/flutter-apk/app-debug.apk`

## Shorebird: giữ font icon ổn định giữa release và patch

Flutter mặc định chỉ đóng gói các glyph đang dùng. Thêm hoặc bỏ icon có thể làm thay đổi `lucide.ttf`, trong khi Shorebird không đưa thay đổi font vào patch. Dùng `--no-tree-shake-icons` cho **cả release nền và mọi patch** để giữ nguyên font khi danh sách icon thay đổi; kích thước app sẽ tăng do giữ đủ glyph. Giữ cùng phiên bản `lucide_icons_flutter` trong `pubspec.lock` giữa release và patch.

Release cũ đã tree-shake font phải được thay bằng **release nền mới**, tăng version/build trong `pubspec.yaml` và cài APK/IPA mới một lần. Chỉ thêm cờ vào patch của release cũ không thể cập nhật font đã cài. Không dùng `--allow-asset-diffs` để che cảnh báo.

Chạy trong `mobile/` sau khi đã cập nhật version cho release mới:

```powershell
rtk shorebird release android --artifact apk -- --no-tree-shake-icons --android-skip-build-dependency-validation
```

Các lần vá sau dùng đúng phiên bản release nền đó, ví dụ thay `<release-version>` bằng version đã phát hành (`x.y.z+build`):

```powershell
rtk shorebird patch android --release-version <release-version> -- --no-tree-shake-icons --android-skip-build-dependency-validation
```

Workflow iOS trong `codemagic.yaml` cũng truyền cùng cờ cho release và patch. Thay đổi font/package/asset thật sự vẫn cần release mới; cờ này chỉ loại bỏ khác biệt do tree-shaking icon.

## Build iOS qua Codemagic (Không cần Mac)
1. Đẩy repository lên GitHub.
2. Đăng nhập [Codemagic](https://codemagic.io), thêm ứng dụng từ repo GitHub, chọn cấu hình từ file `codemagic.yaml` ở gốc repo.
3. Kích hoạt workflow `ios-unsigned`.
4. Tải file `JARVIS-unsigned.ipa` từ mục Artifacts.
5. Cài đặt vào iPhone bằng [Sideloadly](https://sideloadly.io) hoặc AltStore bằng Apple ID miễn phí (ký lại sau 7 ngày).

## Kết nối Server
- Trong app, vào **Cài đặt** (biểu tượng bánh răng) → **Kết nối & API**.
- Nhập địa chỉ server JARVIS (ví dụ `http://192.168.1.100:8000` hoặc địa chỉ IP Tailscale `http://100.x.y.z:8000`).
- App sẽ tự động kiểm tra kết nối qua `/api/health/detailed` và kết nối WebSocket `/ws/voice`.
- Bật Tailscale trên điện thoại nếu bạn muốn trò chuyện với JARVIS từ xa ngoài mạng gia đình.

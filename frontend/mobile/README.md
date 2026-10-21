# JARVIS Mobile

Ứng dụng di động Flutter (iOS + Android) mang trải nghiệm JARVIS WebUI lên điện thoại.

## Tính năng
- **Trò chuyện thời gian thực**: WebSocket 2 chiều với streaming markdown, island trạng thái, status orb và capsule controls.
- **Giọng nói tiếng Việt**: Nhận diện giọng nói STT (`vi_VN` hoặc Whisper fallback qua `/api/stt`) và phát âm thanh TTS streaming (`pcm16le` / chunk encoded).
- **Cài đặt & Cấu hình**: Đầy đủ 16 trang cấu hình, quản lý kết nối server, quản lý bộ nhớ (/api/memory-control), nhật ký hệ thống, danh mục công cụ, MCP servers và bản đồ module.
- **Đăng nhập & Xác thực**: Màn hình Auth Gate 2 tab (Thành viên / Quản trị), cô lập dữ liệu theo người dùng, hỗ trợ token bearer cho API và WebSocket. Loại bỏ màn hình khóa phụ trong Cài đặt: Bộ nhớ và Nhật ký truy cập trực tiếp bằng phiên Auth Gate tương tự frontend web mới.
- **Phân quyền người dùng & Cài đặt**: Tự động ẩn trang lời nhắc hệ thống và các danh mục admin đối với tài khoản Thành viên; Quản trị viên toàn quyền quản lý tài khoản và 8 danh mục bộ nhớ.
- **Ghi nhớ trạng thái Cài đặt**: Tự động lưu và khôi phục trang cài đặt cuối cùng, tab nhật ký, chế độ xem phiên chat và danh mục bộ nhớ đang mở.
- **Xóa phiên chat & Quản lý người dùng**: Hỗ trợ xóa lịch sử từng phiên hội thoại và xóa tài khoản thành viên trực tiếp trong cài đặt.

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

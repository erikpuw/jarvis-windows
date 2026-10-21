# JARVIS

<div align="center">

**Just A Rather Very Intelligent System**  
*Trợ lý AI đa năng, giọng nói tiếng Việt, bảo mật đa người dùng và hoàn toàn cục bộ (Local-First).*

**Phiên bản:** [v10.0.1](VERSION) · **Dự án gốc:** [Ethan](https://ethanplus.ai)

**Tiếng Việt** · [English](README.en.md)

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![Frontend](https://img.shields.io/badge/Frontend-Vite%20%7C%20Three.js-646CFF.svg)](https://vitejs.dev/)
[![Tests](https://img.shields.io/badge/Tests-1060%2B%20Passed-brightgreen.svg)]()
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D6.svg)]()
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

---

## 📌 Giới thiệu

**JARVIS** là hệ thống trợ lý AI chạy cục bộ trên máy tính cá nhân (Windows), kết nối trực tiếp với mô hình ngôn ngữ lớn (LLM) qua `llama.cpp` (API chuẩn OpenAI). JARVIS không phụ thuộc vào dịch vụ đám mây bên thứ ba cho dữ liệu cá nhân: toàn bộ lịch sử trò chuyện, tài liệu tri thức, nhật ký tập luyện và phong cách tự học đều được lưu trữ an toàn trong SQLite và Obsidian Vault cục bộ.

Hệ thống được thiết kế theo kiến trúc **định tuyến công cụ phẳng (Flat Tool Routing)**, hỗ trợ mô hình quyết định chuyên biệt **Jev Fast-Path (0.8B)** giúp phản hồi hội thoại siêu tốc, cùng cơ chế **phân quyền đa người dùng (Multi-User RBAC)** cách ly dữ liệu triệt để giữa Quản trị viên (Admin) và Thành viên (Member).

---

## ✨ Tính năng nổi bật

### 1. Định tuyến công cụ phẳng & Jev Fast-Path
- **Quyết định không nhân cách (Grammar JSON)**: Ép cấu trúc đầu ra `{"tool", "say", "args"}` qua grammar của `llama.cpp`, loại bỏ hoàn toàn hiện tượng ảo giác (hallucination) khi gọi công cụ.
- **Jev Fast-Path Chat Bypass**: Mô hình quyết định chuyên biệt `Jev-Style-0.8B-Decision-v3` (GGUF) chạy thường trực trên cổng 8083 hoặc in-process. Với các câu giao tiếp thông thường (chào hỏi, tâm sự, bách khoa), Jev kích hoạt Fast-path bỏ qua vòng chọn tool của LLM chính, giảm ngay ~3.5 giây độ trễ và trả lời trực tiếp.
- **Lối tắt linh hoạt**: Hỗ trợ gọi nhanh công cụ bằng tiền tố `/tên_tool`, nhắc lệnh `@tên_tool` hoặc phân tích nhanh tệp đính kèm.

### 2. Bảo mật đa người dùng & Phân quyền chặt chẽ (RBAC)
- **Tách biệt Admin & Member**: Bảng `users` trong cơ sở dữ liệu định danh từng người dùng.
- **MCP Gmail Admin-only**: Chặn truy cập hòm thư Gmail của Admin ở mọi tầng (MCP Hub, Tool Registry, Tool Schema, Slash Commands, REST API) đối với tài khoản Member.
- **Bảo vệ Prompt hệ thống**: Toàn bộ chỉ dẫn hệ thống (`prompt/jarvis.md`) được bảo vệ bằng rào chắn Admin; Member không có quyền đọc hay sửa.
- **Telegram Bot đa người dùng**: Hỗ trợ liên kết tài khoản an toàn qua lệnh `/link <token>` hoặc cấu hình `telegram_chat_id`. Nhận diện tự động quyền hạn, chặn truy cập trái phép và cách ly hoàn toàn lịch sử chat giữa các người dùng Telegram.

### 3. Tự học & Tiến hóa nhận thức độc lập (Learning & Evolution)
- **Học có chọn lọc (Learning Engine)**: Chỉ ghi nhận bài học khi người dùng hướng dẫn rõ ràng ("ghi nhớ", "từ giờ", "lần sau dùng..."). Không tự suy diễn từ câu chuyện phiếm.
- **Tiến hóa phong cách (Evolution Engine)**: Tự động tổng hợp và tinh chỉnh các quy tắc giao tiếp thành tệp `STYLE.md`.
- **Cách ly dữ liệu người dùng tuyệt đối**: Bài học, sở thích và tiến hóa của Thành viên được lưu trữ và chiếu riêng vào `data/users/{user_id}/` (`Learning.md`, `Preferences.md`, `STYLE.md`, `Evolution.md`), hoàn toàn không ảnh hưởng hay ghi đè lên dữ liệu của Admin.

### 4. Kho Tri Thức Cục Bộ & RAG (`@rag`)
- **Truy xuất ngữ nghĩa đa tầng (Dense Retrieval + FTS5)**: Sử dụng mô hình `EmbeddingGemma 2` (768d) để lập chỉ mục và tìm kiếm nội dung tài liệu.
- **Đồng bộ Obsidian Vault**: Tự động giám sát thư mục `data/wiki/Documents/`, nhận diện và lập chỉ mục tự động khi thêm/sửa ghi chú `.md`, tệp PDF, DOCX, TXT.
- **Stream thời gian thực**: Trả lời dạng stream mượt mà, trích dẫn rõ ràng nguồn tài liệu và tự động làm sạch ký tự rác.

### 5. Trợ lý Thể hình & Dinh dưỡng Cục bộ (`@gym`)
- Quản lý hồ sơ tập luyện cá nhân độc lập cho từng người dùng.
- Tự động ghi nhận bài tập, số hiệp, mức tạ, tính toán volume tập luyện và ước lượng 1RM.
- Theo dõi cân nặng hàng ngày, nhắc nhở thói quen uống nước, tư vấn dinh dưỡng theo khuyến nghị WHO.
- Tự động đồng bộ nhật ký ra Obsidian Wiki (`data/wiki/Gym/`).

### 6. So sánh giá siêu thị & Tra cứu dược phẩm
- **So sánh giá bách hóa**: Tra cứu đồng thời giá các mặt hàng thực phẩm, gia dụng từ các chuỗi bán lẻ lớn: Bách Hóa Xanh, Co.op Online, WinMart, LOTTE Mart, Emart.
- **Tra cứu công nghệ**: Tìm kiếm giá điện thoại, laptop, linh kiện từ CellphoneS, FPT Shop, Thế Giới Di Động với bộ lọc loại bỏ phụ kiện trôi.
- **Tra cứu dược phẩm (`search_medicine`)**: Bóc tách dữ liệu thời gian thực từ 3 chuỗi nhà thuốc lớn: Nhà thuốc Long Châu, An Khang và Pharmacity; hiển thị phân loại, khoảng giá và lời nhắc an toàn y tế.

### 7. Tin tức, Đọc bài sạch & Tiện ích thường ngày
- **Bóc tách bài viết sạch (Reader Card)**: Tự động loại bỏ quảng cáo, menu rác từ các trang báo thông qua Trafilatura, hiển thị khung đọc nhanh không xao nhãng.
- **Thời tiết & Lịch vạn niên**: Dự báo thời tiết thời gian thực (Báo Mới, Open-Meteo, wttr.in), cảnh báo mưa theo giờ, tra cứu ngày âm lịch và ngày hoàng đạo.
- **Kiểm soát Windows & Thị giác máy tính**: Hỗ trợ chụp màn hình (`read_screen`), phân tích hình ảnh đính kèm (`read_image`), và điều khiển ứng dụng Windows an toàn.

---

## 🏗️ Kiến trúc hệ thống

```text
┌────────────────────────────────────────────────────────┐
│               Giao diện người dùng (Clients)           │
│   Web HUD (Three.js/Vite)  ·  Telegram Bot  ·  Mobile  │
└──────────────────────────┬─────────────────────────────┘
                           │ HTTP / WebSocket
┌──────────────────────────▼─────────────────────────────┐
│                 FastAPI Server & Gateway               │
│  - Phân quyền (Auth & RBAC: Admin vs Member)           │
│  - Quản lý phiên hội thoại & WebSocket Streaming       │
└──────────────┬──────────────────────────┬──────────────┘
               │                          │
┌──────────────▼─────────────┐ ┌──────────▼──────────────┐
│       Jev Fast-Path        │ │  Vòng lặp Turn Loop     │
│  (Chat tức thì, bypass LLM)│ │  - Vòng 1: Chọn Tool    │
└────────────────────────────┘ │  - Vòng 2: Phản hồi     │
                               └──────────┬──────────────┘
                                          │
       ┌──────────────────────────────────┴──────────────────────────────────┐
       │                                                                     │
┌──────▼─────────────────────┐ ┌──────────────────────────┐ ┌────────────────▼───────────────┐
│     Hệ thống Công cụ       │ │   Bộ nhớ & Tiến hóa      │ │     Mô hình & Dịch vụ Local     │
│ - RAG (@rag, Documents)    │ │ - SQLite / FTS5          │ │ - LLM / llama.cpp (:8080)       │
│ - Gym Tracker (@gym)       │ │ - Obsidian Wiki Vault    │ │ - Embedding Server (:8081)      │
│ - Siêu thị / Dược phẩm     │ │ - Learning & STYLE.md    │ │ - Jev Fast-Path Engine (:8083)  │
│ - Windows Vision / Control │ │ - Cách ly data/users/    │ │ - Voice TTS (Edge / VieNeu)     │
│ - MCP Hub (Gmail...)       │ │ - Dream Cycle / Self-Heal│ │                                 │
└────────────────────────────┘ └──────────────────────────┘ └─────────────────────────────────┘
```

---

## 🚀 Cài đặt và cấu hình

### Yêu cầu

- Windows 10/11 64-bit, Python 3.11+, Node.js và Chrome.
- llama.cpp server tương thích OpenAI API: LLM mặc định ở cổng `8080`, embedding ở `8081`.
- `yt-dlp` trong PATH nếu dùng tìm kiếm/phát nội dung YouTube.
- OpenSSL để tạo chứng chỉ HTTPS local.

### Cài và chạy

```powershell
git clone https://github.com/erikpuw/jarvis-windows.git
cd jarvis-windows
pip install -r requirements.txt
cd frontend; npm install; cd ..
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj '/CN=localhost'
```

Khởi động llama.cpp trước, sau đó chạy backend và frontend ở các terminal riêng:

```powershell
python server.py --ssl
```

```powershell
cd frontend
npm run dev
```

Mở `https://localhost:8340`. Nếu dùng VieNeu streaming, chạy thêm `python run_vieneu.py` ở terminal riêng; nếu không, dùng Edge-TTS.

Nếu chạy thêm mô hình quyết định chuyên biệt Jev Fast-Path:
```powershell
python run_jev.py --cpu
```

### Cấu hình `.env`

Sao chép tệp mẫu và cấu hình:

```powershell
copy .env.example .env
```

Các biến thường dùng:

| Biến | Mục đích |
|---|---|
| `LOCAL_URL`, `LOCAL_API_KEY`, `LOCAL_MODEL` | Endpoint, khóa và tên model LLM local. |
| `LOCAL_EMBED_URL`, `LOCAL_EMBED_MODEL` | Endpoint và model embedding cho RAG và learning. |
| `EDGE_TTS_ENABLED`, `VIENEU_TTS_ENABLED` | Chọn engine đọc tiếng Việt; chỉ bật một engine. |
| `USER_NAME`, `HONORIFIC` | Tên và cách xưng hô; có thể chỉnh trong Settings. |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_IDS` | Bật và giới hạn Telegram bot. |
| `JARVIS_CORS_ORIGINS` | Các origin trình duyệt được phép kết nối. Không dùng `*`. |
| `RAG_WATCH_FOLDER` | Thư mục watcher tự lập chỉ mục, mặc định `data/documents`. |
| `MEMORY_PASSWORD` | Bảo vệ các trang Memory và Logs trong Settings. |
| `DREAM_ENABLED` | Bật/tắt Dream Cycle. |

Giá trị mặc định và các biến bổ sung nằm trong `.env.example`; không đưa khóa bí mật vào README hoặc commit.

Truy cập từ xa qua Tailscale: cài Tailscale trên máy chạy JARVIS và thiết bị truy cập, mở frontend cho mạng bằng `npm run dev -- --host`, sau đó thêm origin Tailscale của máy chủ vào `JARVIS_CORS_ORIGINS`. Không cần mở cổng router.

---

## 🧪 Kiểm thử & Đảm bảo chất lượng

Dự án được bao phủ kiểm thử tự động toàn diện với hơn **1.060 bài test**:

```powershell
# Chạy toàn bộ test suite backend
python -m pytest tests/ -q

# Kiểm tra tính toàn vẹn kiểu dữ liệu Frontend (TypeScript)
npx tsc --noEmit -p frontend/tsconfig.json

# Kiểm tra bộ nhớ và sức khỏe mô hình TTS VieNeu (nếu sử dụng)
python -m pytest tests/test_vieneu_health_and_memory.py -v
```

---

## 🔒 Lời cảm ơn, Bản quyền & Tuyên bố miễn trừ

- **Dự án gốc**: Được phát triển, mở rộng và tùy biến sâu từ nền tảng **[Ethan](https://ethanplus.ai)**.
- **Giấy phép**: Phát hành theo giấy phép [MIT License](LICENSE).
- Đây là dự án trợ lý cá nhân mã nguồn mở độc lập, không liên kết với Marvel Entertainment, The Walt Disney Company hay bất kỳ tổ chức thương mại nào. Tên gọi JARVIS được sử dụng như một nguồn cảm hứng sáng tạo công nghệ.

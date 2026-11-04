# JARVIS

<div align="center">

**Just A Rather Very Intelligent System**  
*Trợ lý AI đa năng, giọng nói tiếng Việt, bảo mật đa người dùng và hoàn toàn cục bộ (Local-First).*

**Dự án:** JARVIS · **Phiên bản:** [v10.0.1](VERSION)

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

**JARVIS** là dự án trợ lý AI độc lập, chạy cục bộ trên máy tính cá nhân (Windows), kết nối trực tiếp với mô hình ngôn ngữ lớn (LLM) qua `llama.cpp` (API chuẩn OpenAI). JARVIS không phụ thuộc vào dịch vụ đám mây bên thứ ba cho dữ liệu cá nhân: toàn bộ lịch sử trò chuyện, tài liệu tri thức, nhật ký tập luyện và phong cách tự học đều được lưu trữ an toàn trong SQLite và Obsidian Vault cục bộ.

Hệ thống được thiết kế theo kiến trúc **định tuyến công cụ phẳng (Flat Tool Routing)**, dùng LLM chính để quyết định chat/công cụ, cùng cơ chế **phân quyền đa người dùng (Multi-User RBAC)** cách ly dữ liệu triệt để giữa Quản trị viên (Admin) và Thành viên (Member).

---

## ✨ Tính năng nổi bật

### 1. Jev chọn công cụ, Gemma điền tham số và trả lời
- **Gemma4 & Grammar JSON**: lượt thường chỉ dùng Gemma điền tham số khi code chưa dựng được, trong schema `{tool đã chọn, none}`. Grammar ràng buộc cấu trúc; code kiểm tra quyền, tên tool và tham số trước thực thi.
- **Tách cấu hình chọn tool/trả lời**: vòng grammar giữ think budget 128; vòng trả lời vẫn bật think nhưng không gửi grammar hay giới hạn think 128. Tổng đầu ra mỗi lượt vẫn giới hạn 1500 token. Jarvis bỏ `reasoning_content`; nếu phát hiện khối tự phân tích trong `content`, chat và TTS chỉ tiếp tục khi có dấu `Final Answer:`/`Final Response:`/`Câu trả lời cuối cùng:`. Không tự coi văn xuôi sau khối đó là câu trả lời. Lọc văn bản không bảo đảm nhận diện mọi cách diễn đạt suy nghĩ không có dấu phân cách.
- **Fast-path Workflow & Skill**: Giữ thứ tự ưu tiên replay workflow đã lưu và skill phù hợp. Lượt thường còn lại đi qua guard và Jev; tệp đính kèm giữ vòng xử lý riêng.
- **Lối tắt linh hoạt**: Giữ `/tên_tool`, `@tên_tool`, `@rag` và xử lý tệp đính kèm như hiện tại.
- **Jev-Style 2B (một nơi chọn tool cho lượt thường)**: model **v4 Q4_K_M**, dùng `jev-score-v2`, chỉ dẫn riêng trong `engine/turn/jev/jev_route.json`; giữ nhiệt độ choice đã hiệu chuẩn 0,770. Guard phủ định/trần thuật chạy trước Jev. Các câu còn lại hỏi Jev một lần: chỉ nhận top-1 là tool được phép, điểm ≥ `TAU=0.8`, qua guard đối tượng và không trái correction đã đủ điều kiện. Code dựng args; nếu thiếu thì Gemma chỉ điền args cho `{tool đó, none}`. Code kiểm tra lại tool/args trước thực thi; xong một tool là trả lời, không chọn thêm. Jev chọn chat, điểm thấp, lỗi, timeout hoặc dữ liệu không hợp lệ đều không mở vòng Gemma chọn tool. Đã bỏ `JEV_ONLY`, cue đổi tool, nhánh tool hạng hai và vòng chọn lại sau veto. Lệnh `/tool`, `@tool`, workflow ghim, skill và tệp vẫn đi đường riêng có kiểm tra quyền/args. Corrections của lượt thường chỉ chặn lựa chọn sai, không ép sang tool khác.
  - `TAU=0.8` là ngưỡng hiện có, **chưa hiệu chuẩn lại trên lịch sử mới**; không bảo đảm điểm cao là đúng. Kiểm chứng trực tiếp ngày 2026-11-05: câu “tôi đang xem hoạt động ra sao” bị Jev chọn `read_screen` 0,852 (sai), nên guard phải chặn trước khi hỏi Jev. Bốn lượt đo mất 6,35–7,79 giây/lượt; bản sửa giảm số lượt gọi, không làm model suy luận nhanh hơn.
  - `logs/jev_picks.jsonl` ghi top-3, lựa chọn vòng chạy, hành động cuối và `blocked` (gồm chặn bởi ngưỡng/guard). `agree` chỉ là khớp lựa chọn, không phải độ chính xác. Câu được guard chặn trước Jev không có điểm Jev.
  - Chạy `python run_jev.py` (CPU) hoặc `python run_jev.py --gpu`, cổng 8083; health `/jev/health`. Runner ở `E:\Run_Model\jev-run-v2` hoặc `jev-run-v2-gpu`, GGUF ở `E:\Run_Model\model`; cấu hình qua `JEV_RUN_DIR`, `JEV_GGUF`, `JEV_PORT`. Khởi động lại backend JARVIS để nạp thay đổi routing; không cần sửa GGUF.

### 2. Bảo mật đa người dùng & Phân quyền chặt chẽ (RBAC)
- **Tách biệt Admin & Member**: Bảng `users` trong cơ sở dữ liệu định danh từng người dùng.
- **MCP Gmail Admin-only**: Chặn truy cập hòm thư Gmail của Admin ở mọi tầng (MCP Hub, Tool Registry, Tool Schema, Slash Commands, REST API) đối với tài khoản Member. Với Member, `@check_mail`, `/check_mail` và skill có bước mail coi như không có tool này (không báo "chỉ Admin").
- **Bảo vệ Prompt hệ thống**: Toàn bộ chỉ dẫn hệ thống (`prompt/jarvis.md`) được bảo vệ bằng rào chắn Admin; Member không có quyền đọc hay sửa.
- **Telegram Bot đa người dùng**: Hỗ trợ liên kết tài khoản an toàn qua lệnh `/link <token>` hoặc cấu hình `telegram_chat_id`. Nhận diện tự động quyền hạn, chặn truy cập trái phép và cách ly hoàn toàn lịch sử chat giữa các người dùng Telegram.

### 3. Tự học & Tiến hóa nhận thức độc lập (Learning & Evolution)
- **Học có chọn lọc (Learning Engine)**: Chỉ ghi nhận bài học khi người dùng hướng dẫn rõ ràng ("ghi nhớ", "từ giờ", "lần sau dùng..."). Không tự suy diễn từ câu chuyện phiếm.
- **Sửa công cụ dùng sai**: Ngay sau một lượt dùng tool, lời phản đối thường ("ơ kìa, tin tức mà, đâu có nghe nhạc") cũng được xét nhưng chỉ ghi `tool_fix`. Câu gốc lấy từ `outcomes`; lượt bị sửa đổi thành `failed`.
- **Tự học workflow có bằng chứng** (`engine/turn/outcome.py`): mỗi lượt tool ghi `outcomes`. Chỉ tạo/tăng workflow khi lượt thường (không @tool/skill/tệp, không trả lời câu hỏi), thành công, **một bước**, mọi tham số không-enum có trong câu ngài, và câu y hệt đã thành công **≥ 2 lần** với đúng tool + args, chưa từng đi tool khác, chưa bị ngài sửa tool; lượt replay không tính (không tự xác nhận). Workflow cũ vẫn phát lại khi câu khớp nguyên văn; không thêm lượt gọi model kiểm chứng và không đổi Choice/fast-path.
- **Tiến hóa phong cách (Evolution Engine)**: Tự động tổng hợp và tinh chỉnh các quy tắc giao tiếp thành tệp `STYLE.md`. Mỗi lần `STYLE.md` đổi, wiki `System/Evolution.md` ghi một khối theo ngày: luật thêm, luật bỏ, luật bị lọc kèm lý do.
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

### 8. Phiên chat & thanh bên
- **Thanh bên phiên (desktop)**: Bên trái có nút `＋ Phiên mới`, danh sách phiên của bạn nhóm theo `Hôm nay` / `Hôm qua` / `Cũ hơn`, và `⚙ Bảng điều khiển` ở cuối. Trên điện thoại, nút nhà mở thanh bên dạng ngăn kéo.
- **Mở phiên mới hoặc phiên cũ**: Mở app là một cuộc trò chuyện trống; phiên do server tạo (id `web-xxxxxxxx`, gắn với tài khoản đăng nhập) và xuất hiện sau tin nhắn đầu tiên. Chọn phiên cũ sẽ tải lại tin nhắn và tiếp tục (LLM nhận 20 tin gần nhất). Không đổi phiên khi LLM đang trả lời hoặc TTS đang đọc.
- **Tiêu đề phiên**: Lấy từ tin nhắn đầu tiên của bạn, cắt bằng code tối đa 48 ký tự, không dùng LLM.
- **WebSocket `/ws/voice` cần token**: Phải gửi `?token=` của tài khoản đã đăng nhập; thiếu hoặc sai token thì server đóng kết nối với mã 1008. Client không có token (app Flutter mobile, script) phải tự gửi tham số này.
- **Nhật ký (Settings)**: Lịch sử chat chỉ Admin xem, theo từng phiên (chủ phiên + tiêu đề, lọc theo user). Thành viên không còn thấy mục Nhật ký.
- **API**: `GET /api/sessions/mine` và `GET /api/sessions/mine/{id}` cho người dùng đăng nhập; `/api/conversations/sessions` và `/session/{id}` chỉ Admin.
- **Ảnh trong lịch sử chat** (`engine/core/chat_media.py`): khi lưu câu trả lời, mọi ảnh (poster phim, ảnh game, bìa YouTube, ảnh chụp màn hình, ảnh tool tạo) được tải/chép về `data/chat_media/<user_id>/<session_id>/`. Ảnh ngoài chỉ nhận `image/*`, tối đa 5 MB, chờ 10 giây; tải hỏng thì giữ link gốc. DB chỉ giữ tham chiếu (bảng `message_media`), nội dung tin trỏ `/api/media/<id>`; mở lại hay đổi phiên vẫn thấy ảnh, model không nhận ảnh. `/api/media/<id>` chỉ chủ tin nhắn và Admin xem được (chưa đăng nhập 401); `/api/media/local` cũng cần đăng nhập. Token được chép sang cookie `jarvis_token` để thẻ ảnh gửi kèm (cookie `Secure`: cần mở qua HTTPS hoặc localhost). Xoá tin (Dream 14 ngày, xoá bản ghi, xoá user) là xoá luôn ảnh. Bảng tool có `display=True` (poster phim, bìa game) được lưu kèm trước câu trả lời, nên mở lại lịch sử vẫn thấy nguyên bảng và ảnh.

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
│    Workflow / Skill       │ │  Vòng lặp Turn Loop     │
│  Replay / chuỗi công cụ   │ │  - Vòng 1: Chọn Tool    │
└────────────────────────────┘ │  - Vòng 2: Phản hồi     │
                               └──────────┬──────────────┘
                                          │
       ┌──────────────────────────────────┴──────────────────────────────────┐
       │                                                                     │
┌──────▼─────────────────────┐ ┌──────────────────────────┐ ┌────────────────▼───────────────┐
│     Hệ thống Công cụ       │ │   Bộ nhớ & Tiến hóa      │ │     Mô hình & Dịch vụ Local     │
│ - RAG (@rag, Documents)    │ │ - SQLite / FTS5          │ │ - LLM / llama.cpp (:8080)       │
│ - Gym Tracker (@gym)       │ │ - Obsidian Wiki Vault    │ │ - Embedding Server (:8081)      │
│ - Siêu thị / Dược phẩm     │ │ - Learning & STYLE.md    │ │                                │
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
- `npm install -g agent-desktop` nếu dùng `/win_control <việc cần làm>` (điều khiển ứng dụng Windows qua cây accessibility, chạy nền, không chiếm chuột; chuột ảo "JARVIS" hiện trên màn hình khi máy đang thao tác). Backend tự tìm exe native của gói npm hoặc dùng `AGENT_DESKTOP_PATH`. agent-desktop lưu trạng thái trong `C:\ProgramData\agent-desktop` và `~\.agent-desktop`: chạy JARVIS cùng mức quyền (thường hoặc Administrator) với lần đầu dùng nó, nếu không các thao tác sẽ báo lỗi chủ sở hữu thư mục.

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

## 🔒 Giấy phép & Tuyên bố miễn trừ

- **Giấy phép**: Phát hành theo giấy phép [MIT License](LICENSE).
- Đây là dự án trợ lý cá nhân mã nguồn mở độc lập, không liên kết với Marvel Entertainment, The Walt Disney Company hay bất kỳ tổ chức thương mại nào. Tên gọi JARVIS được sử dụng như một nguồn cảm hứng sáng tạo công nghệ.

# JARVIS

**Tiếng Việt** | [English](README.en.md)

**Just A Rather Very Intelligent System** — trợ lý AI giọng nói tiếng Việt, chạy local trên Windows.

**Phiên bản:** xem file [`VERSION`](VERSION) (nguồn duy nhất) · [Nhật ký phiên bản](CHANGELOG.md) · **Dự án gốc:** [Ethan](https://ethanplus.ai)

> [!IMPORTANT]
> **Dự án do người Việt xây dựng cho người dùng tiếng Việt và chỉ hỗ trợ tiếng Việt.** Không có công tắc đổi ngôn ngữ. Prompt, nhận dạng giọng nói (`vi-VN`), giọng đọc, từ khoá khớp chuỗi trong code, test và chữ trên giao diện đều bằng tiếng Việt, nên nhập tiếng Anh thường không khớp. **Muốn dùng bằng tiếng Anh thì phải fork và chuyển đổi toàn bộ dự án**, không chỉ sửa `.env`: xem [Fork sang ngôn ngữ khác](#fork-sang-ngôn-ngữ-khác).

JARVIS dùng mô hình ngôn ngữ local để trò chuyện, xử lý yêu cầu và gọi công cụ trên máy. Hệ thống có WebUI, giọng nói tiếng Việt, bộ nhớ hội thoại và hệ thống công cụ phẳng đa năng. Dữ liệu bộ nhớ chính được lưu local.

## Mục lục

- [Tính năng](#tính-năng)
- [Vòng lặp sinh có ràng buộc](#vòng-lặp-sinh-có-ràng-buộc-2026-10-12)
- [Lối tắt và công cụ chuyên biệt](#lối-tắt-và-công-cụ-chuyên-biệt)
- [Bộ nhớ và tự học](#bộ-nhớ-và-tự-học)
- [Giao diện và tích hợp](#giao-diện-và-tích-hợp)
- [Kiến trúc](#kiến-trúc)
- [Cài đặt và cấu hình](#cài-đặt-và-cấu-hình)
- [Fork sang ngôn ngữ khác](#fork-sang-ngôn-ngữ-khác)
- [API, kiểm thử và bảo mật](#api-kiểm-thử-và-bảo-mật)
- [Phiên bản và giấy phép](#phiên-bản-và-giấy-phép)

## Tính năng

| Hệ thống | Chức năng |
|---|---|
| **LLM local** | Kết nối llama.cpp qua API tương thích OpenAI; kiểm tra kết nối cổng 8080 (LLM) và 8081 (Embed), giữ trạng thái chờ kết nối ngăn chặn spam lỗi khi máy chủ chưa mở. |
| **Giọng nói tiếng Việt** | Nhận giọng nói trên trình duyệt (`vi-VN`); đọc câu trả lời bằng Edge-TTS hoặc VieNeu streaming qua máy chủ stream_TTS cổng 8082 (kiểm tra kết nối và giữ trạng thái chờ kết nối khi chưa mở). Chỉ bật một engine TTS tại một thời điểm. |
| **Định tuyến tool phẳng** | Quyết định không nhân cách (Gemma 4 chọn tool & điền tham số tối đa 3 vòng) → Trả lời có nhân cách JARVIS; hỗ trợ lối tắt code, câu chờ tự động. |
| **Xử lý tệp đính kèm** | Tự động nhận diện định dạng tệp (PDF, văn bản, Office, ảnh...) và liên kết với công cụ xử lý tương ứng (`file_tools_for`). |
| **RAG** | Tìm kiếm tài liệu local bằng embedding, BM25 và kết hợp thứ hạng; phản hồi stream text thời gian thực, lọc ký tự rác tự động và trích dẫn nguồn. |
| **Bộ nhớ** | SQLite/FTS5 lưu hội thoại, bài học, sở thích và kết quả công cụ. Memory Center trong Settings quản lý dữ liệu. |
| **Theo dõi tập luyện** | Công cụ Gym nhớ hồ sơ đang chọn, chuẩn hóa múi giờ địa phương, hỗ trợ câu lệnh tự nhiên, tự động đồng bộ nhật ký ra Obsidian Wiki (`data/wiki/Gym/`, cách ly khỏi vector AI) và quản lý trực quan qua tab Gym Memory trong Memory Control Center. |
| **Tự học và tác vụ nền** | Learning phản tư, Evolution, Dream Cycle và Self-Healing hoạt động nền khi máy rảnh; thao tác sửa mã cần người dùng duyệt. |
| **Bảo vệ đầu vào** | Lọc chỉ thị không tin cậy, kiểm tra Origin/IP cho API và WebSocket, giới hạn các hành động tiếp theo sau khi đọc nội dung ngoài. |

## Vòng lặp sinh có ràng buộc (2026-10-12)

Mỗi lượt: lối tắt code (tệp nén, `/tên_tool`, `@tên_tool`, `@rag`) → nếu không khớp, vòng lặp `engine/turn`:
- Vòng chọn tool (`prompt/jarvis.md` + `prompt/turn_tool.md` + danh mục công cụ): grammar của llama.cpp ép JSON
  `{"tool","say","args"}`. Gọi tool thì "say" là câu báo (🛠️ đứng trước, stream lên giao diện + TTS); code gửi
  `status: working` khi chạy tool, `thinking` khi model nghĩ, nối kết quả, lặp tối đa 4 vòng.
- `tool = "none"` → vòng trả lời bằng chữ thường (`prompt/jarvis.md` + `prompt/turn_answer.md`, không JSON, không
  danh mục công cụ): câu trả lời dài (thực đơn, tóm tắt tin) có nội dung thật thay vì câu hứa.
- Bảng của tool `display=True` do code hiện nguyên văn; vòng trả lời chỉ nhận xét. Tool đã tự tổng hợp (vision
  `read_screen`/`read_webcam`/`read_image`, `rag_ask`) cũng hiện nguyên văn, không bị tóm lại lần hai.
- Cổng chặn bằng code (`loop._NEEDS_WORD`): `read_screen` chỉ chạy khi câu nói tới "màn hình/screen",
  `system_status` khi hỏi CPU/RAM/ổ/tiến trình…; câu ngài kể việc mình đang xem/theo dõi thành trò chuyện, không
  hiện câu báo gọi tool. Nhờ thật mà không có các từ đó thì dùng `@read_screen` / `@system_status`.
- Vòng trả lời kẹt lặp một từ/cụm (≥ 7 lần) thì cắt và đóng kết nối để llama-server ngừng sinh.
- Kết quả tool vào vòng trả lời tối đa 8.000 ký tự; `search_news` tự chia đều cho mỗi bài để không mất bài cuối.
  Lịch sử: lượt gần nhất giữ 3.000 ký tự (kết quả tool + câu trả lời) để hỏi tiếp không mất nội dung, lượt cũ 300.
- Vòng trả lời đi từng câu qua `loop._breaks_promise`: câu hứa làm việc mà lượt đó không chạy công cụ, hoặc hứa
  nhắc/theo dõi/báo lại sau, bị bỏ và thay bằng một câu nói thật (prompt chỉ giảm bịa, code chặn).
- Luồng bước (flow island): Chọn công cụ → X, Chạy X, Trả lời.
- Mỗi lượt có tool ghi một dòng bảng `outcomes` (tools, câu, success/failed/partial, từng bước; `win_control` kèm
  thao tác cua). Lượt thành công mà mọi tham số lấy từ lời ngài thì lưu bảng `workflows` (`engine/turn/outcome.py`).
- Câu trùng nguyên văn (chữ thường, bỏ dấu câu) một câu đã lưu → phát lại chuỗi tool, bỏ vòng chọn tool.
  `win_control` phát lại thao tác cua theo cửa sổ + nhãn nút, vẫn hỏi xác nhận như thường; không khớp thì cua tự làm tiếp.
Mô tả tool: `prompt/tools/<tên>.md`. Thêm tool: hàm `@tool` trong `engine/tools/catalog/` + file `.md`.
Gợi ý `/` và `@` trên ô nhập sinh từ registry (`engine.turn.entry.mention_list`: `@rag` + mọi tool).
Spec: `docs/superpowers/specs/2026-10-12-turn-rebuild-design.md`.

### Xử lý tệp đính kèm

Vòng lặp chỉ đưa vào danh mục các công cụ tệp hợp với phần mở rộng của tệp:
- Tệp PDF, văn bản, bảng tính, Office: liên kết với RAG (`rag_tool`) hoặc OfficeCLI (`office_tool`).
- Hình ảnh (jpg, png, webp, bmp): liên kết với phóng to ảnh (`upscale_image`) hoặc phân tích ảnh (`read_image`).
- Tệp nén (zip): tự động giải nén an toàn và tìm tệp hỗ trợ bên trong.
Danh sách tool tệp được cấu hình trực tiếp qua thuộc tính `@tool(file_extensions=[...])` trong `engine/tools/catalog/`.

## Lối tắt và công cụ chuyên biệt

### Theo dõi tập luyện (`@gym`)

`@gym` là trợ lý thể hình và theo dõi tập luyện lưu trữ local an toàn:
- **Hướng dẫn lệnh & Điều hướng**: Gõ `@gym` không kèm nội dung để xem trạng thái hồ sơ hiện hành và toàn bộ bảng hướng dẫn lệnh tiếp theo.
- **Quản lý hồ sơ**: Tự động nhận diện lệnh tạo hoặc chọn hồ sơ bằng ngôn ngữ tự nhiên: `@gym tạo hồ sơ [Tên]` hoặc `@gym chọn hồ sơ [Tên]`.
- **Ghi nhận buổi tập**: `@gym vừa tập Bench Press 3 hiệp 10 reps 60kg` (tự động tính volume và ước tính 1RM).
- **Ghi nhận cân nặng**: `@gym hôm nay cân nặng 72kg` (lưu trữ theo ngày).
- **Tra cứu bài tập**: `@gym tìm bài tập ngực` (trả về danh sách bài tập kèm link YouTube xem kỹ thuật).
- **Thống kê & Lịch sử**: `@gym thống kê tiến độ` / `@gym lịch sử tập luyện`.
- **Tư vấn dinh dưỡng**: `@gym tư vấn dinh dưỡng tăng cơ` / `giảm mỡ` (theo khuyến nghị WHO).
- **Theo dõi thói quen**: `@gym hôm nay đã uống đủ 2 lít nước` / `@gym tiến độ thói quen`.

---

### Kho Tri Thức & Tài Liệu (`@rag`)

`@rag` là trợ lý tra cứu kho tri thức và phân tích tài liệu local đa định dạng (PDF, DOCX, TXT, v.v.):
- **Hướng dẫn lệnh**: Gõ `@rag` không kèm nội dung để xem ngay trạng thái kho tài liệu, số đoạn văn bản và bảng lệnh tra cứu.
- **Tra cứu tài liệu**: `@rag <câu hỏi>` (ví dụ: `@rag thực đơn tuần này`, `@rag bài tập ngực thứ hai`). Trả lời dạng **Stream text thời gian thực** kèm trích dẫn nguồn cụ thể.
- **Quản lý kho tài liệu**:
  - `@rag danh sách`: Liệt kê tài liệu trong kho (đánh số) và số đoạn văn bản đã trích xuất.
  - `@rag lưu` (kèm tệp đính kèm): copy tệp vào `data/wiki/Documents/`; bộ theo dõi tự nạp. Không có tệp đính kèm thì "lưu…" được hiểu là câu hỏi.
  - `@rag xóa <số thứ tự hoặc tên file>`: bỏ khỏi chỉ mục **và** chuyển tệp gốc vào `data/wiki/.trash/Documents/` (khôi phục bằng cách kéo lại). Chỉ xóa chỉ mục thì lần khởi động sau tệp bị nạp lại.
- **Một nguồn duy nhất**: thư mục `data/wiki/Documents/` (đổi bằng `RAG_WATCH_FOLDER`) nằm trong vault Obsidian nên Obsidian đọc được tệp gốc. Chỉ mục (`data/rag_index/rag_vectors.tq` + `rag_metadata.json`) dựng lại được từ thư mục này. Đính kèm tệp rồi hỏi một lần thì chỉ dùng tạm, không lưu. Đổi model embedding thì phải xóa hai tệp chỉ mục và `data/rag_watch.db` để nạp lại từ đầu.
- **Làm sạch dữ liệu tự động**: Tự động loại bỏ ký tự rác, null bytes (`\x00`), control characters và chuẩn hóa khoảng trắng/dấu gạch nối khi nạp tài liệu PDF/văn bản.

## Bộ nhớ và tự học

- **Nguồn dữ liệu:** `data/jarvis.db` (SQLite + FTS5). Obsidian Vault trong `data/wiki/` là bản chiếu để đọc.
- **Memory Center:** quản lý memories, learnings, workflow, kết quả công cụ và lịch sử. Đây là giao diện chính để xem/sửa dữ liệu bộ nhớ.
- **Learning:** đề xuất bài học từ hội thoại và kết quả tác vụ, phản biện với dữ liệu cũ rồi mới thêm/gộp/thay thế. Áp dụng cổng tín hiệu tường minh (Explicit Signal Gate): chỉ học khi có yêu cầu ghi nhớ, phàn nàn/cấm đoán hành vi hoặc sở thích cá nhân; loại bỏ 100% việc tự suy diễn từ hội thoại thông thường để không ghi nhớ lung tung.
- **Evolution:** lưu quy tắc phong cách đang áp dụng (`STYLE.md`) và nhật ký các đề xuất tiến hóa. Tự động khử trùng lặp theo chủ đề, loại bỏ luật nghiệp vụ lạc đề, gộp luật trùng ý và duy trì giới hạn tối đa 8 luật (không chứa luật xưng hô hay công cụ) để kiểm soát hành vi và chống phình context.
- **Dream Cycle:** chạy khi rảnh để tổng hợp/dọn dữ liệu cũ; có sao lưu trước khi gộp.
- **Self-Healing:** phân loại lỗi từ log và ghi nhận để xử lý; chỉ gọi quy trình sửa mã sau khi người dùng duyệt.
- **Nhiều phiên:** WebUI và Telegram có session riêng; lịch sử và trạng thái định tuyến tách theo phiên.

## Giao diện và tích hợp

Frontend dùng Vite, TypeScript và Three.js trong `frontend/`. WebUI gồm giao diện chat/HUD, Command Bar, trình phát media và Settings dashboard. Tính năng bản đồ (panel MapLibre, ghim vị trí, ranh giới hành chính) đã gỡ hẳn ngày 2026-10-13 (test `tests/test_map_removed.py`). Webcam chỉ còn khung nhỏ, không phóng toàn màn hình.

- Gõ `/` hoặc `@` trên Command Bar để gợi ý công cụ, lối tắt.
- Nút Cài đặt (Settings) trực tiếp trên thanh điều khiển (thay thế menu sổ dropdown); nút Khởi động lại hệ thống được đưa vào tab "Kết nối & API".
- Bong bóng chat hỗ trợ Markdown chuẩn GFM, tô màu cú pháp code block (highlight.js) kèm nhãn ngôn ngữ và nút sao chép, hiển thị bảng biểu cuộn responsive đồng bộ cùng Settings.
- Settings quản lý prompt, người dùng, kết nối, MCP, bộ nhớ, lịch sử và log.
- Telegram có thể dùng cùng backend; cấu hình `TELEGRAM_BOT_TOKEN` và `TELEGRAM_ALLOWED_CHAT_IDS`. Tự động nhận diện mất kết nối mạng/mất điện, tạm dừng polling chống spam log và tự kết nối lại khi có mạng.
- Mô tả công cụ nằm ở `prompt/tools/<tên>.md`; prompt cấu hình nằm trong `prompt/`.
- Skills, hooks và MCP mở rộng khả năng của hệ thống. Máy chủ MCP được cấu hình tại `config/mcp_config.json` và quản lý trong Settings.

## Kiến trúc

```text
WebUI / Telegram
       ↓ HTTP + WebSocket
FastAPI server → Router → Tools (Catalog)
       ↓                   ↓
SQLite + Memory Center     LLM / Embedding / Windows / Web
```

| Thành phần | Vị trí | Vai trò |
|---|---|---|
| Server và API | `server.py`, `engine/server/` | FastAPI, WebSocket, cài đặt, lịch sử và phân phối kết quả. |
| Vòng lặp hội thoại | `engine/turn/` | Lối tắt `/` `@`, vòng lặp sinh có ràng buộc `{say, tool, args}`, chạy tool, stream câu trả lời. |
| Công cụ | `engine/tools/` | Hệ thống tool phẳng (`engine/tools/catalog/`) thực hiện tác vụ chuyên biệt. |
| Prompt | `prompt/`, `engine/prompts/` | Nội dung chỉ dẫn và code lắp ghép ngữ cảnh. |
| Frontend | `frontend/src/` | Chat, HUD, điều khiển giọng nói và Settings. |
| Dữ liệu | `data/` | Database, tài liệu, wiki, log và dữ liệu người dùng. |

**Hiệu ứng `stream_start`** (`frontend/src/stream-loader.css/.ts`, `main.ts: STREAM_TEXT_AFTER_LOADER_MS`, test `frontend/e2e/stream-bounce.cjs`): 4 quả cầu nhỏ đang bay vòng khi chờ chữ; khi chữ tới, cả cụm **thu nhỏ về tâm** (không zoom) rồi tan trong 0,3 giây. Chữ đầu tiên chỉ bắt đầu hiện sau 0,2 giây, lúc 4 quả đã thu gần hết, nên thấy rõ chữ đầu. Vẫn là 4 quả riêng, vẫn bay vòng, giữ nguyên vị trí và kích thước.

**Trang Thông tin (README) và Settings không tràn ngang** (`frontend/src/markdown.ts`, `frontend/src/settings/styles.css`, test `frontend/e2e/settings-overflow.cjs`, `frontend/e2e/info-wrap.cjs`): mọi trang Settings gói gọn theo bề ngang ở 390/768/1280px; code nội tuyến ngắn trong README (`vi-VN`, `/check_system`) giữ nguyên một dòng, code rất dài vẫn tự ngắt, bảng cuộn trong khối của nó.

**Mép bot mượt trên PC** (`frontend/src/bot.ts: sides:"sprite"`, test `frontend/e2e/bot-edge.cjs`): thân bot dùng lát ảnh dựng sẵn có làm mịn (như iPhone/Safari), không dùng "vector" nữa vì chồng nhiều lát khử răng cưa làm viền lởm chởm ở màn hình 100%. Đo ở PC 100%: điểm mép đặc từ 26,5% xuống còn khoảng 4–9%.

**Bot linh vật làm trò khi chờ** (`frontend/src/bot.ts`, mặt giận `drawSulkFace` trong `frontend/src/bot-mouth.ts`, test `frontend/e2e/bot-tricks.cjs`): trong 30 giây rảnh (idle) trước khi ngủ, bot không chỉ nhìn quanh mà cứ 4–6,5 giây làm một trò: nhảy nhẹ lên, hoặc nảy co giãn (hai nhịp thấp, dẹt xuống rồi giãn dài); đã chờ 15 giây không ai đụng tới thì giận dỗi ~2,5 giây (quay mặt đi nhìn xuống, miệng hình "^", dán đúng emoji 💢 ở góc trên đầu, co giãn theo thân; dấu tự vẽ trước đó trông như vết sẹo: `drawSulkFace`), lần đầu sau 15 giây luôn là giận, sau đó nửa này nửa kia. Không làm trò khi đang gõ trong ô lệnh, khi JARVIS đang nghĩ/nói/làm việc, khi bật giảm chuyển động; người dùng chạm/bấm phím/đưa chuột lại gần thì hết giận ngay. Trò không tính là hoạt động: hết 30 giây vẫn ngủ.

**Xem thử hình dạng Bot Mascot (Command Bar) trong Cài đặt** (`frontend/src/bot.ts`, `frontend/src/settings/pages.ts`, `frontend/src/settings/index.ts`, `frontend/src/settings/styles.css`): tại tab Người dùng (`data-page="user"`), bảng chọn dạng lưới hiển thị 18 linh vật bot (`bot-avatars`) kèm canvas xem trước tĩnh; nhấp vào bot bất kỳ lập tức cập nhật hình dạng và màu sắc mascot trên thanh lệnh Command Bar (`#jarvis-bot`) trong phiên làm việc hiện tại mà không lưu vĩnh viễn (mặc định luôn là `Square`). Nút "Đặt lại mặc định" cho phép quay về Square nhanh chóng.

**Phiên chat không bị tách khi nối lại** (`frontend/src/ws.ts`, `engine/core/session_context.py: resolve_ws_session/resume_history`, `server.py`, test `frontend/e2e/ws-session.cjs`, `tests/test_ws_session_resume.py`): mỗi lần mở trang có một ID `web-xxxxxxxx`, gửi kèm URL WebSocket (`?session=`). iPhone thoát app rồi vào lại (socket nối lại, trang vẫn giữ bong bóng) thì server dùng lại đúng phiên đó và nạp lại lịch sử, nên lịch sử không bị tách ID và model không mất ngữ cảnh. Tải lại trang hoặc tab khác thì là phiên mới.

**Bảng trong bong bóng chat và bảng tool** (`frontend/src/style.css`, `engine/tools/shop_engine.py`, `engine/tools/search_engine.py`, test `frontend/e2e/chat-table-wrap.cjs`, `tests/test_tool_tables_markdown.py`): ô bảng chỉ xuống dòng ở dấu cách như GitHub (không còn "Đá/nh giá", "61.90/0đ" trên điện thoại), bảng rộng thì cuộn ngang trong khung. Tra giá chỉ đưa cột Đánh giá/Đã bán khi có số liệu. Giá thị trường: mỗi khối (tiêu đề, bảng, ghi chú) cách nhau dòng trống, không lấy được giá thì là câu thường thay vì hàng bảng lơ lửng; ví dụ trong quy tắc vòng 2 dùng đúng tiêu đề `####` như tool.

**Quầng sáng nút gửi** (`frontend/src/metal-halo.ts`, `.metal-glow` trong `style.css`, test `frontend/e2e/metal-glow.cjs`): chép thuật toán halo của `metal-fx` v2 (Libraries.dev, MIT) sang canvas 2D, không cần React: 4 nét chồng nhau có làm mờ + một chấm sáng nhỏ, canvas tràn ~43px quanh nút như bản gốc, sáng đầy trên mép vòng, một nửa ở ngoài, không lấn vào trong nút; độ sáng thấp (glowOpacity 0,3, chỗ đậm nhất ~67%). Nhịp 3 giây: 1 giây sáng dần, 1 giây giữ, 1 giây tắt dần; tắt hẳn rồi mới hiện ở chỗ ngẫu nhiên khác trên vòng (cách chỗ trước ≥ 60°), không xoay. **Màu lấy từ vòng kim loại**: tại góc quầng sáng sắp hiện, lấy trung bình một mảnh nhỏ trên dải vòng của canvas shader (`preserveDrawingBuffer` bật ở `metal-ring.ts`), chuẩn hoá kênh sáng nhất = 255 như metal-fx; vòng đổi màu liên tục nên khi đang sáng quầng sáng được lấy mẫu lại mỗi 0,4 giây và trôi dần theo màu vòng. Chưa chép: chọn chỗ sáng nhất của shader, trôi nhẹ dọc vòng, bắt sáng theo con trỏ. Hình học (tâm, bán kính, mật độ điểm ảnh) được dựng lại mỗi khi nút gửi đổi cỡ hoặc màn hình đổi mật độ (xoay máy, gập mở, thu phóng, kéo cửa sổ sang màn hình khác), nên luôn ôm đúng vòng kim loại ở mọi kích thước (test `frontend/e2e/metal-glow-fit.cjs`: 6 máy iOS/Android/PC). Dừng cùng shader khi màn hình bị che; đứng yên khi bật giảm chuyển động.

**Lịch sử trong bong bóng chat không giới hạn** (`frontend/src/main.ts`, test `frontend/e2e/chat-history-all.cjs`): bỏ mức cắt 36 phần tử trong `addChatMessage`; một phiên chat là một cuộc trò chuyện (tải lại trang = phiên mới, khung chat trống) nên giữ toàn bộ bong bóng của phiên đó.

**Thang cỡ chữ và lớp hiển thị** (`:root` đầu `frontend/src/style.css`): mọi cỡ chữ dùng 7 bước `--fs-label` 11px, `--fs-small` 12px, `--fs-ui` 13px, `--fs-body` 14px, `--fs-input` 16px, `--fs-title` 18px, `--fs-heading` 20px (giao diện chính, Settings và style inline trong TS); điện thoại (khối `@media (max-width: 768px)`) tăng `--fs-small`/`--fs-ui`/`--fs-body` lên 13/14/15px. Chữ nhỏ nhất 11px; số đồng hồ giữ cỡ riêng. Lớp gốc, mỗi lớp một giá trị, từ dưới lên: orb 10, nhãn JARVIS 20, cụm lệnh/chat 30, đồng hồ 40, hàng nút 50, webcam 60, trình phát media 70, đảo thông báo 80, xem ảnh 90, Cài đặt 100 (`--z-*`); z-index khác chỉ có nghĩa bên trong khung cha của nó.

**Đảo thông báo (Dynamic Island) kiểu Sileo** (`frontend/src/notify-island.ts`, chuyển động `frontend/src/island-shape.ts`, `.island*` trong `style.css`, gốc `#error-text`, test `frontend/e2e/notify-island.cjs`): khung các bước xử lý (flow-tracker, `flow_step`) và lỗi hệ thống (`showError`) không còn là bong bóng/dòng chữ riêng mà vào một viên thuốc ở giữa mép trên màn hình (top-center mặc định), theo thiết kế của sileo.aaryan.design: viên thuốc rộng đúng bằng chữ (icon trạng thái, bước hiện tại hoặc lỗi, số đếm) nền xám than `#2b3240` đậm 90% (sáng hơn nền trang tối một chút nên không chìm, chữ trắng vẫn tương phản ~12:1); bấm vào thì một thẻ rũ xuống dưới liệt kê các bước, nối với viên thuốc bằng cổ cong. Dựng đúng như Sileo (đọc từ mã nguồn gói `sileo` và soi từng khung video demo): một SVG cố định kích thước chứa hai `rect` (viên thuốc và thân thẻ) dưới bộ lọc goo nhẹ của Sileo (blur 8 → ngưỡng → ghép, 3 bước), JS đổi thuộc tính các `rect` mỗi khung hình theo lò xo của Sileo (`island-shape.ts`). Bung: nửa dưới viên thuốc kéo xuống thêm 24px, thân thẻ đủ bề rộng nằm ngay dưới cao dần và hiện dần (còn thấp thì gần như trong suốt, không thành vạch kẻ), goo nối hai hình thành cổ cong nên thân như kéo ra từ viên thuốc rồi bung ngang; thu thì ngược lại. Không viền (như Sileo). Giống hệt trên PC và điện thoại. Thẻ agent (flow-agent) vẫn nằm trong khu bong bóng chat.
- **Mặc định không bao giờ tự popup**: thông báo mới chỉ hiện viên thuốc; thẻ chỉ bung khi người dùng bấm (kể cả khi có media/webcam: thẻ nằm trên cả hai lớp đó: đảo 80 > media 70 > webcam 60, dưới xem ảnh 90 và Cài đặt 100; Cài đặt che đảo).
- Chữ trong thẻ hiện cùng lúc với khung thẻ (fade-in trễ 0,2 giây, đo độ cao khung bằng `scrollHeight` nên khung và chữ bắt đầu cùng lúc), khi thu thì chữ mờ trước rồi khung co.
- Thẻ mở ra mà 5 giây không chạm (di chuyển/chạm/cuộn trong thẻ thì đếm lại) thì tự thu về viên thuốc, thu ngang về đúng bề rộng chữ ở giữa; trên máy tính chuột còn nằm trong thẻ thì không thu, rời chuột đi trong 5 giây thì thu. Bấm lại viên thuốc, bấm ra ngoài hoặc Escape thì thu ngay. Màn hình cảm ứng không tính `:hover` (iOS giữ hover sau khi chạm).
- Xử lý xong, hoặc lỗi đã hiện 8 giây, và không ai xem thì viên thuốc biến mất: thu ngang vào giữa tới hết trong 0,3 giây, icon + chữ + số đếm bị xoá mờ dần và bám theo nhanh hơn (0,25 giây; nút viên thuốc co cùng nền và cắt nội dung theo bề rộng đang co), cả đảo mờ trong lúc thu nên thu xong là biến mất luôn, không còn vệt hẹp; không trượt lên.
- Bung thẻ theo chuyển động của Sileo (đọc từ mã nguồn gói `sileo`): lò xo 600ms (cùng các điểm với `linear()` của Sileo), thẻ rũ xuống từ viên thuốc, cổ nối cong nằm ngay dưới viên thuốc; chữ tiêu đề nhỏ lại 0,9 và hạ 3px khi mở; nội dung nằm ngoài luồng bố cục và chỉ đổi độ mờ, nên không phải tính lại bố cục mỗi khung hình. Thẻ thu về nhanh (0,22 giây, không nảy).
- Chữ trong viên thuốc đổi dài/ngắn thì viên thuốc co giãn cùng lúc trong 0,3 giây: bề rộng nút viên thuốc được JS đặt cùng khung hình với đường viền, nội dung nằm giữa và bị cắt theo nó, nên chữ không tràn ra ngoài nền trước rồi nền mới giãn theo (test `notify-island.cjs` mục 8b). Bề rộng chữ đo bằng `offsetWidth` (không tính phép thu nhỏ 0,9 lúc thẻ mở), nên mở xem rồi thu về viên thuốc vẫn ôm trọn chữ và số đếm (mục 11f).
- Thẻ bung ra rộng tối đa 340px và luôn chừa 56px mỗi bên (không che nút menu điều khiển ở góc phải, trừ máy dưới 360px nơi thẻ tối thiểu 200px).
- Mượt trên điện thoại như Sileo: bộ lọc nhẹ chạy trên SVG `rect` trong khối có kích thước cố định (không đổi cỡ mỗi khung hình), nội dung nằm ngoài luồng bố cục chỉ đổi độ mờ, đảo chỉ đo lại bố cục khi chiều cao nội dung đổi (test `notify-island.cjs` mục 9b, 9d, 11b, 11d).

**Mở JARVIS trên iPhone / trình duyệt** (thẻ `<meta>` trong `frontend/index.html`): dùng `viewport-fit=cover`, `theme-color`, và `apple-mobile-web-app-status-bar-style="black-translucent"` để giao diện tràn đều qua tai thỏ trên iPhone và duy trì dải gradient mờ của hệ thống.
- `html, body` cao `100dvh`; xem ảnh cao `100dvh`.
- Android: cài như app toàn màn hình cần manifest + HTTPS hợp lệ (chứng chỉ hiện tại tự ký), chưa làm.

**Trang không kéo được, chỉ khung chat cuộn** (`lockPageDrag` trong `frontend/src/viewport-reset.ts`, `overscroll-behavior: contain` trên `#chat-history`, test `frontend/e2e/page-scroll-lock.cjs`): trên điện thoại cả trang không bao giờ bị kéo, kể cả khi bàn phím ảo hiện (iOS vốn cho kéo cả trang lúc đó). Một cú vuốt chỉ cuộn khung có thanh cuộn riêng nằm dưới ngón tay (khung bong bóng chat, Cài đặt, danh sách bước của đảo thông báo...) và chỉ bên trong khung đó: kéo tới mép trên/dưới rồi kéo tiếp cũng không kéo theo trang; vuốt ngang chỉ cuộn khung cuộn ngang (bảng, khối code).

**Dải gradient ở mép trên iPhone sau Cài đặt** (`frontend/src/settings/styles.css`, `frontend/src/settings/index.ts`, `frontend/src/viewport-reset.ts`): `#settings-container` và `.sd-root` đều đặt `background: none` (trong suốt hoàn toàn ở toạ độ `y=0`), kích thước `width: 100vw; height: 100dvh`, nền giao diện chỉ bắt đầu từ `.sd-body` (`--sd-bg: #050508`), thanh tiêu đề `.sd-topbar` trong suốt và có `padding-top: env(safe-area-inset-top)` để né tai thỏ; khi đóng Cài đặt, hàm `closeSettings` tự động `blur()` giải phóng focus khỏi nút `#settings-close` và gán thuộc tính `inert`; hàm `refreshStatusBarTint` trong `viewport-reset.ts` kích hoạt Safari khôi phục dải gradient mờ ở tai thỏ. Khối `#safe-top-fill` đã được gỡ bỏ hoàn toàn khỏi HTML và CSS. Khi đóng lớp phủ, trang đưa scroll về 0.

**Bàn phím ảo tự hạ khi chạm ra ngoài** (`frontend/src/keyboard-dismiss.ts`, test `frontend/e2e/keyboard-dismiss.cjs`): trên màn hình cảm ứng, khi ô nhập đang focus: chạm (tap) vào lịch sử chat hoặc bất cứ đâu ngoài thanh lệnh thì hạ bàn phím và đưa trang về đầu (`dismissKeyboardOnMobile`); kéo ở ngoài khung chat cũng hạ; vuốt trong khung chat để đọc thì giữ bàn phím và chat cuộn; chạm thanh lệnh không hạ. Máy tính dùng chuột không đổi.

**Ô nhập một dòng, placeholder tự rút gọn** (`adjustInputHeight` và `fitPlaceholder` trong `frontend/src/main.ts`, test `frontend/e2e/input-placeholder.cjs`): chữ gợi ý luôn một dòng, cắt bằng "…" cho vừa bề ngang ô (nội dung đầy đủ ở `aria-label`); ô trống không đo `scrollHeight` nữa nên xoá hết chữ không còn làm thanh lệnh nhảy lên; chiều cao một dòng theo cỡ chữ (`1.35em + 4px`), không còn 24px cố định.

**Menu nút điều khiển** (`frontend/src/controls-menu.ts`, `#controls` trong `style.css`, `frontend/index.html`, test `frontend/e2e/controls-menu.cjs`): 6 nút (webcam, mic, tiếng TTS, thanh lệnh, orb, cài đặt) gom sau một nút chính tròn ở góc trên phải. Bấm nút chính: cả 6 nút tròn nhỏ (30px, ôm sát icon) hiện cùng lúc trên hai vòng cung quanh nó (3 nút vòng trong bán kính 44px ở 0°/45°/90°, 3 nút vòng ngoài 78px ở 15°/45°/75°, về phía trái và dưới). Không chạm gì 4 giây thì tự thu lại (chạm nút nào cũng đếm lại), bấm nút chính hoặc Escape thì thu ngay. Đóng: các nút kia ẩn hẳn (`visibility:hidden`), nên test e2e bấm chuột thật phải mở menu trước (`#btn-controls`) hoặc gọi `.click()` trong trang.

**Khung chat tự co giãn theo chỗ trống** (`frontend/src/chat-fit.ts`, test `frontend/e2e/chat-fit.cjs`): chiều cao tối đa của `#chat-history` là khoảng trống giữa đáy khung chat và vật thấp nhất phía trên: đồng hồ `#jarvis-clock` (luôn), và trên điện thoại là trình phát media khi đang mở (video nằm ngay dưới hàng nút). Không media: chat dài kéo lên sát mép dưới đồng hồ; có media: dừng ở mép dưới video; bàn phím ảo bật lên làm khung thấp đi thì khung chat co lại thay vì chui lên đè đồng hồ và hàng nút; chat ngắn thì khung ôm vừa nội dung. Thay cho các chiều cao cố định cũ (điện thoại 360px, máy nhỏ 180px). Trên PC chỉ tính đồng hồ (video nằm bên trái). **Bàn phím ảo: cả trang trôi lên nguyên vẹn** (`keyboardShift` trong `frontend/src/chat-fit.ts`, `html.kb-open` cuối `style.css`, test `frontend/e2e/chat-keyboard.cjs`, 6 cỡ máy iOS/Android): iOS Safari tự kéo trang lên để lộ ô nhập (khung layout giữ nguyên) nên trang KHÔNG can thiệp gì (lần sửa trước nâng thanh lệnh và co khung chat thêm làm cụm chat co lại, đẩy lệch khi cuộn). Android khi trình duyệt thu nhỏ khung layout (Samsung Internet, Chrome PWA/WebView) thì thanh lệnh bị đẩy lên theo đáy còn đồng hồ/hàng nút ở mép trên giữ nguyên làm khung chat chui lên đè đồng hồ; khi ô nhập đang focus và khung layout thấp đi hơn 120px, đồng hồ, hàng nút, thông báo lỗi và trình phát media được đẩy lên đúng bằng phần thu nhỏ (`translate`), cả trang trôi lên như iOS, khung chat giữ nguyên chiều cao. Bàn phím hạ xuống (kể cả ô nhập vẫn còn focus) thì về chỗ cũ. Khung chat luôn chỉ cao tới mép trên vùng nhìn thấy (đáy đồng hồ, hoặc mép trên của `visualViewport` khi iOS đã kéo trang, hoặc mép màn hình khi Android đã đẩy đồng hồ lên) để vuốt đọc được hết tin cũ.
- Bàn phím iPhone: Safari trả toạ độ theo vùng nhìn thấy (đã trừ phần trang bị kéo lên), trình duyệt khác theo khung layout; mép trên vùng nhìn thấy được đo bằng `#safe-top-fill` (cố định ở top 0) cộng `visualViewport.offsetTop`, nên không trừ phần kéo lên hai lần (lỗi cũ: khung chat bị gom còn ~80px; test `chat-keyboard.cjs` mục 1d).

**Thông báo lỗi `#error-text`** (`frontend/src/style.css`, test `frontend/e2e/error-text.cjs`): đang được dùng (`showError` khi webcam/mic/upload lỗi, hiện 5 giây). Trên điện thoại hàng nút điều khiển đè lên dòng lỗi, nên dòng lỗi nay hiện ngay dưới hàng nút, căn giữa, trong màn hình.

**Hàng trạng thái đổi chỗ khi ẩn/hiện thanh lệnh** (`frontend/src/status-label.ts: mountStatusRowFade`, test `frontend/e2e/status-fade.cjs`): quả cầu `#status-orb` và chữ `#status-text` (đi chung một hàng) không còn nhảy tức thời từ trái ra giữa. Cả hai chiều như nhau: hàng mờ đi và co về 85% ở chỗ cũ, rồi mờ vào và phóng lên 100% ở chỗ mới, tổng 0,25 giây. Hiệu ứng riêng của quả cầu và chữ giữ nguyên. Tắt khi bật "giảm chuyển động" của hệ điều hành.

## Cài đặt và cấu hình

### Yêu cầu

- Windows 10/11 64-bit, Python 3.11+, Node.js và Chrome.
- llama.cpp server tương thích OpenAI API: LLM mặc định ở cổng `8080`, embedding ở `8081`.
- Redis ở cổng `6379`.
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

Khởi động llama.cpp và Redis trước, sau đó chạy backend và frontend ở các terminal riêng:

```powershell
python server.py
```

```powershell
cd frontend
npm run dev
```

Mở `https://localhost:8340`. Nếu dùng VieNeu streaming, chạy thêm `python run_vieneu.py` ở terminal riêng; nếu không, dùng Edge-TTS.

### Cấu hình `.env`

Các biến thường dùng:

| Biến | Mục đích |
|---|---|
| `LOCAL_URL`, `LOCAL_API_KEY`, `LOCAL_MODEL` | Endpoint, khóa và tên model LLM local. |
| `LOCAL_EMBED_URL`, `LOCAL_EMBED_MODEL` | Endpoint và model embedding cho RAG/bộ nhớ ngữ nghĩa. |
| `EDGE_TTS_ENABLED`, `VIENEU_TTS_ENABLED` | Chọn engine đọc tiếng Việt; chỉ bật một engine. |
| `USER_NAME`, `HONORIFIC` | Tên và cách xưng hô; có thể chỉnh trong Settings. |
| `REDIS_URL` | Địa chỉ Redis. |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_IDS` | Bật và giới hạn Telegram bot. |
| `JARVIS_CORS_ORIGINS` | Các origin trình duyệt được phép kết nối. Không dùng `*`. |
| `RAG_WATCH_FOLDER` | Thư mục watcher tự lập chỉ mục, mặc định `data/documents`. |
| `MEMORY_PASSWORD` | Bảo vệ các trang Memory và Logs trong Settings. |
| `DREAM_ENABLED` | Bật/tắt Dream Cycle. |

Giá trị mặc định và các biến bổ sung nằm trong `.env.example`; không đưa khóa bí mật vào README hoặc commit.

Truy cập từ xa qua Tailscale: cài Tailscale trên máy chạy JARVIS và thiết bị truy cập, mở frontend cho mạng bằng `npm run dev -- --host`, sau đó thêm origin Tailscale của máy chủ vào `JARVIS_CORS_ORIGINS`. Không cần mở cổng router.

## Fork sang ngôn ngữ khác

Quy mô nội dung tiếng Việt (số dòng chứa chữ Việt): `engine/` hơn 3.000 dòng, `frontend/src/` hơn 500, `prompt/`, `prompt/tools/` và `tests/` hàng trăm dòng. Tác giả không có kế hoạch hỗ trợ ngôn ngữ khác, nên hãy coi đây là việc chuyển đổi toàn bộ. Làm theo thứ tự:

1. **Prompt**: `prompt/jarvis.md`, `prompt/turn_tool.md`, `prompt/turn_answer.md`, `prompt/voice_cues.md`, mọi mô tả tool trong `prompt/tools/*.md` và các prompt nền (`learning_*`, `evolution`, `dream_*`, `self_healing`). Thêm chỉ dẫn rõ ràng ở đầu `prompt/jarvis.md`, ví dụ:
   ```
   The user's language is English. Always reply in English, even when tool results come back in Vietnamese.
   Address the user as "sir" and refer to yourself as "I". Keep sentences short and natural for speech.
   ```
2. **Từ khoá khớp chuỗi trong code** (phần dễ hỏng âm thầm nhất): `_NEEDS_WORD`, `_FUTURE`, `_ACT` và câu thay thế `_NO_PROMISE` trong `engine/turn/loop.py`; `_PREF_STYLE` và tên thứ trong tuần ở `engine/turn/prompt.py`; chữ tiếng Việt trong các tool ở `engine/tools/catalog/` và `engine/tools/*.py`; tên file wiki như `Học hỏi.md` ở `engine/core/learning.py`. Mẫu chặn `PROMPT_INJECTION_PATTERNS` ở `engine/core/guardrails.py` đã có tiếng Anh.
3. **Giọng nói**:
   - Đọc: đặt `TTS_LOCAL_MODEL=en-US-GuyNeural` trong `.env` (`edge-tts --list-voices` liệt kê giọng). Giữ `EDGE_TTS_ENABLED=true`, `VIENEU_TTS_ENABLED=false`, vì VieNeu chỉ đọc tiếng Việt. Muốn ElevenLabs, OpenAI TTS, Azure, Google: viết thêm engine trong `engine/server/` theo mẫu `tts_engine.py`, đăng ký ở `tts_manager.py` (đọc `TTS_ENGINE`); dịch vụ nên trả âm thanh từng câu để phát liên tục.
   - Nghe: phía trình duyệt dùng `vi-VN` trong `frontend/src/voice.ts`, còn `engine/server/whisper_server.py` cố định `language="vi"`. Đổi cả hai.
4. **Nguồn dữ liệu**: tin tức, thời tiết, giá vàng/xăng, lịch vạn niên, rạp CGV, Epic, trang bán hàng đều của Việt Nam. Thay hoặc bỏ tool tương ứng (`engine/tools/catalog/` + `prompt/tools/<tên>.md`).
5. **Chữ trên giao diện** trong `frontend/src/` và các trang Settings.
6. **Test**: nhiều test và bản chụp `tests/golden/` chứa câu tiếng Việt; cập nhật theo prompt mới rồi chạy lại toàn bộ test.
7. **Đo lại**: prompt được tinh chỉnh cho model local nhỏ bằng tiếng Việt. Dịch xong hãy chạy lại các probe trong `tests/live/` với llama-server của bạn.

**Dùng model lớn (Claude, Gemini, ChatGPT)**: đổi `LOCAL_URL`, `LOCAL_API_KEY`, `LOCAL_MODEL` trong `.env` sang endpoint tương thích OpenAI của nhà cung cấp. Nếu API khác định dạng OpenAI, cần chỉnh hoặc viết lại [`engine/server/llm_server.py`](engine/server/llm_server.py) (cách gọi, tham số, stream); prompt có thể cần chỉnh lại vì được tinh chỉnh cho model local nhỏ.

**Khi tải về**: skill `skills/officecli` chỉ chứa hướng dẫn dùng, hãy cài officecli từ mã nguồn gốc và lấy thư mục `examples/` từ đó. Một số tính năng riêng của tác giả (tra cứu pháp luật, tra cứu đơn vị hành chính) không có trong bản công khai.

## API, kiểm thử và bảo mật

### API

- `GET /api/health` và `/api/health/detailed`: trạng thái server/dịch vụ.
- `/api/settings/*`: cấu hình và kiểm tra kết nối trong Settings.
- `/api/memory-control/*`, `/api/learnings/*`, `/api/conversations/*`: bộ nhớ và lịch sử.
- `GET /api/outputs/{token}`: tải tệp kết quả được phân phối cho phiên.
- `WS /ws/voice`: luồng giọng nói, văn bản, âm thanh và sự kiện giao diện.

Các API nhạy cảm yêu cầu quyền/trạng thái phù hợp; xem router trong `engine/server/` để biết đầy đủ endpoint.

### Kiểm thử

```powershell
python -m pytest tests -q --ignore=tests/live --ignore-glob="tests/test_live_*"
# Chẩn đoán RAM và kiểm tra cache mô hình HuggingFace VieNeu-TTS:
python scripts/check_vieneu_memory.py
python -m pytest tests/test_vieneu_health_and_memory.py -v
```

Frontend dùng các kịch bản Playwright trong `frontend/e2e/*.cjs` (chạy `npm run dev` ở `:5173`, rồi `PW=<đường dẫn module playwright> node frontend/e2e/<tên>.cjs`; Playwright không nằm trong `package.json`, cần tự cài). CI (`.github/workflows/ci.yml`, chạy mỗi lần push `main` và mỗi PR) gồm: `ruff check .`, compile Python, `python .github/scripts/check_imports.py` (mọi `from engine... import X` phải trỏ tới tên có thật), `pytest` (cài `requirements-ci.txt` và `bsdtar`) và `npm run build` cho frontend; chạy lại các lệnh này trước khi push. Một số test cần máy thật (VieNeu, llama-server) nên tự bỏ qua trên CI; nếu test lỗi trên máy bạn, hãy kiểm tra lại trước khi sửa code. Test dữ liệu learning/wiki chạy trên thư mục tạm để tránh thay đổi dữ liệu người dùng.

### Bảo mật

- REST API thay đổi dữ liệu và WebSocket kiểm tra `Origin`; IP được giới hạn theo cấu hình bảo mật.
- Kết quả từ web/tool được đánh dấu là dữ liệu không tin cậy và lọc chỉ thị giả mạo trước khi chuyển tiếp.
- Sau khi đọc nguồn bên ngoài, router chặn chuỗi hành động có thể điều khiển máy.
- Có thể đặt `MEMORY_PASSWORD` để bảo vệ Memory Center và Logs; secret chỉ cấu hình trong `.env`.

## Phiên bản và giấy phép

Phiên bản được quản lý tại [`VERSION`](VERSION) (nguồn duy nhất); lịch sử cũ ở [CHANGELOG.md](CHANGELOG.md). Khi phát hành bản mới, cập nhật `VERSION` và ghi tóm tắt thay đổi chính tại đây.

### Chưa phát hành

- **Graphfy đỡ rối (2026-10-13):** đường import mờ, chỉ đường gọi LLM có xung sáng; đường tới các khối dùng chung `server`, `tools`, `UIUX` ẩn mặc định (rê chuột vào khối thì hiện), nút **Hiện tất cả** để bật lại.
- **Chuyển đổi sang kiến trúc định tuyến tool phẳng (2026-10-12):** Thay thế toàn bộ hệ thống 31 agent, orchestrator, classifier và single-stream ReAct cũ bằng mô hình gọi tool phẳng của Gemma 4: Quyết định không nhân cách (tối đa 3 vòng gọi tool) → Trả lời có nhân cách JARVIS. Dọn dẹp toàn bộ code thừa, thư mục commands/ và các probe/test chết.
- **Nâng cấp Timeline Indicator & Connector trên Dynamic Island (2026-10-11):** Tái cấu trúc danh sách các bước xử lý theo chuẩn Chakra/Ant Design Timeline; thay thế đường kẻ nền tạm bợ cũ bằng các đoạn `TimelineConnector` mỏng gắn liền theo từng bước và tự động triệt tiêu ở bước cuối cùng; áp dụng hiệu ứng `TimelineDot` morphicon (pulsing beacon khi đang chạy, tự động biến hình pop spring thành solid dot tích hợp icon khi hoàn tất).
- **Tự động điều chỉnh trần chat theo Webcam, Media Player & tỉ lệ màn hình (2026-10-10):** Thay thế logic cũ bằng hàm tinh gọn `initChatAutoCeiling` đo toạ độ thực tế để co khung chat xuống dưới mép Webcam/Media Player khi hiển thị trên mobile, vừa khít chân đồng hồ trên mọi dòng máy mà hoàn toàn không can thiệp bàn phím; thêm `interactive-widget=overlays-content` cho Android.
- **Gỡ tính năng ghi chú (2026-10-13):** bỏ tab Notes trong Bộ nhớ, các endpoint `/api/notes/*` và `engine/tools/note_engine.py` (không còn tool nào dùng). Tệp ghi chú cũ trên đĩa giữ nguyên.
- **Cài đặt: trang Mention và Commands theo đúng lệnh còn chạy (2026-10-12):** trang "Agents" đổi thành **Mention**, liệt kê đúng những gì `@` nhận (`@rag` + `@<tool>` trong registry); trang **Commands** liệt kê `/help` + `/<tool>`. Bảng Tổng quan đếm số mention và số lệnh `/` thật (trước đây số lệnh luôn 0). Bộ nhớ: "Agent Outcomes" đổi thành **Outcomes**.
- **App Màn hình chính iPhone kín đáy (2026-10-12):** `<head>` giống GeForce NOW: manifest `display: standalone` (`frontend/public/app/`), `apple-mobile-web-app-capable`, `apple-touch-fullscreen`, `apple-mobile-web-app-title`; bỏ `apple-mobile-web-app-status-bar-style` (`black-translucent` làm app hụt một thanh trạng thái ở đáy). `.sd-topbar` phải giữ trong suốt: có màu nền là iOS mất gradient tai thỏ cả trên Safari lẫn app.
- **Tối ưu thanh trạng thái iOS Safari, ẩn controls & đảo động khi mở Cài đặt (2026-10-10):** Giữ dải gradient tai thỏ Safari iOS bằng cách đặt `.sd-root` và `.sd-topbar` nền trong suốt (`background: none`); tự động ẩn hoàn toàn cụm nút `#controls` và đảo động Dynamic Island (`.island`) khi mở modal Cài đặt để tránh lộ nút hay thông báo qua topbar trong suốt; tự khôi phục đảo động nếu đang chạy khi đóng Cài đặt; dọn dẹp thẻ thừa `btn-menu`.
- **Evolution cập nhật cả bộ luật STYLE (2026-10-08):** mỗi lần trả về toàn bộ `STYLE.md` (tối đa 20 luật giao tiếp): giữ luật cũ, gộp luật trùng ý, viết đè luật bị bài học mới phủ định, thêm luật từ bài học/sở thích về cách nói; sự thật đời sống không thành luật; không nhãn `[MỚI]`/nguồn/ví dụ; temp 0. Probe `tests/live/probes/evolution_probe.py`: 9/9 kiểm tra × 3 lần.
- **Learning chỉ học đúng 3 loại (2026-10-08):** điều ngài tự nói về bản thân, yêu cầu ghi nhớ/đổi cách cư xử, và lời chỉ trích/sửa sai; không tự suy diễn luật từ trò chuyện. Luật xưng hô/giọng/emoji/độ dài luôn là `behaviour_lesson`. Nói lại điều đã học (khác chữ) không tạo/ghi đè dòng mới (`adds_new_information`). Probe learning: nên học 10/10, không nên học 0/9.
- **Dọn dữ liệu học (2026-10-08):** bài học không còn lưu kèm "(ví dụ: …)"/"(Evidence: …)" (câu của ngài từng lọt vào prompt chat); `STYLE.md` vào prompt không còn nhãn `[MỚI]`/`(Từ key)`. Dọn dữ liệu cũ: `python scripts/clean_learnings_2026_10.py` (mặc định chỉ xem; `--apply` sao lưu `jarvis.db` rồi xóa dòng rác, làm sạch nội dung và đồng bộ lại wiki).
- **Prompt đúng định dạng Gemma 4 (2026-10-08):** Gemma 4 chỉ được huấn luyện với một system turn ở đầu; chat từng gửi 3 system turn (2 cái giữa hội thoại) và model có lúc chép nguyên `<turn_status>` ra câu trả lời. `llm_server` giờ gộp mọi system về một turn ở đầu cho Gemma như Qwen/Bonsai (đo: fabrication/honorific/knowledge/command_help/overask bằng hoặc tốt hơn).

Đây là dự án fan hâm mộ độc lập, không liên kết với Marvel Entertainment hoặc The Walt Disney Company. Tên và khái niệm JARVIS thuộc chủ sở hữu bản quyền tương ứng.

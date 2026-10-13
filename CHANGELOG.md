# Nhật Ký Phiên Bản

**Tiếng Việt** | [English](CHANGELOG.en.md) · [← Về README](README.md)

**Quy tắc đánh số** `MAJOR.MINOR.PATCH`:
- Số phiên bản nằm ở một chỗ duy nhất là file [`VERSION`](VERSION). `/api/health` và dashboard (Vite) đọc từ file này; README chỉ trỏ link tới nó.
- Mỗi lần phát hành: tăng số trong `VERSION` (chỉ sửa 1 chỗ này), thêm một mục mới vào nhật ký dưới đây, rồi gắn git tag `vX.Y.Z`.
- Tăng số nào:
  - `PATCH`: sửa lỗi, không đổi hành vi thiết kế.
  - `MINOR`: thêm tính năng, hoặc đổi prompt/luồng mà không làm vỡ dữ liệu cũ.
  - `MAJOR`: đổi kiến trúc, hoặc đổi dữ liệu/DB theo cách cần chuyển đổi.

## v9.9.6 — 2026-09-27

**Settings thành dashboard toàn màn hình.** Spec và plan do Claude viết, một model khác triển khai (kèm 9 trang ngoài plan theo yêu cầu), rồi Claude review và sửa.

| Vấn đề phát hiện khi review | Hậu quả | Cách sửa |
|---|---|---|
| `/api/settings/status` trả nguyên `args` của MCP | Lộ API key context7 cho mọi client | Chỉ trả tên/lệnh/trạng thái; `args` che giá trị bí mật (`_redact_args`) |
| Status nhét README, prompts, commands… (≈93KB) vào mỗi lần poll | Settings chậm, dễ timeout | Tách sang `/api/settings/catalog`, gọi khi mở trang |
| `mcp_servers` đổi từ dict sang list | HUD hiện "0,1,2" với chấm lỗi | Trả lại `{tên: trạng thái}` từ hub thật |
| `/api/mcp/servers` dùng `_json` chưa import | Trang MCP lỗi | Sửa, trạng thái lấy từ hub thay vì cờ `enabled` |
| UI gửi `SERVER_API_KEY`, `FISH_AUDIO_API_KEY` | Backend từ chối, báo "lỗi kết nối" | Đổi sang `LOCAL_API_KEY`, `TTS_LOCAL_KEY` |
| Bản chuyển vào `settings/` bỏ sự kiện `jarvis:overlay` | Orb không tạm dừng | Phát lại sự kiện |
| Giọng đọc gõ cứng 4 giọng Google, lưu sai API | Lưu giọng giả | Nạp `/api/tts/voices`, lưu qua `/api/tts/voice`, gắn nút clone |
| CSS ép `display:flex` lên lưới Bộ nhớ, chữ IN HOA, chữ < 12px | Bố cục vỡ, font lệch | Sửa lưới, một họ font, tối thiểu 12px; gỡ 42 rule chết |
| Command-bar gợi ý `/help`, `/clear`, skill, `/plugin` | Gõ vào đều "Không tìm thấy lệnh" | Chỉ gợi ý lệnh backend chạy được |
| Thu nhỏ sidebar Settings: nhãn `display:none` + icon căn giữa ngay lập tức | Chữ/icon nhảy trong lúc co chiều rộng | Icon giữ nguyên toạ độ, nhãn mờ dần (`opacity`), không xuống dòng |
| Dashboard lấy số phiên bản từ `.env` | Lệch với `VERSION` | Vite đọc file `VERSION` |

**Mascot trên nút gửi** (`frontend/src/mascot.ts`) — port TypeScript thuần của [nilbuild/page-mascot](https://github.com/nilbuild/page-mascot) (MIT), không cần React (gói npm `page-mascot` không dùng tới, có thể gỡ).
- **Vị trí:** đứng yên ngay trên `#cmd-send`, thân đè lên viền trên command-bar (lún 20px) để trông như ngồi trên thanh lệnh; bên trái vẫn là dòng trạng thái. Cỡ 56px (mobile 44px).
- **Vùng bấm:** chỉ phần đầu nhận click; phần thân cho click xuyên qua nên nút gửi vẫn bấm bình thường.
- **Tương tác:** đầu quay theo chuột (8 hướng), thỉnh thoảng chớp mắt; bấm để đổi biểu cảm (tim, lấp lánh, vui), bấm nhanh 4 lần = choáng.
- **Theo trạng thái JARVIS** qua sự kiện `jarvis:mascot` (phát trong `transition()` và `showError()`): thinking nhìn lên, working lấp lánh, speaking vui, lỗi/restart choáng, idle 60 giây thì ngủ.
- **Nhân vật:** sprite `frontend/public/mascots/<tên>-directions.webp` và `<tên>-reactions.webp` (lưới 3×3, nền trong suốt); đổi nhân vật bằng tham số `name` của `mountMascot` trong `main.ts`.
- **Phục vụ file tĩnh:** `mount_frontend_dist` (`engine/UIUX/ui_engine.py`) phục vụ `/` và mọi thư mục trong `frontend/dist` (`assets/`, `mascots/`, …) — trước đây chỉ `/assets` nên ảnh mascot bị 404 trên app desktop.
- **Test:** `frontend/e2e/mascot.cjs` (vị trí, không che nút gửi, hướng nhìn, biểu cảm, trạng thái, mobile) và `tests/test_frontend_static.py`.

**Khung các bước (flow_tracker) và thẻ agent (flow_agents) thiết kế lại** — một font giao diện 12–12.5px cho cả hai (bỏ monospace), dấu trạng thái cùng cỡ.
- **Khung các bước:** đầu khung = icon trạng thái + bước hiện tại + số đếm dạng viên `6/7` + thanh tiến độ mảnh; danh sách là dòng thời gian dọc (chấm xanh lá xong · xanh dương nhấp nháy đang chạy · xám chưa tới), bỏ số "1. 2. 3."; phần sau "→" thành chữ phụ mờ, bỏ "..." cuối nhãn.
- **Thẻ agent:** icon lucide trong ô bo góc + tên + việc đang làm (bỏ tiền tố "Thực thi:"). Backend giữ nguyên `"<emoji> Agent <Tên>"` (Telegram vẫn dùng); frontend tách emoji và chọn icon theo tên trong `AGENT_ICON` (`frontend/src/icons.ts`). Agent mới trong `engine/agents` chưa có trong bảng vẫn hiện, với icon robot.
- **Test:** `frontend/e2e/flow-ui.cjs` (WebSocket giả phát một lượt chạy).

**Đồng hồ lật kiểu HTC Sense** (`frontend/src/clock.ts`) — mỗi chữ số một ô (`HH:MM`; dấu `:` là 2 chấm tròn phát "sóng radar" — vòng sáng xanh lan ra từ từng chấm luân phiên, chu kỳ 2 giây, đứng yên khi bật giảm chuyển động), không khung, chỉ còn đường cắt ngang giữa số; giữa phía trên màn hình chính, ngay dưới hàng nút.
- **Hiệu ứng:** khi đổi số, nửa trên số cũ gập xuống rồi nửa dưới số mới rơi vào (2 × 0,3 giây). Chỉ chữ số vừa đổi mới lật (10:59→11:00 giữ nguyên số 1 đầu). Không có thẻ nền nên hai nửa tĩnh mờ dần ra/vào theo tấm lật, số cũ và mới không chồng lên nhau. Tắt khi máy bật giảm chuyển động.
- **Lớp:** `z-index: 1`, chỉ nằm trên orb; HUD, chat, bản đồ, Settings đều đè lên được. `pointer-events: none` nên không chặn click.
- **Font:** Oswald Light (300), nhúng vào bản build qua `@fontsource/oswald` (bộ latin) — app desktop chạy offline vẫn đúng font.
- **Test:** `frontend/e2e/clock.cjs` (giờ giả bằng `page.clock`: hiện 10:59, lật sang 11:00, dọn tấm lật, vị trí, lớp, font, mobile).

Thêm: sửa và lưu prompt (`POST /api/prompts/save`, chỉ ghi đè `prompt/*.md` có sẵn); Graphfy thành bản đồ luồng chạy thật. Test: `tests/test_settings_status_api.py`, `frontend/e2e/settings-dashboard.cjs`.

## v9.9.5 — 2026-09-25

**Gom prompt và learning tự phản tư.** Spec do Claude viết, một model khác lên plan và triển khai, rồi Claude review và sửa lại. Kết quả chạy thật: hiểu ngữ cảnh tốt hơn, phản hồi nhanh hơn, token giảm, dễ bảo trì.

| Vấn đề phát hiện khi review | Hậu quả | Cách sửa |
|---|---|---|
| Lịch sử từ DB chỉ lấy `role` và `content` | Thẻ `<ask_user>` không bao giờ được dựng lại | Giữ thêm cột `ask_user`/`action_run`, có test trên DB tạm |
| Lịch sử bỏ mọi lượt user trùng chữ | Mất lượt "ừ" cũ, ảnh hưởng cả gate | Chỉ gộp bản ghi trùng nằm liền nhau |
| `unlearn_last_learning` xoá bài học mới nhất mỗi khi ngài phàn nàn route sai | Mất dữ liệu | Thay bằng `retract` có kiểm soát |
| Prompt được chép sang `.md` nhưng code vẫn dùng chữ viết cứng | Sửa file `.md` không có tác dụng | Nối code vào file `.md`, kiểm bằng golden test |
| `learning_workflow.md` có schema đầu ra khác prompt thật | Sẽ làm hỏng việc học workflow | Viết lại theo đúng prompt đang chạy |
| Test learning ghi vào `data/` thật | Để lại rác trong `Evolution.md` | Test chạy trên thư mục tạm, script dọn gỡ rác |
| Sampling được đổi sau khi đo trên bố cục cũ | Đo lại 10 lần mỗi kịch bản, cấu hình mới tệ hơn | Giữ `0.4 / 0.8 / 40` |
| Script dọn sửa `STYLE.md` trước khi sao lưu, và model kia tự chạy `--apply` | Bản sao lưu thiếu `skills/self_evolution/` | Sao lưu trước mọi thay đổi |

**Sửa thêm sau khi chạy thật:**
- **Media phát nhầm video**: từ đệm "tôi muốn … của" kéo một video re-up lên đầu danh sách. Đã bỏ từ đệm trước khi xếp hạng. Bảng kết quả chép nguyên từ tool và nói đúng bài đang phát.
- **Classifier**: tên có gạch nối như "M-TP" được tính là một từ, nên câu rút gọn được nhận.
- **Chat bịa kết quả kiểm tra bảo mật** khi không có tool nào chạy: thêm `<tool_status>` cho mọi lượt chat. Đo lại: bịa 8/10 → 0/10, đề nghị đúng giao thức 10/10. Lượt từ chối không còn nói "đã mở rồi" (1/10). Đã gỡ các dữ liệu bịa khỏi DB và nhật ký wiki, có sao lưu trong `data/backups/`.

**Bài học khi giao việc cho model khác:**
- Test phải chạy qua đường code thật, không chỉ gọi hàm với dữ liệu giả.
- Test không được đụng `data/` thật.
- Thao tác `--apply` trên dữ liệu thật do người dùng tự chạy.
- Chỉ đo live trên đúng bố cục đang chạy, với đủ số lần chạy.
- Sửa prompt thì phải chứng minh nó giống từng byte với bản cũ, hoặc nói rõ là đã đổi.

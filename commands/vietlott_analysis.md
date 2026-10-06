---
name: vietlott_analysis
description: Phân tích kết quả chính thức Mega 6/45 và Power 6/55; báo kỳ mới nhất, giải thưởng, Jackpot ước tính, xác suất lý thuyết và điểm thống kê.
usage: '{"games": ["mega645", "power655"], "max_pages": 5, "sync_all": false}'
category: info
tags: ["vietlott", "xổ số", "mega", "power", "xác suất"]
enabled: true
---

# Lệnh vietlott_analysis

Chỉ dùng dữ liệu từ các trang chính thức Vietlott.

Kết quả cho từng game phải có:

- Kỳ quay mới nhất, ngày quay và bộ số.
- Số đặc biệt của Power 6/55.
- Toàn bộ hạng giải kỳ mới nhất, số lượng giải và giá trị mỗi giải.
- Jackpot/Jackpot 1/Jackpot 2 ước tính hiện tại từ trang chủ Vietlott.
- Ba bộ số tham khảo với `statistical_score_percent` và cỡ mẫu.
- Xác suất Jackpot lý thuyết theo tổ hợp.
- Trạng thái nguồn và tiến độ cache lịch sử.

`statistical_score_percent` chỉ là điểm xếp hạng mô tả, không phải xác suất
trúng. Không dùng từ “chính xác”, “khả năng cao” hoặc cam kết dự đoán.

`sync_all` mặc định là `false`. Chỉ đặt `true` khi cần chạy hết các batch lịch
sử; mỗi batch phải được lưu trước khi chuyển sang batch tiếp theo.

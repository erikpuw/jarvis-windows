---
name: weather_search
description: Tra cứu thời tiết một địa điểm — hiện tại (nhiệt độ, độ ẩm, gió, khả năng mưa) hoặc lịch khả năng mưa % theo từng giờ
usage: '{"location": "Tên thành phố hoặc địa điểm (ví dụ: Hà Nội, Đà Nẵng); bỏ trống thì mặc định Hồ Chí Minh", "hourly": "true nếu người dùng hỏi khả năng mưa / dự báo mưa theo giờ, ngược lại bỏ trống"}'
category: search
tags: [weather, thời tiết, nhiệt độ, dự báo, mưa]
enabled: true
---

Tra cứu thời tiết cho một địa điểm cụ thể.

- Mặc định: thời tiết hiện tại từ Báo Mới (34 tỉnh thành), dự phòng wttr.in rồi Open-Meteo. Gồm nhiệt độ, nhiệt độ thấp/cao hôm nay, độ ẩm, gió, khả năng mưa.
- `hourly=true`: lịch khả năng mưa (%) và lượng mưa (mm) cho 24 giờ tới từ Open-Meteo, dự phòng Báo Mới khi Open-Meteo bị giới hạn lượt gọi.
- Không nêu địa điểm thì dùng Hồ Chí Minh.

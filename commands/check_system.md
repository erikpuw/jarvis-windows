---
name: check_system
description: "Xem hoạt động hệ thống máy tính: CPU, RAM, ổ đĩa, tiến trình, tình trạng máy."
usage: '{}'
category: security
tags: [system, cpu, ram, disk, process, health]
enabled: true
---

Công cụ này đọc nhanh tình trạng hoạt động của máy (khác check_security chỉ kiểm tra kết nối mạng và firewall):
1. CPU, RAM, swap và thời gian bật máy.
2. Dung lượng từng ổ đĩa.
3. Top 5 tiến trình tốn tài nguyên nhất và mức dùng của chính JARVIS.

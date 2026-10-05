---
name: search_media
description: Tìm kiếm và tự động phát nhạc, video trên YouTube hoặc file local.
usage: '{"query": "CHỈ tên bài hát/video/nội dung, KHÔNG bao gồm từ khóa định tuyến (youtube, video, nhạc, phim, xem phim...)", "source": "youtube, local, hoặc auto"}'
category: media
tags: ["utility", "music", "video"]
enabled: true
---

# Lệnh search_media

## QUY TẮC QUAN TRỌNG
- **query**: CHỈ chứa tên bài hát/video/nội dung cần tìm. KHÔNG bao gồm từ khóa định tuyến.
- **source**: "youtube" cho nhạc/video, "local" cho file trong máy, "auto" nếu không rõ.

## VÍ DỤ
| Câu người dùng | query (đúng) | source |
|---|---|---|
| "youtube come my way sơn tùng" | "come my way sơn tùng" | youtube |
| "video tối nay em thức anh nhé" | "tối nay em thức anh nhé" | youtube |
| "bài hát see tình" | "see tình" | youtube |
| "xem phim đấu phá thương khung phần 5" | "đấu phá thương khung phần 5" | youtube |
| "mở file nhạc trong máy tên chiều hôm ấy" | "chiều hôm ấy" | local |

## CÁC TỪ KHÓA CẦN LOẠI BỎ KHỎI query
- youtube, video, nhạc, bài hát, nghe, phim, xem phim — từ chỉ loại nội dung
- mở, tìm, xem — từ hành động chung

## LƯU Ý
Giữ nguyên số phần/số tập nếu người dùng nói (ví dụ "phần 5", "tập 10") vì đó là một phần tên cần tìm.

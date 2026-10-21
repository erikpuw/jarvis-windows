Bạn bảo trì bộ nhớ hành vi của Jarvis: dọn danh sách bài học.

<nhiem_vu>
Xem <bai_hoc> (mỗi dòng: #id [loại, ngày] nội dung) và đề xuất:
- "trùng": hai bài cùng ý → gỡ một bài, "keep_id" là bài giữ lại.
- "merge": nhiều bài cùng chủ đề gộp thành một câu.
Hai bài khác chủ đề hoặc trái ý nhau thì không phải trùng. Không chắc thì không gỡ. Tối đa 5 mục.
</nhiem_vu>

<vi_du>
#3 [lesson, 2026-09-01] Tránh trả lời lan man. #9 [lesson, 2026-10-01] Trả lời ngắn gọn, không dài dòng. #7 [lesson, 2026-09-12] Xin lỗi ngắn một câu.
→ {{"remove": [{{"id": 3, "why": "trùng", "keep_id": 9}}], "merge": []}}
</vi_du>

<bai_hoc>
{items}
</bai_hoc>

Trả về JSON gồm remove, merge.

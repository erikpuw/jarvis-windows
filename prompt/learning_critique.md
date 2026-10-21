Bạn kiểm duyệt bài học trước khi Jarvis ghi nhớ.

<nhiem_vu>
So <de_xuat> với <muc_cu> (mục gần nhất đã có) và chọn một quyết định:
- skip: trùng ý với mục cũ, chỉ là cảm xúc hay việc nhất thời, hoặc không giúp Jarvis phục vụ tốt hơn.
- merge: cùng chủ đề và đề xuất có thêm ý mới; "merged_content" là một câu gộp cả hai.
- replace: ngài đổi ý, đề xuất trái với mục cũ; đề xuất thay mục cũ.
- new: khác chủ đề với mục cũ (hoặc không có mục cũ) và đáng ghi.
"merged_content" để rỗng khi không phải merge.
</nhiem_vu>

<vi_du>
Đề xuất "Trả lời ngắn gọn." / mục cũ "Tránh trả lời dài dòng." → {{"decision": "skip", "reason": "cùng ý", "merged_content": ""}}
Đề xuất "Dùng emoji vừa phải." / mục cũ "Nói giọng Sài Gòn." → {{"decision": "new", "reason": "khác chủ đề", "merged_content": ""}}
Đề xuất "Trả lời chi tiết từng bước." / mục cũ "Trả lời ngắn gọn." → {{"decision": "replace", "reason": "ngài đổi ý", "merged_content": ""}}
</vi_du>

<de_xuat>
{proposal}
</de_xuat>

<muc_cu>
{existing_item}
</muc_cu>

Trả về JSON quyết định.

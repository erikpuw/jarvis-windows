Bạn phân tích Learning.md/Preferences.md của Jarvis và cập nhật 2 khối:

1. ROUTING: agent nào nên xử lý loại yêu cầu nào. Đây CHỈ là đề xuất cho người duyệt, không tự áp dụng.
2. STYLE: bộ luật Jarvis nói và cư xử khi trò chuyện (xưng hô, giọng điệu, emoji, độ dài, cách xin lỗi, cách đáp khi bị chỉ trích), để sửa lỗi giao tiếp mà ngài đã yêu cầu hoặc chỉ trích.
   Cách cập nhật STYLE:
   - Bắt đầu từ STYLE.MD HIỆN TẠI và trả về TOÀN BỘ bộ luật sau khi cập nhật, không chỉ luật mới.
   - Mỗi luật cũ phải có mặt lại trong kết quả (nguyên văn hoặc đã sửa), trừ khi bị một bài học mới phủ định.
   - Bài học cùng ý với một luật cũ: gộp vào luật đó, không thêm dòng.
   - Bài học trái với một luật cũ: viết lại luật đó theo bài học mới; bài học mới thắng, không giữ cả hai.
   - Bài học về cách nói hoặc cư xử chưa có luật nào: thêm một luật.
   - Sở thích của ngài về cách Jarvis nói (giọng, xưng hô, emoji, độ dài) là luật. Sự thật hay sở thích đời sống của ngài (đồ ăn, thói quen, công việc, thiết bị) không phải luật.
   - Tối đa 20 luật; mỗi luật một câu khái niệm, không ví dụ, không trích câu, không ghi nguồn hay nhãn.
   TUYỆT ĐỐI KHÔNG viết luật STYLE liên quan đến công cụ, hỏi lại, xin phép, agent hay thẻ. Các luật này do persona và <soul_rules> quản lý độc quyền.

PREFERENCES.MD:
"""
{pref_content}
"""

LEARNING.MD:
"""
{learning_content}
"""

ĐỀ XUẤT ROUTING ĐÃ CÓ (chưa duyệt):
"""
{current_routing_proposals}
"""

STYLE.MD HIỆN TẠI:
"""
{current_style}
"""

Nếu không có gì mới, set need_evolution=false. Trả lời tiếng Việt, đúng khuôn:

DECISION_JSON:
{{"need_evolution": true/false, "reason": "lý do ngắn"}}

ROUTING_RULES:
# Self Evolution Routing Rules
[bullet mới, hoặc để trống]

STYLE_RULES:
# Self Evolution Style Rules
[toàn bộ luật sau khi cập nhật, mỗi luật một dòng bắt đầu bằng "- "]

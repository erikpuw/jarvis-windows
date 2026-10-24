Bạn là bộ phận ghi nhớ của Jarvis: ngài vừa dạy Jarvis một điều, hãy ghi lại đúng điều ngài dạy.

<nhiem_vu>
Chỉ ghi điều ngài nói trong <luot_moi>; <hoi_thoai> chỉ để hiểu ngữ cảnh, không ghi lại điều đã nói ở lượt trước.
Mỗi ý ngài dạy là một mục, tối đa 4 mục:
- lesson: cách Jarvis nói, trả lời, cư xử (giọng, độ dài, emoji, từ đệm, cách xin lỗi). Viết một câu khái niệm, không chép câu của ngài.
- preference: điều ngài thích, không thích, hay chọn, thói quen ăn uống, giải trí.
- user_fact: sự thật về con người ngài, không phải chuyện thích hay không: nghề, ngày sinh, nơi ở, gia đình, thú nuôi, sức khoẻ, cung hoàng đạo.
- tool_rule: một loại yêu cầu thì dùng công cụ nào. "topic" là loại yêu cầu theo lời ngài, "right_tool" là tên trong <cong_cu> ứng với công cụ ngài nhắc (ngài có thể gọi tắt).
- tool_fix: ngài nói Jarvis vừa dùng sai công cụ cho một yêu cầu cụ thể trong <cong_cu_da_dung>. "wrong_tool" là công cụ đã dùng, "right_tool" là công cụ ngài chỉ ra.
- retract: ngài phủ nhận đúng một mục trong <da_hoc_luot_truoc>.
Không ghi: lời chê chung chung không nói phải làm gì, cảm xúc nhất thời, lệnh làm một lần, lời của Jarvis.
"evidence" là nguyên văn một đoạn trong <luot_moi>.
</nhiem_vu>

<vi_du>
<luot_moi>ghi nhớ: trả lời ngắn thôi, và dùng emoji ở tiêu đề</luot_moi>
→ {{"proposals": [{{"kind": "lesson", "key": "tra_loi_ngan_gon", "content": "Trả lời ngắn gọn, đi thẳng vào ý chính.", "evidence": "trả lời ngắn thôi"}}, {{"kind": "lesson", "key": "emoji_tieu_de", "content": "Đặt emoji ở tiêu đề.", "evidence": "dùng emoji ở tiêu đề"}}]}}
<luot_moi>từ giờ hỏi thời tiết thì dùng weather, lịch phim dùng cinema</luot_moi>
→ {{"proposals": [{{"kind": "tool_rule", "topic": "hỏi thời tiết", "right_tool": "weather", "evidence": "hỏi thời tiết thì dùng weather"}}, {{"kind": "tool_rule", "topic": "lịch phim", "right_tool": "cinema", "evidence": "lịch phim dùng cinema"}}]}}
ngài: "giá thịt heo" (Jarvis dùng market_price) → <luot_moi>sai rồi, giá thịt heo phải tra search_products</luot_moi>
→ {{"proposals": [{{"kind": "tool_fix", "wrong_tool": "market_price", "right_tool": "search_products", "evidence": "giá thịt heo phải tra search_products"}}]}}
<luot_moi>nhớ giùm tôi thích uống trà đá</luot_moi>
→ {{"proposals": [{{"kind": "preference", "key": "thich_tra_da", "content": "Ngài thích uống trà đá.", "evidence": "tôi thích uống trà đá"}}]}}
<luot_moi>ghi nhớ giúp, tôi có hai đứa con</luot_moi>
→ {{"proposals": [{{"kind": "user_fact", "key": "co_hai_con", "content": "Ngài có hai người con.", "evidence": "tôi có hai đứa con"}}]}}
</vi_du>

<cong_cu>
{tools}
</cong_cu>

<cong_cu_da_dung>
{used_tools}
</cong_cu_da_dung>

<da_hoc_luot_truoc>
{just_learned}
</da_hoc_luot_truoc>

<hoi_thoai>
{context}
</hoi_thoai>

<luot_moi>
{latest}
</luot_moi>

Ghi lại điều ngài dạy trong <luot_moi>, trả về JSON theo <nhiem_vu>.

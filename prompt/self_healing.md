Bạn phân loại lỗi trong log của Jarvis để quyết định có cần sửa mã nguồn không.

<nhiem_vu>
Chọn đúng một "classification":
- CODE_BUG: lỗi logic, cú pháp, gọi sai API, lỗi import, biến chưa có, sai kiểu trong mã của dự án.
- TRANSIENT: mạng chập chờn, hết thời gian chờ, giới hạn tần suất, mất kết nối tạm thời.
- CONFIG: thiếu biến môi trường, sai đường dẫn, không tìm thấy tệp, thiếu quyền.
- DEPENDENCY: dịch vụ ngoài ngừng, lỗi của thư viện bên thứ ba.
- OTHER: không rõ ràng.
Chỉ chọn CODE_BUG khi lỗi nằm trong mã của <tep>. Không chắc thì chọn OTHER.
"summary": một câu ngắn nêu lỗi. "action": một bước xử lý cụ thể kế tiếp.
</nhiem_vu>

<vi_du>
NameError: name 'foo' is not defined
→ {{"classification": "CODE_BUG", "summary": "Biến foo chưa được khai báo.", "action": "Khai báo foo trước khi dùng."}}
httpx.ReadTimeout: timed out
→ {{"classification": "TRANSIENT", "summary": "Hết thời gian chờ phản hồi.", "action": "Không cần sửa mã, theo dõi lần sau."}}
</vi_du>

<tep>
{project_file}
</tep>

<loi>
{err_snippet}
</loi>

Đọc <loi> và trả về JSON gồm classification, summary, action.

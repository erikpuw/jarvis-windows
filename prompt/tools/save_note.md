Ghi một ghi chú mới vào kho ghi chú của ngài (thư mục Ghi_chu), sau này tìm lại được bằng search_documents. Dùng khi ngài bảo ghi chú, ghi lại, lưu lại một thông tin cụ thể (vd hạn thanh toán, mật khẩu wifi khách, lịch hẹn), hoặc bảo lưu kết quả vừa tra (tin tức, bảng giá). Không dùng khi ngài chỉ kể chuyện mà không bảo ghi, không dùng để tìm lại ghi chú (dùng search_documents), và không dùng để dạy JARVIS cách cư xử. Mỗi lần gọi tạo một file mới, không sửa hay xoá ghi chú cũ.

content: nội dung cần ghi, đúng như lời ngài; để trống khi chỉ lưu kết quả vừa tra
title: tên ngắn cho ghi chú (vd "Hạn trả nợ thẻ"); để trống thì lấy từ nội dung
from_last_result: true khi ngài bảo lưu cái vừa tra; code tự lấy kết quả tra cứu thành công gần nhất trong 1 giờ, không tra lại

## answer
Báo ngắn đã ghi chú và tên file trong kết quả; kết quả báo chưa có nội dung hay chưa có kết quả tra cứu thì nói đúng như vậy.

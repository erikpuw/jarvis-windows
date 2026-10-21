Tìm một món hàng đang bán trên các sàn thương mại điện tử và chuỗi cửa hàng bán lẻ, trả về bảng giá, sao đánh giá, lượt bán để ngài so sánh khi mua sắm. Dùng khi ngài muốn mua, hỏi giá hoặc so sánh một món đồ cụ thể: điện thoại, laptop, tai nghe, đồ gia dụng, quần áo, thực phẩm và đồ tạp hoá. Không dùng cho quán ăn, quán cà phê, nhà hàng, khách sạn, địa điểm hay dịch vụ (gọi xe, giao đồ ăn, đặt bàn, đặt phòng, đặt vé): danh mục chưa có công cụ cho các việc đó, nên chọn "none". Không dùng cho giá vàng, xăng dầu, tỷ giá (dùng market_price) hay thuốc, thực phẩm chức năng (dùng search_medicine). Chỉ trả về giá niêm yết lúc tra, không đặt mua hộ.

query: tên món hàng cần tìm, giữ nguyên tên hãng và mẫu mã ngài nói (vd "airpods pro 3", "nồi chiên không dầu")

## answer
Không tự thêm giá không có trong kết quả. Trả lời đúng trọng tâm kết quả tra được, không tự ý hỏi thêm hay gợi ý các siêu thị, cửa hàng khác khi ngài không yêu cầu.

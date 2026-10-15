Sổ gym của ngài: ghi buổi tập, ghi cân nặng, tra bài tập, xem lịch sử và thống kê tiến độ, thói quen, hướng dẫn dinh dưỡng. Dùng khi ngài kể vừa tập gì, cân được bao nhiêu, hỏi bài tập cho nhóm cơ, hoặc muốn xem tiến độ tập. Không dùng cho tra giá thực phẩm (search_products) hay tài liệu thực đơn đã lưu (search_documents).

action: log_workout = ghi buổi tập (bài, hiệp, số lần, kg); record_bodyweight = ghi cân nặng; search_exercises = tìm bài tập theo nhóm cơ/tên; history = xem các buổi tập đã ghi; stats = thống kê, tổng kết tiến độ; log_habit / habit_summary = ghi / xem thói quen; nutrition_guide = hướng dẫn dinh dưỡng; list_profiles / create_profile / select_profile = xem / tạo / chọn hồ sơ
profile_id: ID hồ sơ (tùy chọn)
name: tên hồ sơ mới (tùy chọn)
query: từ khóa bài tập (tùy chọn)
trained_on: ngày tập YYYY-MM-DD (tùy chọn)
exercises: danh sách bài tập [{name, sets:[{reps, kg}]}] (tùy chọn)
measured_on: ngày cân YYYY-MM-DD (tùy chọn)
weight_kg: cân nặng kg (tùy chọn)
goal: eat_food, maintain, fat_loss hoặc gain_muscle (tùy chọn)
habit: tên thói quen (tùy chọn)
done: thói quen đã làm hay chưa (tùy chọn)
day: ngày YYYY-MM-DD (tùy chọn)
note: ghi chú (tùy chọn)
days: số ngày, mặc định 7 (tùy chọn)
limit: số dòng, mặc định 20 (tùy chọn)

## answer
Giữ nguyên tiếng Việt có dấu trong các lệnh gợi ý nằm trong dấu backtick. Tra bài tập thì giữ các liên kết video dạng [Tiêu đề](url). Vừa tạo hoặc chọn hồ sơ thì xác nhận và nêu các việc ngài có thể làm tiếp.

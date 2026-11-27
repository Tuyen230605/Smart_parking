# Các tình huống sử dụng

## Người dùng

- Khách lái xe: không cần tài khoản. Quét mã QR để xem chỗ trống và đường đi, có thể nhận email.
- Nhân viên bãi: đăng nhập trang quản trị, bấm cho vào, cho ra, thu tiền.
- Màn hình ở cổng (kiosk): tài khoản riêng, chỉ hiện mã QR.

## UC-01. Xe vào

1. Đưa tay hoặc xe mô hình vào làn vào trước camera. Pi gửi tin "có xe ở làn vào".
2. Đám mây cấp biển số demo (ví dụ 11111) và tạo phiên "Chờ cho vào".
3. Trang Phiên đỗ hiện thẻ "Chờ cho vào – 11111". Trang camera trên Pi hiện "Chờ cho vào: 11111".
4. Nhân viên bấm *Cho vào*. Servo quay trái, 5 giây sau tự về giữa. Xe vào danh sách xe trong bãi.
5. Kiosk hiện mã QR và bản đồ đường đi tới ô trống gần nhất.

Nếu camera báo nhầm, nhân viên bấm *Không cho vào*. Số biển đó sẽ được dùng lại cho xe sau.

## UC-02. Khách xem đường và nhận email

1. Khách quét QR, mở trang `/s/<mã>`. Trang hiện ô trống gợi ý và bản đồ hai tầng.
2. Khách chạm vào ô trống khác để chọn. Đường đi được vẽ lại. Ô tầng 2 có bước lên dốc.
3. Khách nhập email, tích ô đồng ý, bấm gửi. Email ghi đường tới ô đã chọn.
4. Mỗi phiên chỉ gửi một email. Link QR hết hạn sau 15 phút.

Gợi ý không giữ chỗ. Xe khác vẫn có thể đỗ vào ô đó.

## UC-03. Ghi nhớ email theo biển số

1. Ở bước 3 của UC-02, khách tích "Ghi nhớ email cho biển số xe này".
2. Lần sau xe có biển số đó được cho vào, hệ thống tự gửi email hướng dẫn.
3. Khách hủy bằng link trong email, hoặc bấm *Bỏ liên kết email* trên trang QR.

## UC-04. Bãi đầy hoặc mất kết nối bo mạch ô

- Bo mạch 18 nút đang kết nối và cả 18 ô đều có xe: bấm *Cho vào* sẽ báo bãi đầy, cần không mở.
- Bo mạch 18 nút mất kết nối quá 90 giây: mọi ô thành "không rõ". Xe vẫn được cho vào, chỉ không có ô gợi ý.

## UC-05. Xe ra và tính tiền

1. Đưa tay vào làn ra. Đám mây chọn xe có số lớn nhất đang đỗ, tính tiền và tạo trạng thái "Chờ cho ra".
2. Trang Phiên đỗ hiện số tiền. Cần chưa mở.
3. Miễn phí: nhân viên bấm *Cho ra*. Có phí: thu tiền mặt rồi bấm *Đã thu … cho ra*, hoặc bấm *Miễn phí* và ghi lý do.
4. Servo quay phải. Phiên đóng, xe rời danh sách.

Bãi không còn xe mà camera báo xe ra thì hệ thống bỏ qua.

## UC-06. Ô đỗ

Mỗi ô có một nút. Nhấn một lần đổi trạng thái giữa trống và có xe, nhấn lại thì đổi ngược. Trạng thái được lưu trong bo mạch nên không mất khi mất điện. Sơ đồ trên web cập nhật sau vài giây.

## UC-07. Sự cố kết nối

- Tin nhắn có thể đến hai lần. Đám mây và ESP32 đều bỏ bản trùng nên không tạo phiên trùng hay mở cần hai lần.
- Lệnh mở cần quá 5 giây bị bỏ qua, để lệnh cũ không chạy sau khi bo mạch kết nối lại.
- Thiết bị im lặng quá 90 giây thì bị đánh dấu mất kết nối và có cảnh báo trên trang quản trị.
- Gửi email lỗi thì phiên đỗ vẫn bình thường, trang quản trị ghi là gửi thất bại.

## UC-08. Xóa dữ liệu sau 10 ngày

Biển số và email của mỗi phiên bị xóa sau tối đa 10 ngày. Tác vụ dọn dữ liệu chạy mỗi giờ. Email đã ghi nhớ theo biển số giữ tới khi khách hủy.

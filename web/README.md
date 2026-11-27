# Web

Một ứng dụng React (Vite, TypeScript) dùng chung cho mọi người:

| Đường dẫn | Dùng cho |
|---|---|
| `/` | Sơ đồ 18 ô, ai cũng xem được |
| `/kiosk` | Màn hình ở cổng: mã QR lớn và bản đồ đường đi của xe vừa vào. Đăng nhập bằng tài khoản `kiosk` |
| `/s/:mã` | Trang của khách mở từ mã QR: ô gợi ý, bản đồ chọn ô và vẽ đường đi, gửi email, ghi nhớ email |
| `/huy-email/:mã` | Hủy ghi nhớ email từ link trong email |
| `/admin` | Quản trị: danh sách xe, nút Cho vào, Cho ra, thu tiền, thiết bị, bảng giá. Đăng nhập bằng tài khoản `admin` |

Web chỉ gọi [API](../docs/api-contract.md), không kết nối trực tiếp tới IoT Core và không chứa khóa AWS.

## Chạy

```bash
cd web
npm install
npm run dev     # http://localhost:5173
npm run build   # kiểm tra kiểu và build ra dist/
```

Sau khi chạy `infra/aws/deploy.sh`, cấu hình API được ghi sẵn vào `web/.env.*.local` nên `npm run dev` gọi API thật. Không có cấu hình thì web dùng API giả trong `src/api/mock.ts` và hiện dải vàng báo đang dùng dữ liệu giả. Đường dẫn thử với API giả: `/s/demo`, `/s/demo-f2`, `/s/sent`, `/s/expired`.

Đưa web lên CloudFront: `infra/aws/deploy-web.sh`.

## Cấu trúc

| Thư mục | Nội dung |
|---|---|
| `src/pages/public/` | Sơ đồ bãi |
| `src/pages/kiosk/` | Màn hình QR ở cổng |
| `src/pages/guest/` | Trang của khách, trang hủy email |
| `src/pages/admin/` | Trang quản trị |
| `src/components/` | Sơ đồ ô, bản đồ đường đi (`RouteMap.tsx`), đăng nhập |
| `src/api/` | Kiểu dữ liệu, gọi API thật (`http.ts`), API giả (`mock.ts`) |

Thêm API mới thì sửa đủ ba chỗ: `types.ts`, `http.ts`, `mock.ts`. Như vậy trang vẫn chạy được với dữ liệu giả.

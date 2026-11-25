# Web dùng chung cho khách, kiosk và quản trị

Một ứng dụng responsive, ba chế độ:

- Public/guest: sơ đồ 18 ô; trang QR phiên gợi ý ô trống, cho khách chạm chọn ô và vẽ đường đi từ cổng vào (`components/RouteMap.tsx`), form email (tùy chọn ghi nhớ theo biển số); `/huy-email/:token` hủy liên kết.
- Kiosk tại cổng: hiển thị QR phiên vừa được cho vào kèm bản đồ đường đi, không hiện dữ liệu riêng của xe khác.
- Admin: đăng nhập Cognito; Tổng quan có danh sách xe trong bãi/chờ vào/chờ ra; Phiên đỗ có nút **Cho vào** và **Cho ra** (thu tiền) để mở cần; thiết bị, bảng giá.

Web dùng [REST API](../docs/api-contract.md); không nhúng AWS secret hoặc subscribe IoT Core trực tiếp.

## Chạy

```bash
cd web
npm install
npm run dev          # http://localhost:5173, dùng API giả
npm run build        # kiểm tra kiểu + build ra dist/ để đưa lên S3
```

Khi backend đã deploy: chép `.env.example` thành `.env.local` và điền `VITE_API_BASE_URL`. Bỏ trống thì app dùng API giả trong `src/api/mock.ts` và hiện dải vàng báo đang mock.

Đường dẫn thử với API giả: `/s/demo`, `/s/demo-f2`, `/s/sent` (đã gửi email), `/s/expired` (QR hết hạn).

## Cấu trúc và người phụ trách

Vite + React + TypeScript + React Router. Một app, một bộ API, mỗi người sở hữu một thư mục trang.

| Đường dẫn | URL | Người |
|---|---|---|
| `src/pages/guest/` | `/s/:token` (URL trong QR) | 1 |
| `src/pages/kiosk/` | `/kiosk` | 2 |
| `src/pages/public/`, `src/components/FloorMap.tsx` | `/` | 3 |
| `src/pages/admin/`, `src/auth.ts` | `/admin/*` | 4 |
| `src/api/`, `src/App.tsx`, `src/styles.css` | dùng chung | sửa qua PR, báo cả nhóm |

## Quy ước

- Mọi lời gọi backend đi qua `api` trong `src/api`. Không gọi `fetch` trực tiếp trong trang.
- Thêm endpoint mới: thêm kiểu vào `types.ts` → thêm hàm vào interface `Api` → cài đặt ở cả `http.ts` và `mock.ts`. Nhờ vậy trang luôn chạy được bằng mock khi backend chưa xong.
- Kiểu dữ liệu bám [api-contract.md](../docs/api-contract.md). Đổi hợp đồng thì sửa tài liệu và `types.ts` trong cùng một PR, có người 4 duyệt.
- Dùng màu/biến CSS sẵn có trong `styles.css` (`--available`, `--occupied`…) để các trang trông thống nhất.
- Mutation gửi header `Idempotency-Key` (xem `submitClaimEmail`). Trang khách không hiện biển số/email.
- Deploy S3 + CloudFront phải trả `index.html` cho lỗi 403/404 để route `/s/...`, `/admin` tải được trực tiếp.

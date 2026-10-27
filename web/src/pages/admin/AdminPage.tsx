// Người 4: trang quản trị. Khung chạy được; cần hoàn thiện theo docs/team-tasks.md.
import { api } from "../../api";
import { useLoad } from "../../components/useLoad";

export function AdminPage() {
  const { data, error } = useLoad(() => api.getDashboard(), [], 5_000);
  return (
    <main className="page">
      <h1>Quản trị</h1>
      {error && <div className="card error">{error.message}</div>}
      {data && (
        <div className="stats">
          <div className="card"><b>{data.available}</b> trống</div>
          <div className="card"><b>{data.reserved}</b> đang giữ</div>
          <div className="card"><b>{data.occupied}</b> có xe</div>
          <div className="card"><b>{data.unknown}</b> không rõ</div>
        </div>
      )}
      {/* TODO người 4: đăng nhập Cognito, danh sách/chi tiết phiên, thiết bị, sửa OCR, thu phí, mở cổng ra, bảng giá. */}
    </main>
  );
}

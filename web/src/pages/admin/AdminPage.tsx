// Người 4: trang quản trị (docs/team-tasks.md). Route con dưới /admin/*, chỉ nhóm ADMIN.
import { NavLink, Route, Routes } from "react-router-dom";
import { authEnabled, signOut } from "../../auth";
import { RequireAuth, useAuthUser } from "../../components/RequireAuth";
import { Dashboard } from "./Dashboard";
import { DevicesPage } from "./DevicesPage";
import { PricingPage } from "./PricingPage";
import { SessionDetailPage } from "./SessionDetailPage";
import { SessionsPage } from "./SessionsPage";
import "./admin.css";

export function AdminPage() {
  return (
    <RequireAuth groups={["ADMIN"]}>
      <main className="page admin">
        <header className="admin-head">
          <h1>Quản trị</h1>
          <UserBox />
        </header>
        {!authEnabled && (
          <p className="dev-note">Đăng nhập đang tắt (chưa đặt VITE_COGNITO_*): chỉ dùng với API giả hoặc backend local.</p>
        )}
        <nav className="admin-tabs">
          <NavLink to="/admin" end>Tổng quan</NavLink>
          <NavLink to="/admin/sessions">Phiên</NavLink>
          <NavLink to="/admin/devices">Thiết bị</NavLink>
          <NavLink to="/admin/pricing">Bảng giá</NavLink>
        </nav>
        <Routes>
          <Route index element={<Dashboard />} />
          <Route path="sessions" element={<SessionsPage />} />
          <Route path="sessions/:sessionId" element={<SessionDetailPage />} />
          <Route path="devices" element={<DevicesPage />} />
          <Route path="pricing" element={<PricingPage />} />
          <Route path="*" element={<p className="muted">Không có trang này.</p>} />
        </Routes>
      </main>
    </RequireAuth>
  );
}

function UserBox() {
  const user = useAuthUser();
  if (!authEnabled || !user) return null;
  return (
    <div className="admin-user">
      <span>{user.username}</span>
      <button type="button" className="secondary" onClick={signOut}>Đăng xuất</button>
    </div>
  );
}

import { NavLink, Outlet, createBrowserRouter } from "react-router-dom";
import { usingMock } from "./api";
import { AdminPage } from "./pages/admin/AdminPage";
import { ClaimPage } from "./pages/guest/ClaimPage";
import { KioskPage } from "./pages/kiosk/KioskPage";
import { LayoutPage } from "./pages/public/LayoutPage";

function Shell() {
  return (
    <>
      <header className="topbar">
        <strong>Smart Parking</strong>
        <nav>
          <NavLink to="/" end>Sơ đồ</NavLink>
          <NavLink to="/kiosk">Kiosk</NavLink>
          <NavLink to="/admin">Quản trị</NavLink>
        </nav>
      </header>
      {usingMock && <div className="mock-banner">Đang dùng API giả — đặt VITE_API_BASE_URL để nối backend</div>}
      <Outlet />
    </>
  );
}

// Mỗi route thuộc một người; xem docs/team-tasks.md.
export const router = createBrowserRouter([
  {
    element: <Shell />,
    children: [
      { path: "/", element: <LayoutPage /> },      // người 3
      { path: "/kiosk", element: <KioskPage /> },  // người 2
      { path: "/admin/*", element: <AdminPage /> }, // người 4
    ],
  },
  { path: "/s/:token", element: <ClaimPage /> },   // người 1: URL trong QR, không có menu
]);

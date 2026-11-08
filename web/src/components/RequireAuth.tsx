// Bọc trang kiosk/admin: chưa đăng nhập thì hiện form, sai nhóm thì báo không có quyền.
import { useState, type FormEvent, type ReactNode } from "react";
import { authEnabled, login, logout, useAuth } from "../auth";

export function RequireAuth({ groups, children }: { groups: string[]; children: ReactNode }) {
  const session = useAuth();
  if (!session) return <LoginForm />;
  if (!session.groups.some((g) => groups.includes(g))) {
    return (
      <main className="page narrow">
        <div className="card error">
          Tài khoản <b>{session.username}</b> không có quyền xem trang này (cần nhóm {groups.join(" hoặc ")}).
        </div>
        <button onClick={logout}>Đăng xuất</button>
      </main>
    );
  }
  return <>{children}</>;
}

export function UserBadge() {
  const session = useAuth();
  if (!authEnabled || !session) return null;
  return (
    <span className="muted user-badge">
      {session.username} · <button className="link" onClick={logout}>Đăng xuất</button>
    </span>
  );
}

function LoginForm() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      await login(username, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page narrow">
      <form className="card" onSubmit={submit}>
        <h2>Đăng nhập nhân viên</h2>
        <label>
          Tên đăng nhập
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
        </label>
        <label>
          Mật khẩu
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        </label>
        {error && <p className="error-text">{error}</p>}
        <button type="submit" disabled={busy}>{busy ? "Đang đăng nhập…" : "Đăng nhập"}</button>
      </form>
    </main>
  );
}

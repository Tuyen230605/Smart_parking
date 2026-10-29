// Bọc trang cần đăng nhập Cognito: /admin (nhóm ADMIN) và /kiosk (KIOSK hoặc ADMIN). Người 4 sở hữu.
// Khi tắt đăng nhập (chạy API giả/backend local) thì hiện thẳng nội dung.
import { useEffect, useState, useSyncExternalStore, type FormEvent, type ReactNode } from "react";
import {
  AuthError,
  authEnabled,
  completeNewPassword,
  currentUser,
  onAuthChange,
  restoreSession,
  signIn,
  signOut,
} from "../auth";
import "./RequireAuth.css";

export function useAuthUser() {
  return useSyncExternalStore(onAuthChange, currentUser);
}

export function RequireAuth({ groups, children }: { groups: string[]; children: ReactNode }) {
  const user = useAuthUser();
  const [restoring, setRestoring] = useState(authEnabled && !user);

  useEffect(() => {
    if (restoring) restoreSession().finally(() => setRestoring(false));
  }, [restoring]);

  if (!authEnabled) return <>{children}</>;
  if (restoring) return <main className="page narrow"><p className="muted">Đang kiểm tra đăng nhập…</p></main>;
  if (!user) return <LoginForm />;
  if (!groups.some((g) => user.groups.includes(g))) {
    return (
      <main className="page narrow">
        <div className="card error">
          Tài khoản <b>{user.username}</b> không có quyền vào trang này (cần nhóm {groups.join(" hoặc ")}).
        </div>
        <button type="button" onClick={signOut}>Đăng xuất</button>
      </main>
    );
  }
  return <>{children}</>;
}

function LoginForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [challenge, setChallenge] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(undefined);
    if (challenge && newPassword !== confirm) {
      setError("Hai lần nhập mật khẩu mới không khớp.");
      return;
    }
    setBusy(true);
    try {
      if (challenge) {
        await completeNewPassword(email.trim(), newPassword, challenge);
      } else {
        const result = await signIn(email.trim(), password);
        if (result.status === "NEW_PASSWORD_REQUIRED") setChallenge(result.session);
      }
    } catch (err) {
      setError(err instanceof AuthError ? err.message : "Đăng nhập thất bại.");
      // Phiên đổi mật khẩu của Cognito hết hạn sau vài phút: quay lại bước đăng nhập.
      if (err instanceof AuthError && err.code === "NotAuthorizedException") setChallenge(undefined);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page narrow">
      <form className="card login" onSubmit={submit}>
        <h1>{challenge ? "Đặt mật khẩu mới" : "Đăng nhập"}</h1>
        {challenge ? (
          <>
            <p className="muted">Lần đầu đăng nhập cần đổi mật khẩu tạm.</p>
            <label>
              Mật khẩu mới
              <input type="password" required minLength={12} autoComplete="new-password"
                value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
            </label>
            <label>
              Nhập lại mật khẩu mới
              <input type="password" required autoComplete="new-password"
                value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            </label>
          </>
        ) : (
          <>
            <label>
              Email
              <input type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />
            </label>
            <label>
              Mật khẩu
              <input type="password" required autoComplete="current-password"
                value={password} onChange={(e) => setPassword(e.target.value)} />
            </label>
          </>
        )}
        {error && <p className="error-text">{error}</p>}
        <button type="submit" disabled={busy}>{busy ? "Đang xử lý…" : challenge ? "Lưu mật khẩu" : "Đăng nhập"}</button>
      </form>
    </main>
  );
}

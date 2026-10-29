import { useRef, useState } from "react";
import { ApiError } from "../../api";
import { authEnabled, signOut } from "../../auth";

const ERROR_MESSAGES: Partial<Record<string, string>> = {
  NETWORK_ERROR: "Không kết nối được máy chủ. Bấm lại để thử: thao tác không bị làm hai lần.",
  INTERNAL_ERROR: "Máy chủ lỗi. Bấm lại để thử: thao tác không bị làm hai lần.",
  FORBIDDEN: "Tài khoản không có quyền thao tác này.",
  RATE_LIMITED: "Thao tác quá nhanh, đợi một chút rồi thử lại.",
};

/** Key ngẫu nhiên; không dùng crypto.randomUUID vì trình duyệt chỉ cho phép trên HTTPS/localhost. */
export function newIdempotencyKey(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");
}

export function errorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return String(error);
  return ERROR_MESSAGES[error.code] ?? error.message;
}

/** Hết phiên đăng nhập thì đưa về form đăng nhập thay vì chỉ báo lỗi. */
export function handleAuthError(error: unknown) {
  if (authEnabled && error instanceof ApiError && error.code === "UNAUTHENTICATED") signOut();
}

/**
 * Chạy một thao tác quản trị với Idempotency-Key. Lỗi mạng/5xx: giữ key, bấm lại an toàn vì backend
 * nhận ra key cũ. Thành công hoặc lỗi nghiệp vụ (4xx): đổi key cho lần thao tác tiếp theo.
 */
export function useAction() {
  const key = useRef(newIdempotencyKey());
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();

  async function run<T>(action: (idempotencyKey: string) => Promise<T>): Promise<T | undefined> {
    setPending(true);
    setError(undefined);
    try {
      const result = await action(key.current);
      key.current = newIdempotencyKey();
      return result;
    } catch (e) {
      if (e instanceof ApiError && e.status !== 0 && e.status < 500) key.current = newIdempotencyKey();
      handleAuthError(e);
      setError(errorMessage(e));
      return undefined;
    } finally {
      setPending(false);
    }
  }

  return { run, pending, error };
}

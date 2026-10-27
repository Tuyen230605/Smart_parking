import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../api";

/** Gọi một hàm API khi mount; `pollMs` để tự làm mới (sơ đồ, kiosk, dashboard). */
export function useLoad<T>(load: () => Promise<T>, deps: unknown[], pollMs?: number) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<ApiError>();
  const run = useCallback(load, deps);

  const reload = useCallback(async () => {
    try {
      setData(await run());
      setError(undefined);
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, "NETWORK_ERROR", String(e)));
    }
  }, [run]);

  useEffect(() => {
    reload();
    if (!pollMs) return;
    const id = setInterval(reload, pollMs);
    return () => clearInterval(id);
  }, [reload, pollMs]);

  return { data, error, loading: !data && !error, reload, setData };
}

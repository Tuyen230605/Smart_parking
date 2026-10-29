import { useEffect, useState } from "react";
import type { SessionState } from "../../api";
import { useLoad } from "../../components/useLoad";
import { STATE_LABELS, stateTone } from "./format";
import { errorMessage, handleAuthError } from "./useAction";

/** useLoad + chuyển về form đăng nhập khi token hết hạn. */
export function useAdminLoad<T>(load: () => Promise<T>, deps: unknown[], pollMs?: number) {
  const result = useLoad(load, deps, pollMs);
  useEffect(() => handleAuthError(result.error), [result.error]);
  return result;
}

export function StateBadge({ state }: { state: SessionState }) {
  return <span className={`badge badge-${stateTone(state)}`}>{STATE_LABELS[state] ?? state}</span>;
}

export function ErrorCard({ error }: { error: unknown }) {
  return error ? <div className="card error">{errorMessage(error)}</div> : null;
}

/** Nút cho thao tác khó đảo ngược (mở cần, đóng phiên): bấm lần hai để xác nhận. */
export function ConfirmButton({ label, confirmLabel, disabled, onConfirm, className }: {
  label: string;
  confirmLabel: string;
  disabled?: boolean;
  onConfirm: () => void;
  className?: string;
}) {
  const [asking, setAsking] = useState(false);
  if (!asking) {
    return <button type="button" className={className} disabled={disabled} onClick={() => setAsking(true)}>{label}</button>;
  }
  return (
    <span className="actions-row">
      <button type="button" className={className} disabled={disabled} onClick={() => { setAsking(false); onConfirm(); }}>
        {confirmLabel}
      </button>
      <button type="button" className="secondary" onClick={() => setAsking(false)}>Hủy</button>
    </span>
  );
}

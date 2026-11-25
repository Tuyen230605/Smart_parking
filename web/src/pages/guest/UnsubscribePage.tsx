// Link "Hủy liên kết" trong email tự gửi: bỏ liên kết email với biển số, lần sau không tự gửi nữa.
import { useParams } from "react-router-dom";
import { api } from "../../api";
import { useLoad } from "../../components/useLoad";

export function UnsubscribePage() {
  const { token = "" } = useParams();
  const { error, loading } = useLoad(() => api.unsubscribe(token), [token]);
  return (
    <main className="page narrow">
      <section className={`card ${error ? "error" : loading ? "" : "success"}`}>
        {loading ? "Đang hủy liên kết…" : error ? "Link hủy không hợp lệ hoặc đã hết dùng." :
          "Đã hủy liên kết email với biển số xe. Lần sau xe vào bãi sẽ không tự gửi email nữa."}
      </section>
    </main>
  );
}

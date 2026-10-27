// Người 3: sơ đồ 18 ô công khai. Khung chạy được; cần hoàn thiện theo docs/team-tasks.md.
import { api } from "../../api";
import { FloorMap } from "../../components/FloorMap";
import { useLoad } from "../../components/useLoad";

export function LayoutPage() {
  const { data, error } = useLoad(() => api.getLayout(), [], 10_000);
  return (
    <main className="page">
      <h1>Sơ đồ bãi xe</h1>
      {error && <div className="card error">{error.message}</div>}
      <div className="floors">
        <FloorMap floor={1} slots={data?.slots} />
        <FloorMap floor={2} slots={data?.slots} />
      </div>
      {/* TODO người 3: chú thích màu, số ô trống mỗi tầng, nhãn ô mô phỏng, xử lý UNKNOWN. */}
    </main>
  );
}

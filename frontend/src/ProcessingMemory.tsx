import type { ProcessingStats } from "./inspection-api";

export function processingPhase(phase?: string) {
  return ({preparing:"Chuẩn bị hồ sơ", starting_worker:"Khởi động bộ xử lý", reading_ifc:"Đang đọc IFC",
    preparing_geometry:"Chuẩn bị hình học", building_geometry:"Đang dựng hình học", writing_preview:"Đang tạo bản xem 3D",
    optimizing_preview:"Đang tối ưu bản xem 3D", writing_report:"Đang ghi báo cáo", reading_pdf:"Đang đọc PDF",
    reading_drawing:"Đang đọc DXF", converting_drawing:"Đang chuyển DWG", loading_model:"Đang đọc mô hình",
    loading_geometry:"Đang nạp hình học đã lưu", checking_pairs:"Đang so sánh các cấu kiện", saving:"Đang lưu kết quả"} as Record<string,string>)[phase ?? ""] ?? "Đang xử lý";
}

export default function ProcessingMemory({stats, finished = false}: {stats?: ProcessingStats; finished?: boolean}) {
  const budget = stats?.memory_limit_bytes;
  if (!budget || !Number.isFinite(budget) || budget <= 0) return null;
  const peak = stats?.peak_memory_bytes ?? 0;
  const current = finished ? peak : stats?.memory_bytes ?? peak;
  const gib = (bytes: number) => `${(bytes / 1024**3).toFixed(2)} GiB`;
  return <div className="processing-memory" data-testid="processing-memory" aria-live="off">
    <span>RAM {finished ? "cao nhất đo được" : "đang dùng"}: <strong>{gib(current)}</strong> · Ngân sách: {gib(budget)}</span>
    <meter aria-label="RAM bộ xử lý" min={0} max={budget} value={Math.min(current, budget)} high={budget * .85} />
    <small>Đỉnh: {gib(peak)}{stats?.system_available_bytes !== undefined ? ` · RAM hệ thống trống${finished ? " khi đo" : ""}: ${gib(stats.system_available_bytes)}` : ""}</small>
  </div>;
}

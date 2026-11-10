import { useEffect, useRef, useState } from "react";
import { Cloud, RefreshCw } from "lucide-react";
import { errorMessage, processorFetch, type Connection } from "./inspection-api";

type StorageStatus = {
  configured: boolean; bucket?: string; allocated_bytes?: number; external_bytes?: number; verified_bytes?: number;
  limit_bytes?: number; warning?: boolean; error?: string; total?: number;
  items?: { relative: string; status: string; size_bytes: number }[];
  requests?: { month: string; a: number; b: number; limits: { a: number; b: number } };
};
const gb = (bytes = 0) => (bytes / 1_000_000_000).toLocaleString("vi-VN", { maximumFractionDigits: 3 });

export default function StoragePanel({ connection, projectId, locked }: { connection: Connection | null; projectId?: string; locked: boolean }) {
  const [status, setStatus] = useState<StorageStatus | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [message, setMessage] = useState("");
  const request = useRef<AbortController | null>(null);
  const url = projectId ? `/api/projects/${projectId}/storage` : "/api/projects/storage";
  async function load() {
    if (!connection) return;
    const abort = new AbortController(); request.current?.abort(); request.current = abort;
    setError("");
    try {
      const data: StorageStatus = await processorFetch(connection, url, { signal: abort.signal }).then(response => response.json());
      if (!abort.signal.aborted) { setStatus(data); if (data.error) setError(errorMessage(data.error)); }
    } catch (error) { if (!abort.signal.aborted) setError(error instanceof Error ? error.message : "Chưa đọc được trạng thái R2."); }
  }
  useEffect(() => { void load(); return () => request.current?.abort(); }, [connection?.base_url, connection?.token, projectId]);
  async function sync() {
    if (!connection || !projectId || busy) return;
    const abort = new AbortController(); request.current?.abort(); request.current = abort;
    setBusy(true); setError(""); setMessage("");
    try {
      const result: { status: string; verified_files: number; total_files: number; error?: string } = await processorFetch(connection, `${url}/sync`, { method: "POST", signal: abort.signal }).then(response => response.json());
      if (abort.signal.aborted) return;
      setMessage(`Đã xác minh ${result.verified_files}/${result.total_files} tệp${result.status === "verified" ? "." : "; còn tệp cần thử lại."}`);
      if (result.error) setError(errorMessage(result.error));
      const data: StorageStatus = await processorFetch(connection, url, { signal: abort.signal }).then(response => response.json());
      if (!abort.signal.aborted) setStatus(data);
    } catch (error) { if (!abort.signal.aborted) setError(error instanceof Error ? error.message : "Chưa đồng bộ được tệp."); }
    finally { if (!abort.signal.aborted) setBusy(false); }
  }
  return <section className="cloud-panel" aria-label="Lưu tệp R2" aria-busy={busy}>
    <h3><Cloud size={19} />R2 · tệp dự án</h3>
    <p className="project-muted">{status?.configured ? `Bucket private: ${status.bucket}. Bản sao đã đồng bộ sẽ tự tải lại khi thiếu cache trên máy.` : "Chưa cấu hình R2. Bạn vẫn có thể kiểm tra hồ sơ và lưu dự án trên máy."}</p>
    {status?.configured ? <>
      <p className="cloud-usage">Dung lượng đã giữ chỗ: {gb(status.allocated_bytes)} / {gb(status.limit_bytes)} GB · Đã xác minh: {gb(status.verified_bytes)} GB{status.external_bytes ? ` · Tệp khác trong bucket: ${gb(status.external_bytes)} GB` : ""}</p>
      {status.warning && <p role="status" className="coord-error">Dung lượng đang gần giới hạn 8 GB của app. Hãy kiểm tra trước khi thêm bộ hồ sơ lớn.</p>}
      <p className="project-muted">{status.requests && `Request tháng ${status.requests.month}: A ${status.requests.a.toLocaleString("vi-VN")} / ${status.requests.limits.a.toLocaleString("vi-VN")} · B ${status.requests.b.toLocaleString("vi-VN")} / ${status.requests.limits.b.toLocaleString("vi-VN")}. `}Giới hạn trong app không thay thế hạn mức tính phí của Cloudflare.</p>
      {!projectId && <p className="project-muted">Chọn một dự án để đồng bộ tệp, mô hình và lịch sử kiểm tra.</p>}
      <div className="review-actions">
        <button className="button" disabled={!projectId || locked || busy} onClick={() => void sync()}><Cloud size={16} />Đồng bộ dự án lên R2</button>
        {busy ? <button className="button" onClick={() => { request.current?.abort(); setBusy(false); setMessage("Đã yêu cầu dừng đồng bộ. Tệp đã xác minh được giữ lại; bạn có thể thử tiếp."); }}>Dừng đồng bộ</button> : <button className="button" disabled={!connection || locked} onClick={() => void load()}><RefreshCw size={16} />Kiểm tra trạng thái R2</button>}
      </div>
      {!!status.total && <details><summary>{status.total} tệp đã đồng bộ của dự án · xem 20 tệp gần đầu danh sách</summary><ul>{status.items?.map(item => <li key={item.relative}><code>{item.relative}</code><span>{item.status === "verified" ? "Đã xác minh SHA-256" : "Đang chờ xác minh"}</span></li>)}</ul></details>}
    </> : <details><summary>Cách kết nối R2</summary><ol>
      <li>Tạo bucket <strong>Standard, private</strong> trong Cloudflare R2.</li>
      <li>Tạo S3 token <strong>Object Read &amp; Write</strong>, chỉ cho bucket đó.</li>
      <li>Chạy cấu hình R2 theo README trên máy, nhập endpoint và hai key trong cửa sổ nhập ẩn.</li>
      <li>Mở lại app rồi chọn dự án và bấm “Đồng bộ dự án lên R2”.</li>
    </ol><p className="project-muted">Key được mã hóa tại bộ xử lý. Giữ lại bản sao key của bạn để cấu hình trên máy khác.</p></details>}
    {message && <p role="status" className="cloud-result">{message}</p>}
    {error && <p className="coord-error" role="alert">{error}</p>}
  </section>;
}

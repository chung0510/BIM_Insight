import { useEffect, useRef, useState } from "react";
import { BrainCircuit, Download, Focus, RefreshCw } from "lucide-react";
import { errorMessage, processorFetch, type Connection, type FocusedPair } from "./inspection-api";

type Group = { id: string; kind: string; count: number; types: string[]; source_names: string[]; representative: FocusedPair };
type Conclusion = {
  id: string; created_at: string; stale: boolean;
  proposal: { assessment: string; summary: string; priorities: { group_id: string; action: string; rationale: string }[]; next_steps: string[]; citations: string[]; requires_review: true };
  evidence: { scope: string; issue_count: number; kind_counts: Record<string, number>; review_counts: Record<string, number>; group_count: number; groups: Group[]; run_status: string; assessment: string; coverage: { tested_elements: number; missing_geometry?: number; nonmanifold?: number }; diagnostics: string[] };
  metrics: { elapsed_seconds: number; input_tokens: number; output_tokens: number };
  model: { id: string; fine_tuned: boolean; quantization: string; revision: string };
};
const labels: Record<string, string> = {
  intersection: "Giao hình học", clearance: "Khoảng hở", surface_review: "Bề mặt cần rà soát",
  verify_geometry: "Xác minh chất lượng hình học", review_routing: "Rà soát tuyến cơ điện", review_clearance: "Rà soát khoảng hở",
  coordinate_structure: "Phối hợp kết cấu theo phê duyệt", review_design_intent: "Đối chiếu ý đồ thiết kế",
  review_system_requirements: "Kiểm tra yêu cầu vận hành và bảo trì", structural_approval: "Xin xác nhận của người phụ trách kết cấu",
  recheck_geometry: "Chạy lại kiểm tra sau khi chỉnh mô hình",
};
const assessments: Record<string, string> = {
  incomplete: "Chưa đủ cơ sở kết luận toàn bộ", findings: "Có bằng chứng cần phối hợp",
  clear_in_scope: "Không phát hiện trong phạm vi đã kiểm tra",
};
const count = new Intl.NumberFormat("vi-VN");

export default function RunConclusion({ connection, projectId, runId, locked, canGenerate, refreshKey, onBusyChange, onFocus }: {
  connection: Connection; projectId: string; runId: string; locked: boolean; canGenerate: boolean; refreshKey: number;
  onBusyChange: (busy: boolean) => void; onFocus: (pair: FocusedPair) => void;
}) {
  const url = `/api/projects/${projectId}/runs/${runId}/conclusions`;
  const [runtime, setRuntime] = useState<{ configured: boolean; files_present: boolean; error?: string } | null>(null);
  const [history, setHistory] = useState<Conclusion[]>([]), [total, setTotal] = useState(0), [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(true), [error, setError] = useState(""), [message, setMessage] = useState("");
  const request = useRef<AbortController | null>(null), busyRef = useRef(onBusyChange);
  busyRef.current = onBusyChange;
  const conclusion = history.find(item => item.id === selected) ?? history[0];
  const blocked = busy || loading || locked;
  async function load(append = false) {
    const abort = new AbortController(); request.current?.abort(); request.current = abort;
    setLoading(true); setError("");
    try {
      const [status, data] = await Promise.all([
        processorFetch(connection, "/api/projects/ai/runtime", { signal: abort.signal }).then(response => response.json()),
        processorFetch(connection, `${url}?offset=${append ? history.length : 0}&limit=5`, { signal: abort.signal }).then(response => response.json() as Promise<{ items: Conclusion[]; total: number }>),
      ]);
      if (!abort.signal.aborted) { setRuntime(status); setHistory(previous => append ? [...previous, ...data.items] : data.items); setTotal(data.total); }
    } catch (failure) { if (!abort.signal.aborted) setError(failure instanceof Error ? failure.message : "Chưa tải được kết luận."); }
    finally { if (!abort.signal.aborted) setLoading(false); }
  }
  useEffect(() => { void load(); return () => { request.current?.abort(); busyRef.current(false); }; }, [connection.base_url, connection.token, projectId, runId, refreshKey]);
  async function generate() {
    if (blocked || !canGenerate) return;
    const abort = new AbortController(); request.current?.abort(); request.current = abort;
    setBusy(true); busyRef.current(true); setError(""); setMessage("");
    let timedOut = false;
    const timeout = setTimeout(() => { timedOut = true; abort.abort(); }, 240000);
    try {
      const saved: Conclusion = await processorFetch(connection, url, { method: "POST", signal: abort.signal }).then(response => response.json());
      if (!abort.signal.aborted) { setHistory(previous => [saved, ...previous]); setSelected(saved.id); setTotal(value => value + 1); setMessage("Đã lưu kết luận theo dữ liệu của lượt kiểm tra này."); }
    } catch (failure) {
      if (timedOut) setError(errorMessage("ai_timeout"));
      else if (!abort.signal.aborted) setError(failure instanceof Error ? failure.message : "Chưa tạo được kết luận.");
    } finally { clearTimeout(timeout); if (request.current === abort) { setBusy(false); busyRef.current(false); } }
  }
  function download() {
    if (!conclusion) return;
    const blob = URL.createObjectURL(new Blob([JSON.stringify(conclusion, null, 2)], { type: "application/json" }));
    const anchor = document.createElement("a"); anchor.href = blob; anchor.download = `conclusion-${runId}-${conclusion.id}.json`; anchor.click();
    setTimeout(() => URL.revokeObjectURL(blob), 1000);
  }
  return <section className="run-conclusion ai-advice issue-review" aria-label="Kết luận tổng thể Qwen" aria-busy={busy || loading}>
    <h3><BrainCircuit size={22} />Kết luận tổng thể · Qwen3-4B</h3>
    <p className="project-muted">Tổng hợp toàn bộ kết quả đã lưu, kể cả các trang chưa mở. Qwen nhận thống kê và nhóm tiêu biểu; số liệu và giới hạn độ phủ do app xác nhận.</p>
    <div className="review-actions">
      <button className="button button-primary" disabled={blocked || !canGenerate || !runtime?.configured || !runtime.files_present} onClick={() => void generate()}><BrainCircuit size={16} />Tạo kết luận tổng thể</button>
      {busy ? <button className="button" onClick={() => { request.current?.abort(); setBusy(false); busyRef.current(false); setMessage("Đã yêu cầu hủy Qwen. Các kết luận đã lưu được giữ nguyên."); }}>Hủy tạo kết luận</button>
        : <button className="button" disabled={blocked} onClick={() => void load()}><RefreshCw size={16} />Tải lại kết luận</button>}
      {conclusion && <button className="button" disabled={blocked} onClick={download}><Download size={16} />Tải kết luận JSON</button>}
    </div>
    {runtime && (!runtime.configured || !runtime.files_present) && <p className="project-muted">{errorMessage(runtime.error || (!runtime.configured ? "ai_not_configured" : "ai_runtime_missing"))}</p>}
    {!canGenerate && <p className="project-muted">Bạn có thể xem kết luận đã lưu. Cần quyền rà soát để tạo kết luận mới.</p>}
    {busy && <p className="project-muted" role="status">Đang xác minh model và tổng hợp bằng Qwen trên laptop… Có thể mất vài phút.</p>}
    {loading && <p className="project-muted" role="status">Đang tải kết luận đã lưu…</p>}
    {!!history.length && <label>Kết luận đã lưu<select aria-label="Kết luận tổng thể đã lưu" value={conclusion?.id} disabled={blocked} onChange={event => { setSelected(event.target.value); setMessage(""); }}>{history.map(item => <option key={item.id} value={item.id}>{new Date(item.created_at).toLocaleString("vi-VN")} · {item.id.slice(0, 8)}</option>)}</select></label>}
    {history.length < total && <button className="button" disabled={blocked} onClick={() => void load(true)}>Thêm 5 kết luận cũ</button>}
    {conclusion && <div className="ai-result" data-testid="run-conclusion-result">
      <span className="review-tag">CẦN NGƯỜI PHỤ TRÁCH RÀ SOÁT</span>
      {conclusion.stale && <p className="coord-error" role="note">Nhãn hoặc dữ liệu đã thay đổi sau khi tạo bản này. Tạo kết luận mới để cập nhật; bản cũ được giữ làm lịch sử.</p>}
      <h4>{assessments[conclusion.evidence.assessment]}</h4>
      <p>{conclusion.proposal.summary}</p>
      <div className="run-conclusion-stats">{["intersection", "clearance", "surface_review"].map(kind => <div key={kind}><strong>{count.format(conclusion.evidence.kind_counts[kind] ?? 0)}</strong><span>{labels[kind]}</span></div>)}</div>
      <p className="project-muted">{count.format(conclusion.evidence.issue_count)} cặp đã lưu · {count.format(conclusion.evidence.issue_count - conclusion.evidence.review_counts.unreviewed)} cặp có nhãn rà soát. Đây là bằng chứng cần xem xét, chưa phải số lỗi thiết kế đã được xác nhận.</p>
      {conclusion.proposal.priorities.map((priority, index) => {
        const group = conclusion.evidence.groups.find(item => item.id === priority.group_id);
        return group && <article key={priority.group_id}>
          <h5>{index + 1}. {labels[priority.action]}</h5>
          <p>{priority.rationale}</p>
          <p className="ai-target">{group.types.join(" ↔ ")} · {count.format(group.count)} bằng chứng · {labels[group.kind]}</p>
          <small>{group.source_names.join(" / ")}</small>
          <button className="button" disabled={blocked} aria-label={`Xem minh chứng kết luận ${index + 1} trong 3D`} onClick={() => onFocus(group.representative)}><Focus size={16} />Xem cặp minh chứng trong 3D</button>
        </article>;
      })}
      <h5>Bước tiếp theo</h5><ul>{conclusion.proposal.next_steps.map(step => <li key={step}>{labels[step]}</li>)}</ul>
      <details><summary>Phạm vi tổng hợp và nguồn kết luận</summary>
        <p>Thống kê toàn bộ {count.format(conclusion.evidence.issue_count)} cặp đã lưu. Qwen nhận {conclusion.evidence.groups.length}/{count.format(conclusion.evidence.group_count)} nhóm tiêu biểu; không đọc riêng từng cặp. Bộ lọc trên bảng không thay đổi phạm vi này.</p>
        <p>{count.format(conclusion.evidence.coverage.tested_elements)} cấu kiện có hình học · {count.format(conclusion.evidence.coverage.missing_geometry ?? 0)} thiếu hình học · {count.format(conclusion.evidence.coverage.nonmanifold ?? 0)} lưới chưa kín.</p>
        {conclusion.evidence.diagnostics.map(code => <p key={code}>{errorMessage(code)}</p>)}
        <p className="project-muted">{conclusion.model.id} · {conclusion.model.quantization} · model gốc chưa fine-tune · {conclusion.metrics.elapsed_seconds.toFixed(1)} giây · {conclusion.metrics.input_tokens} token vào / {conclusion.metrics.output_tokens} token ra. Nguồn và mã mô hình được giữ trong JSON.</p>
      </details>
    </div>}
    {message && <p className="review-saved" role="status">{message}</p>}
    {error && <p className="coord-error" role="alert">{error}</p>}
  </section>;
}

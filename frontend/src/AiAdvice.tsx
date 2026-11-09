import { useEffect, useRef, useState } from "react";
import { BrainCircuit, RefreshCw } from "lucide-react";
import { errorMessage, processorFetch, type ClashElement, type Connection, type Inspection } from "./inspection-api";

import { getAccount } from "./account-api";

type Feedback = { revision: number; state: string; reviewer: string; note: string };
type Advice = {
  id: string; created_at: string; model: { id: string; revision: string; fine_tuned: boolean; quantization: string };
  proposal: { summary: string; options: { action: string; target: string; rationale: string; checks: string[]; references: ClashElement[] }[]; missing_data: string[]; citations: string[]; requires_review: true };
  references: { id: string; title: string; version: string; text: string; page?: number; sha256?: string; scope: string }[];
  feedback: Feedback; metrics: { elapsed_seconds: number; input_tokens: number; output_tokens: number; tokens_per_second?: number };
};
const labels: Record<string, string> = {
  reroute: "Xem xét đổi tuyến cơ điện", adjust_level: "Xem xét điều chỉnh cao độ tuyến", coordinate_opening: "Phối hợp lỗ mở theo phê duyệt", verify_geometry: "Xác minh hình học và ý đồ thiết kế", check_clearance: "Rà soát yêu cầu khoảng hở",
  system_requirements: "Yêu cầu vận hành, lắp đặt và bảo trì", structural_approval: "Phê duyệt của người phụ trách kết cấu", design_intent: "Ý đồ thiết kế", complete_geometry: "Hình học đầy đủ và khép kín", recheck_geometry: "Chạy lại kiểm tra sau khi thay đổi", route_levels: "Cao độ và thông tin tuyến",
};

export default function AiAdvice({ connection, projectId, runId, issueId, documents, locked, onBusyChange }: {
  connection: Connection; projectId: string; runId: string; issueId: string; documents: Inspection[]; locked: boolean; onBusyChange: (busy: boolean) => void;
}) {
  const url = `/api/projects/${projectId}/runs/${runId}/issues/${issueId}/advice`;
  const [runtime, setRuntime] = useState<{ configured: boolean; files_present: boolean; error?: string } | null>(null);
  const [history, setHistory] = useState<Advice[]>([]), [total, setTotal] = useState(0), [selected, setSelected] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const [busy, setBusy] = useState(false), [saving, setSaving] = useState(false), [loading, setLoading] = useState(true);
  const [error, setError] = useState(""), [message, setMessage] = useState("");
  const [state, setState] = useState("accepted_for_review"), [reviewer, setReviewer] = useState(getAccount()?.display_name ?? ""), [note, setNote] = useState("");
  const request = useRef<AbortController | null>(null);
  const busyRef = useRef(onBusyChange); busyRef.current = onBusyChange;
  const actionLocked = busy || saving || loading || locked;
  const advice = history.find(item => item.id === selected) ?? history[0];
  useEffect(() => { if (advice) { setState(advice.feedback.state === "unreviewed" ? "accepted_for_review" : advice.feedback.state); setReviewer(getAccount()?.display_name ?? advice.feedback.reviewer); setNote(advice.feedback.note); } }, [advice?.id, advice?.feedback.revision]);
  async function load(append = false) {
    const abort = new AbortController(); request.current?.abort(); request.current = abort; setLoading(true); setError("");
    try {
      const [status, data] = await Promise.all([
        processorFetch(connection, "/api/projects/ai/runtime", { signal: abort.signal }).then(response => response.json()),
        processorFetch(connection, `${url}?limit=5&offset=${append ? history.length : 0}`, { signal: abort.signal }).then(response => response.json() as Promise<{ items: Advice[]; total: number }>),
      ]);
      if (!abort.signal.aborted) { setRuntime(status); setHistory(previous => append ? [...previous, ...data.items] : data.items); setTotal(data.total); }
    } catch (error) { if (!abort.signal.aborted) setError(error instanceof Error ? error.message : "Chưa tải được đề xuất."); }
    finally { if (!abort.signal.aborted) setLoading(false); }
  }
  useEffect(() => { void load(); return () => { request.current?.abort(); busyRef.current(false); }; }, [connection.base_url, connection.token, projectId, runId, issueId]);
  async function generate() {
    if (actionLocked) return;
    const abort = new AbortController(); request.current?.abort(); request.current = abort; setBusy(true); busyRef.current(true); setError(""); setMessage("");
    try {
      const data: Advice = await processorFetch(connection, url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ document_ids: chosen }), signal: abort.signal }).then(response => response.json());
      if (!abort.signal.aborted) { setHistory(previous => [data, ...previous]); setTotal(value => value + 1); setSelected(data.id); setMessage("Đã lưu đề xuất. Cần rà soát trước khi sửa thiết kế."); }
    } catch (error) { if (!abort.signal.aborted) setError(error instanceof Error ? error.message : "Chưa tạo được đề xuất."); }
    finally { if (!abort.signal.aborted) { setBusy(false); busyRef.current(false); } }
  }
  async function feedback() {
    if (actionLocked || !advice || !reviewer.trim() || !note.trim()) return;
    const abort = new AbortController(); request.current?.abort(); request.current = abort; setSaving(true); setError(""); setMessage("");
    try {
      const data: Feedback = await processorFetch(connection, `${url}/${advice.id}/feedback`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ state, reviewer: reviewer.trim(), note: note.trim(), expected_revision: advice.feedback.revision }), signal: abort.signal }).then(response => response.json());
      if (!abort.signal.aborted) { setHistory(previous => previous.map(item => item.id === advice.id ? { ...item, feedback: data } : item)); setMessage("Đã lưu phản hồi về đề xuất. Nhãn xung đột giữ theo kết quả rà soát riêng."); }
    } catch (error) { if (!abort.signal.aborted) setError(error instanceof Error ? error.message : "Chưa lưu được phản hồi."); }
    finally { if (!abort.signal.aborted) setSaving(false); }
  }
  return <section className="ai-advice issue-review" aria-label="Đề xuất Qwen cho xung đột" aria-busy={busy || saving || loading}>
    <h4><BrainCircuit size={21} />Đề xuất phối hợp · Qwen3-4B</h4>
    <p className="project-muted">Chạy trên laptop · NF4 · model gốc chưa fine-tune chuyên ngành. Đề xuất bám theo cặp đang rà soát; cần người phụ trách xác nhận và chạy lại kiểm tra sau khi sửa.</p>
    {runtime && (!runtime.configured || !runtime.files_present) && <p className="project-muted">{errorMessage(runtime.error || (!runtime.configured ? "ai_not_configured" : "ai_runtime_missing"))}</p>}
    {!!documents.length && <fieldset disabled={actionLocked}><legend>PDF tham chiếu · chọn tối đa 3 tệp đang mở</legend>{documents.map(document => <label className="ai-document" key={document.id}><input type="checkbox" checked={chosen.includes(document.id)} disabled={!chosen.includes(document.id) && chosen.length >= 3} onChange={event => setChosen(previous => event.target.checked ? [...previous, document.id] : previous.filter(id => id !== document.id))} /><span>{document.name}</span></label>)}</fieldset>}
    <div className="review-actions"><button className="button" disabled={actionLocked || !runtime?.configured || !runtime.files_present} onClick={() => void generate()}><BrainCircuit size={16} />Tạo đề xuất bằng Qwen</button>{busy ? <button className="button" onClick={() => { request.current?.abort(); setBusy(false); busyRef.current(false); setMessage("Đã yêu cầu hủy Qwen; đề xuất đã lưu trước đó được giữ lại."); }}>Hủy chạy Qwen</button> : <button className="button" disabled={actionLocked} onClick={() => void load()}><RefreshCw size={16} />Tải lại đề xuất</button>}</div>
    {busy && <p role="status" className="project-muted">Đang kiểm tra model và chạy Qwen trên GPU… Có thể mất vài phút trên laptop.</p>}
    {loading && <p role="status" className="project-muted">Đang tải lịch sử đề xuất…</p>}
    {!!history.length && <label>Đề xuất đã lưu<select aria-label="Đề xuất đã lưu" value={advice?.id} disabled={actionLocked} onChange={event => { setSelected(event.target.value); setMessage(""); }}>{history.map(item => <option key={item.id} value={item.id}>{new Date(item.created_at).toLocaleString("vi-VN")} · {item.id.slice(0, 8)}</option>)}</select></label>}
    {history.length < total && <button className="button" disabled={actionLocked} onClick={() => void load(true)}>Thêm 5 đề xuất cũ</button>}
    {advice && <div className="ai-result" data-testid="ai-result">
      <span className="review-tag">CẦN RÀ SOÁT · {advice.feedback.state === "rejected" ? "Đã từ chối đề xuất" : advice.feedback.state === "accepted_for_review" ? "Đã chọn để xem xét" : "Chưa phản hồi"}</span>
      <p>{advice.proposal.summary}</p>
      {advice.proposal.options.map((option, index) => <article key={index}><h5>{labels[option.action]}</h5><p>{option.rationale}</p><p className="ai-target">Đối tượng: {option.references.map(ref => `${ref.ifc_type} · ${ref.guid}`).join(" / ")}</p><ul>{option.checks.map(check => <li key={check}>{labels[check]}</li>)}</ul></article>)}
      {!!advice.proposal.missing_data.length && <p>Dữ liệu cần bổ sung: {advice.proposal.missing_data.map(item => labels[item]).join("; ")}.</p>}
      <details><summary>Nguồn tham chiếu và lần chạy</summary>{advice.references.filter(ref => advice.proposal.citations.includes(ref.id)).map(ref => <div className="ai-reference" key={ref.id}><strong>{ref.title}{ref.page ? ` · trang ${ref.page}` : " · hướng dẫn chung, không phải quy chuẩn"}</strong><small>Phiên bản {ref.version}{ref.sha256 ? ` · SHA-256 ${ref.sha256}` : ""}</small><p>{ref.text}</p></div>)}<p className="project-muted">{advice.model.id} · {advice.model.quantization} · mã mô hình {advice.model.revision}<br />{advice.metrics.elapsed_seconds.toFixed(1)} giây · {advice.metrics.input_tokens} token vào / {advice.metrics.output_tokens} token ra.</p></details>
      <form onSubmit={event => { event.preventDefault(); void feedback(); }}><h5>Phản hồi riêng về đề xuất</h5><label>Đánh giá đề xuất<select aria-label="Đánh giá đề xuất" value={state} disabled={actionLocked} onChange={event => setState(event.target.value)}><option value="accepted_for_review">Chọn để tiếp tục xem xét</option><option value="rejected">Từ chối đề xuất</option><option value="unreviewed">Chưa rà soát</option></select></label><label>Người phản hồi<input aria-label="Người phản hồi đề xuất" value={getAccount()?.display_name ?? reviewer} readOnly={!!getAccount()} maxLength={80} disabled={actionLocked} onChange={event => setReviewer(event.target.value)} /></label><label>Nhận xét đề xuất<textarea aria-label="Nhận xét đề xuất" value={note} maxLength={2000} disabled={actionLocked} onChange={event => setNote(event.target.value)} /></label><button className="button" disabled={actionLocked || !reviewer.trim() || !note.trim()}>Lưu phản hồi đề xuất</button></form>
    </div>}
    {message && <p className="review-saved" role="status">{message}</p>}
    {error && <p className="coord-error" role="alert">{error}</p>}
  </section>;
}

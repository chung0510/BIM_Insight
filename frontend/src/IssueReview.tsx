import { useEffect, useRef, useState } from "react";
import { CheckCircle2, Eye, Save } from "lucide-react";
import { processorFetch, type FocusedPair, type Connection, type Review, type ReviewedCase } from "./inspection-api";

import { getAccount } from "./account-api";

export const issueStates: Record<string, string> = { unreviewed: "Chưa rà soát", needs_fix: "Cần sửa", intentional: "Giao có chủ ý", insufficient_data: "Thiếu dữ liệu" };
export const caseLabels: Record<string, string> = { unreviewed: "Chưa rà soát", intersection: "Giao hình học", clearance: "Thiếu khoảng hở", no_clash: "Không giao trong ca", insufficient_data: "Thiếu dữ liệu", surface_review: "Bề mặt cần rà soát" };
export const emptyReview: Review = { revision: 0, label: "unreviewed", reviewer: "", note: "", updated_at: null };

export function ReviewEditor({ connection, projectId, runId, itemId, kind, initial, locked, onSaved, onBusyChange, defaultReviewer }: {
  connection: Connection; projectId: string; runId: string; itemId: string; kind: "issues" | "cases";
  initial: Review; locked: boolean; defaultReviewer: string; onSaved: (review: Review) => void; onBusyChange: (busy: boolean) => void;
}) {
  const [reviewer, setReviewer] = useState(getAccount()?.display_name || initial.reviewer || defaultReviewer), [note, setNote] = useState(initial.note);
  const [value, setValue] = useState<string>(initial.state ?? initial.label ?? "unreviewed");
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [message, setMessage] = useState("");
  const request = useRef<AbortController | null>(null), section = useRef<HTMLElement>(null);
  const isCase = kind === "cases";
  useEffect(() => { section.current?.scrollIntoView({ block: "center", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" }); }, [itemId]);
  useEffect(() => () => { request.current?.abort(); onBusyChange(false); }, [onBusyChange]);
  async function save() {
    if (busy || locked || !reviewer.trim() || ((isCase || value === "intentional") && !note.trim())) return;
    const abort = new AbortController(); request.current = abort; setBusy(true); onBusyChange(true); setError(""); setMessage("");
    try {
      const response = await processorFetch(connection, `/api/projects/${projectId}/runs/${runId}/${kind}/${itemId}/review`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ [isCase ? "label" : "state"]: value, reviewer: reviewer.trim(), note: note.trim(), expected_revision: initial.revision }), signal: abort.signal });
      const result: { review: Review } = await response.json();
      if (!abort.signal.aborted) { onSaved(result.review); setMessage(isCase ? "Đã lưu nhãn ca." : "Đã lưu rà soát."); }
    } catch (error) { if (!abort.signal.aborted) setError(error instanceof Error ? error.message : "Chưa lưu được nhận xét."); }
    finally { if (!abort.signal.aborted) { setBusy(false); onBusyChange(false); } }
  }
  const options = isCase ? Object.entries(caseLabels).filter(([key]) => key !== "surface_review") : Object.entries(issueStates);
  return <section className="issue-review" aria-label={isCase ? "Rà soát ca dữ liệu" : "Rà soát xung đột"} ref={section}>
    <h4>{isCase ? "Gán nhãn ca dữ liệu" : "Rà soát bằng chứng đã chọn"}</h4>
    <p className="project-muted">Nhãn người dùng được lưu riêng với kết quả hình học và nhãn phân tích. Nhận xét không tự sửa mô hình hoặc tự loại bỏ bằng chứng.</p>
    <form onSubmit={event => { event.preventDefault(); void save(); }}>
      <label>Người rà soát<input aria-label="Người rà soát" value={getAccount()?.display_name ?? reviewer} readOnly={!!getAccount()} maxLength={80} required disabled={busy || locked} onChange={event => setReviewer(event.target.value)} /></label>
      <label>{isCase ? "Nhãn sau rà soát" : "Trạng thái rà soát"}<select aria-label={isCase ? "Nhãn sau rà soát" : "Trạng thái rà soát"} value={value} disabled={busy || locked} onChange={event => setValue(event.target.value)}>{options.map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></label>
      <label>Nhận xét<textarea aria-label="Nhận xét" value={note} maxLength={2000} required={isCase || value === "intentional"} disabled={busy || locked} onChange={event => setNote(event.target.value)} placeholder="Ghi căn cứ rà soát và dữ liệu còn thiếu nếu có." /></label>
      <button className="button" disabled={busy || locked || !reviewer.trim() || ((isCase || value === "intentional") && !note.trim())}><Save size={16} />{busy ? "Đang lưu…" : isCase ? "Lưu nhãn ca" : "Lưu rà soát"}</button>
    </form>
    {error && <p className="coord-error" role="alert">{error}</p>}
    {message && <p className="review-saved" role="status"><CheckCircle2 size={15} /> {message}</p>}
    {initial.updated_at && <p className="project-muted">Lần lưu {initial.revision} · {initial.reviewer} · {new Date(initial.updated_at).toLocaleString("vi-VN")}</p>}
  </section>;
}

export function CaseReviewPanel({ cases, connection, projectId, runId, locked, onFocus, onSaved, onBusyChange, reviewer, reloadKey, readOnly = false }: {
  cases: ReviewedCase[]; connection: Connection; projectId?: string | null; runId: string; locked: boolean; readOnly?: boolean;
  onFocus: (pair: FocusedPair | null) => void; onSaved: (caseId: string, review: Review) => void; onBusyChange: (busy: boolean) => void; reviewer: string; reloadKey: number;
}) {
  const [expected, setExpected] = useState("all"), [status, setStatus] = useState("all"), [page, setPage] = useState(0), [selected, setSelected] = useState("");
  useEffect(() => { setPage(0); }, [expected, status]);
  const filtered = cases.filter(item => (expected === "all" || item.expected === expected) && (status === "all" || (status === "reviewed" ? item.review.label !== "unreviewed" : item.review.label === "unreviewed")));
  const item = cases.find(item => item.case_id === selected);
  return <section className="pilot-cases" aria-label="Bộ ca gán nhãn">
    <h3>{cases.length} ca phân tích</h3>
    <p className="pilot-intro">Có cả ca giao và ca âm tính. Đây là một họ mô hình tổng hợp với nhãn phân tích; các biến thể cùng họ phải ở cùng nhóm chia train/test. Nhãn người dùng lưu riêng, chưa được coi là chuyên gia chấp thuận.</p>
    <div className="pilot-case-controls"><label>Lọc nhãn phân tích<select aria-label="Lọc nhãn phân tích" value={expected} onChange={event => setExpected(event.target.value)}><option value="all">Mọi nhãn phân tích</option>{["intersection", "clearance", "no_clash"].map(key => <option key={key} value={key}>{caseLabels[key]}</option>)}</select></label><label>Lọc trạng thái nhãn<select aria-label="Lọc trạng thái nhãn" value={status} onChange={event => setStatus(event.target.value)}><option value="all">Tất cả</option><option value="unreviewed">Chưa rà soát</option><option value="reviewed">Đã gán nhãn</option></select></label></div>
    <p className="project-muted">{cases.filter(item => item.review.label !== "unreviewed").length}/{cases.length} ca đã có nhãn người dùng · Hiển thị {filtered.length} ca theo bộ lọc.</p>
    <div className="pilot-case-list">{filtered.slice(page * 10, (page + 1) * 10).map(item => <article key={item.case_id} data-testid="pilot-case-row"><h4>{item.label}</h4><p>Nhãn phân tích: <strong>{caseLabels[item.expected]}</strong><br />Bộ máy: {caseLabels[item.detected] ?? item.detected}{!item.geometry_complete ? " · Hình học chưa đủ để kết luận" : ""}</p><span className="review-tag">Nhãn người dùng: {caseLabels[item.review.label ?? "unreviewed"]}</span><div><button className="button" aria-label={`Xem ca ${item.case_id} trong 3D`} onClick={() => onFocus({ id: `case:${item.case_id}`, a: item.a, b: item.b })}><Eye size={16} />Xem cặp trong 3D</button><button className="button" disabled={!projectId || locked} onClick={() => setSelected(item.case_id)}>Rà soát ca</button></div></article>)}</div>
    {!filtered.length && <p className="project-muted">Không có ca khớp bộ lọc.</p>}
    <div className="pilot-pages"><button className="button" disabled={!page} onClick={() => setPage(value => value - 1)}>Trang trước</button><span>{Math.min(filtered.length, page * 10 + 1)}–{Math.min(filtered.length, (page + 1) * 10)}/{filtered.length}</span><button className="button" disabled={(page + 1) * 10 >= filtered.length} onClick={() => setPage(value => value + 1)}>Trang sau</button></div>
    {!projectId && <p className="project-muted">Chọn dự án trước khi nhập và chạy để lưu nhãn người dùng.</p>}
    {item && projectId && <ReviewEditor key={`${item.case_id}:${reloadKey}`} connection={connection} projectId={projectId} runId={runId} itemId={item.case_id} kind="cases" initial={item.review} locked={locked || readOnly} onSaved={review => onSaved(item.case_id, review)} onBusyChange={onBusyChange} defaultReviewer={reviewer} />}
  </section>;
}

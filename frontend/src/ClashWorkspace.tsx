import { useEffect, useMemo, useRef, useState } from "react";
import ProcessingMemory, {processingPhase} from "./ProcessingMemory";
import { AlertTriangle, Download, Focus, ScanLine, X } from "lucide-react";
import { errorMessage, processorFetch, type ClashIssue, type ClashReport, type FocusedPair, type Connection, type Inspection, type LinkResult, type Review, type ReviewBundle } from "./inspection-api";
import { CaseReviewPanel, ReviewEditor, emptyReview, issueStates } from "./IssueReview";
import "./Clash.css";
import AiAdvice from "./AiAdvice";
import RunConclusion from "./RunConclusion";
import { getAccount } from "./account-api";
import { readClashStream, type ClashProgress } from "./clash-stream";

function GroupEvidence({ group, onChoose }: { group: ClashIssue[]; onChoose: (issue: ClashIssue) => void }) {
  const [open, setOpen] = useState(false), [page, setPage] = useState(0);
  const currentPage = Math.min(page, Math.max(0, Math.ceil(group.length / 100) - 1));
  return <details className="review-evidence-list" onToggle={event => setOpen(event.currentTarget.open)}><summary>{group.length} bằng chứng</summary>{open && <>
    {group.slice(currentPage * 100, (currentPage + 1) * 100).map((member, index) => <button className="button" key={member.id} onClick={() => onChoose(member)}>Bằng chứng {currentPage * 100 + index + 1}</button>)}
    {group.length > 100 && <nav aria-label="Phân trang bằng chứng trong nhóm"><button className="button" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>100 bằng chứng trước</button><span>Trang {currentPage + 1}/{Math.ceil(group.length / 100)}</span><button className="button" disabled={(currentPage + 1) * 100 >= group.length} onClick={() => setPage(currentPage + 1)}>100 bằng chứng tiếp</button></nav>}
  </>}</details>;
}

export default function ClashWorkspace({ models, connection, link, uploadsBusy, onFocus, onBusyChange, initialReport, onRunSaved, documents = [], canEdit = true, canReview = true }: {
  models: Inspection[];
  connection: Connection;
  link: LinkResult | null;
  uploadsBusy: boolean;
  onFocus: (issue: FocusedPair | null) => void;
  onBusyChange: (busy: boolean) => void;
  initialReport?: ClashReport | null;
  onRunSaved?: (report: ClashReport) => void;
  documents?: Inspection[]; canEdit?: boolean; canReview?: boolean;
}) {
  const [chosen, setChosen] = useState<string[] | null>(initialReport?.parameters?.model_ids ?? null);
  const [mode, setMode] = useState<string>(initialReport?.parameters?.mode ?? "hard");
  const [tolerance, setTolerance] = useState(String(initialReport?.parameters?.tolerance_mm ?? 1));
  const [clearance, setClearance] = useState(String(initialReport?.parameters?.clearance_mm ?? 50));
  const [frame, setFrame] = useState(false);
  const [shared, setShared] = useState(initialReport?.parameters?.shared_references_confirmed ?? false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<ClashProgress | null>(null);
  const [issueAiBusy, setIssueAiBusy] = useState(false), [conclusionBusy, setConclusionBusy] = useState(false);
  const aiBusy = issueAiBusy || conclusionBusy;
  const [conclusionRefresh, setConclusionRefresh] = useState(0);
  const [error, setError] = useState("");
  const [report, setReport] = useState<ClashReport | null>(initialReport ?? null);
  const [page, setPage] = useState(0);
  const [kindFilter, setKindFilter] = useState("all"), [disciplineFilter, setDisciplineFilter] = useState("all"), [storeyFilter, setStoreyFilter] = useState("all"), [stateFilter, setStateFilter] = useState("all");
  const [grouped, setGrouped] = useState(true), [selectedIssue, setSelectedIssue] = useState("");
  const [reviews, setReviews] = useState<ReviewBundle | null>(null), [reviewError, setReviewError] = useState(""), [reviewReload, setReviewReload] = useState(0), [reviewBusy, setReviewBusy] = useState(false), [reviewer, setReviewer] = useState(getAccount()?.display_name ?? "");
  const request = useRef<AbortController | null>(null);
  const modelKey = models.map(model => model.id).join(",");
  const lastModelKey = useRef(modelKey);
  const limits = connection.processing_limits;
  const ids = chosen ?? models.slice(0, limits.clash_models).map(model => model.id);
  const linked = link?.confirmed && ids.includes(link.model_id) ? link : null;
  const payload = { model_ids: ids, mode, tolerance_mm: Number(tolerance), clearance_mm: Number(clearance), coordinates_confirmed: frame, shared_references_confirmed: shared, link_id: linked?.id ?? null };
  const signature = JSON.stringify(payload);
  const lastSignature = useRef(signature);
  useEffect(() => { if (lastModelKey.current !== modelKey) { setChosen(null); setFrame(false); setShared(false); lastModelKey.current = modelKey; } }, [modelKey]);
  useEffect(() => { if (lastSignature.current === signature) return; lastSignature.current = signature; request.current?.abort(); setBusy(false); onBusyChange(false); setReport(null); setError(""); setPage(0); onFocus(null); }, [signature, onFocus, onBusyChange]);
  useEffect(() => () => { request.current?.abort(); onBusyChange(false); }, [onBusyChange]);
  useEffect(() => { setPage(0); }, [kindFilter, disciplineFilter, storeyFilter, stateFilter, grouped]);
  useEffect(() => {
    setReviews(null); setReviewError(""); setSelectedIssue("");
    if (!report?.project_id) return;
    const abort = new AbortController();
    processorFetch(connection, `/api/projects/${report.project_id}/runs/${report.id}/reviews`, { signal: abort.signal }).then(response => response.json()).then(data => { if (!abort.signal.aborted) setReviews(data); }).catch(error => { if (!abort.signal.aborted) setReviewError(error.message); });
    return () => abort.abort();
  }, [report?.id, reviewReload, connection.base_url, connection.token]);
  const reviewMap = useMemo(() => new Map(reviews?.issues.map(item => [item.issue_id, item.review]) ?? []), [reviews]);
  const storeys = useMemo(() => [...new Map(models.flatMap(model => model.result?.storeys ?? []).map(storey => [storey.guid, storey.name])).entries()], [models]);
  const rows = useMemo(() => {
    const filtered = (report?.issues ?? []).filter(issue => (kindFilter === "all" || issue.kind === kindFilter) && (disciplineFilter === "all" || models.some(model => model.discipline === disciplineFilter && [issue.a.source_id, issue.b.source_id].includes(model.id))) && (storeyFilter === "all" || [issue.a.storey_guid, issue.b.storey_guid].includes(storeyFilter)) && (stateFilter === "all" || (reviewMap.get(issue.id)?.state ?? "unreviewed") === stateFilter));
    const groups = new Map<string, ClashIssue[]>();
    for (const issue of filtered) { const key = grouped ? issue.group_id ?? issue.id : issue.id; const group = groups.get(key); if (group) group.push(issue); else groups.set(key, [issue]); }
    return [...groups.values()];
  }, [report, models, kindFilter, disciplineFilter, storeyFilter, stateFilter, grouped, reviewMap]);
  const currentPage = Math.min(page, Math.max(0, Math.ceil(rows.length / 100) - 1));
  function saveIssue(id: string, review: Review) { setReviewer(review.reviewer); setReviews(current => current ? { ...current, issues: current.issues.map(item => item.issue_id === id ? { ...item, review } : item) } : current); setConclusionRefresh(value => value + 1); }
  function saveCase(id: string, review: Review) { setReviewer(review.reviewer); setReviews(current => current ? { ...current, cases: current.cases.map(item => item.case_id === id ? { ...item, review } : item) } : current); }
  const canRun = canEdit && ids.length >= 2 && ids.length <= limits.clash_models && frame && models.filter(model => ids.includes(model.id)).every(model => model.clash_ready) && tolerance.trim() && clearance.trim() && Number(tolerance) >= .1 && Number(tolerance) <= 10 && Number(clearance) >= 1 && Number(clearance) <= 500;
  async function run() {
    if (!canRun || busy || aiBusy || uploadsBusy) return;
    const abort = new AbortController(); request.current = abort;
    let timedOut = false;
    let connectionLost = false, streaming = false, lastActivity = performance.now();
    const timer = setTimeout(() => { timedOut = true; abort.abort(); }, (limits.timeout_seconds + 60) * 1000);
    const heartbeat = setInterval(() => {
      if (performance.now() - lastActivity > (streaming ? 30000 : 120000)) { connectionLost = true; abort.abort(); }
    }, 1000);
    setBusy(true); onBusyChange(true); setError(""); setReport(null); onFocus(null); setProgress({ phase: "preparing", elapsed_seconds: 0 });
    try {
      const response = await processorFetch(connection, "/api/inspections/clashes", { method: "POST", headers: { "Content-Type": "application/json", Accept: "application/x-ndjson" }, body: JSON.stringify(payload), signal: abort.signal });
      streaming = response.headers.get("Content-Type")?.includes("application/x-ndjson") ?? false; lastActivity = performance.now();
      const result = await readClashStream(response, value => { lastActivity = performance.now(); if (!abort.signal.aborted && request.current === abort) setProgress(value); });
      if (!abort.signal.aborted) { setReport(result); onRunSaved?.(result); }
    } catch (error) {
      if (connectionLost) setError(errorMessage("clash_connection_lost"));
      else if (timedOut) setError(errorMessage("processing_timeout"));
      else if (!abort.signal.aborted) {
        const code = error && typeof error === "object" && "code" in error ? error.code : error instanceof TypeError || error instanceof SyntaxError ? "clash_connection_lost" : null;
        setError(code ? errorMessage(code) : error instanceof Error ? error.message : "Chưa hoàn tất kiểm tra va chạm.");
      }
    } finally { clearTimeout(timer); clearInterval(heartbeat); if (request.current === abort) { setBusy(false); onBusyChange(false); } }
  }
  async function exportDataset() {
    if (!report?.project_id) return;
    try {
      const response = await processorFetch(connection, `/api/projects/${report.project_id}/runs/${report.id}/dataset`);
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a"); anchor.href = url; anchor.download = `dataset-${report.id}.json`; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { setReviewError(error instanceof Error ? error.message : "Chưa xuất được bộ nhãn."); }
  }
  async function download() {
    if (!report) return;
    try {
      const response = await processorFetch(connection, report.report_url);
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a"); anchor.href = url; anchor.download = `clashes-${report.id}.json`; anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { setError(error instanceof Error ? error.message : "Không tải được báo cáo."); }
  }
  const synthetic = models.length > 0 && models.every(model => !!model.dataset);
  const analyticCases = report?.evaluation?.case_results ?? [];
  const caseRecords = report?.project_id ? reviews?.cases ?? [] : analyticCases.map(item => ({ ...item, review: emptyReview }));
  const reviewedIssue = report?.issues.find(issue => issue.id === selectedIssue);
  const diagnostics = [...new Set(report?.diagnostics.map(item => item.code) ?? [])];
  return <section className="clash-workspace" aria-label="Kiểm tra va chạm 3D" aria-busy={busy}>
    <div className="coord-heading"><div><span className="section-index">04 / KIỂM TRA VA CHẠM</span><h2>Nhìn rõ điểm cần phối hợp.</h2><p>So hình học giữa các tệp IFC. DXF định vị kết quả sau khi lưu liên kết đúng tầng.</p></div><span className={`clash-dataset ${synthetic ? "synthetic" : ""}`}>{synthetic ? "DỮ LIỆU TỔNG HỢP" : "HỒ SƠ CỦA BẠN"}</span></div>
    {synthetic && <p className="clash-scope-note">{models[0]?.dataset === "synthetic_pilot_v1" ? "60 ca phân tích có biến thể kích thước, góc xoay và vị trí." : "6 tình huống có đáp án hình học để kiểm chứng bộ máy."} Điểm đánh giá chỉ áp dụng cho họ mô hình tổng hợp này.</p>}
    <fieldset className="clash-models" disabled={busy || aiBusy || uploadsBusy || !canEdit}><legend>Chọn 2–{limits.clash_models} IFC để so với nhau</legend>{models.map(model => <label key={model.id}><input type="checkbox" aria-label={`Kiểm tra va chạm ${model.name}`} checked={ids.includes(model.id)} disabled={!ids.includes(model.id) && ids.length >= limits.clash_models} onChange={event => { setChosen(event.target.checked ? [...ids, model.id] : ids.filter(id => id !== model.id)); setFrame(false); setShared(false); }} /><span>{model.name}<small>{model.discipline} · {model.clash_ready ? "Có bản nguồn để kiểm tra" : "Cần nhập và kiểm tra lại tệp"}</small></span></label>)}{models.length < 2 && <p>Thêm IFC của bộ môn khác trong cùng dự án để kiểm tra va chạm 3D.</p>}</fieldset>
    <p className="clash-scope-note">Mỗi lượt: tối đa {limits.clash_elements.toLocaleString("vi-VN")} cấu kiện, {limits.clash_issues.toLocaleString("vi-VN")} bằng chứng và {Math.ceil(limits.timeout_seconds / 60)} phút. Kết quả chạm giới hạn luôn được ghi là chưa đầy đủ. Tệp JSON xuất toàn bộ kết quả đã lưu, kể cả các trang chưa mở.</p>
    <div className="coord-form clash-form">
      <label>Chế độ<select aria-label="Chế độ kiểm tra va chạm" value={mode} disabled={busy || aiBusy || !canEdit} onChange={event => setMode(event.target.value)}><option value="hard">Giao hình học (hard clash)</option><option value="clearance">Giao và khoảng hở (clearance)</option></select></label>
      <label>Ngưỡng giao (mm)<input aria-label="Ngưỡng giao (mm)" type="number" min="0.1" max="10" step="0.1" value={tolerance} disabled={busy || aiBusy || !canEdit} onChange={event => setTolerance(event.target.value)} /></label>
      <label>Khoảng hở yêu cầu (mm)<input aria-label="Khoảng hở yêu cầu (mm)" type="number" min="1" max="500" value={clearance} disabled={busy || aiBusy || !canEdit || mode !== "clearance"} onChange={event => setClearance(event.target.value)} /></label>
    </div>
    <p className="clash-scope-note">Các ngưỡng trên do bạn chọn cho lượt kiểm tra này. Số đo xấp xỉ từ lưới tam giác IFC. Chỉ so giữa các tệp; chưa kiểm tra các cấu kiện trong cùng một IFC.</p>
    <label className="coord-confirm"><input type="checkbox" aria-label="Tôi đã kiểm tra các IFC cùng công trình và hệ tọa độ" checked={frame} disabled={busy || aiBusy || uploadsBusy || !canEdit} onChange={event => setFrame(event.target.checked)} /><span>Tôi đã kiểm tra các IFC cùng công trình và hệ tọa độ.</span></label>
    <details className="clash-reference"><summary>Đối tượng được tham chiếu ở nhiều IFC</summary><p>Giữ mặc định khi chưa xác minh. Các cặp cùng GUID tham chiếu sẽ được báo chưa đủ cơ sở, thay vì coi là hai cấu kiện độc lập.</p><label className="coord-confirm"><input type="checkbox" checked={shared} disabled={busy || aiBusy || !canEdit} onChange={event => setShared(event.target.checked)} /><span>Tôi đã xác minh các đối tượng cùng GUID và cùng nhóm cấu kiện là tham chiếu dùng chung; bỏ qua các cặp này.</span></label></details>
    <div className="clash-actions"><button className="button button-primary" disabled={!canRun || busy || aiBusy || uploadsBusy} onClick={() => void run()}><ScanLine size={17} />Chạy kiểm tra va chạm</button>{busy && <button className="button" onClick={() => { request.current?.abort(); setBusy(false); onBusyChange(false); setError("Đã hủy kiểm tra. Chưa có kết luận cho lần chạy này."); }}><X size={16} />Hủy kiểm tra va chạm</button>}<span role="status">{busy ? "Đang dựng hình học và kiểm tra…" : aiBusy ? "Qwen đang dùng bộ xử lý local" : linked ? "Có liên kết DXF để đối chiếu mặt bằng" : "Kiểm tra trực tiếp IFC · DXF không bắt buộc"}</span></div>
    {busy && progress && <div className="clash-progress" data-testid="clash-progress" role="status" aria-live="polite">
      <strong>{processingPhase(progress.phase)}</strong>
      {progress.source_name && <span>Mô hình {progress.source_index}/{progress.source_count}: {progress.source_name}</span>}
      {progress.total !== undefined && progress.total > 0 && <><progress value={progress.done ?? 0} max={progress.total} aria-label="Tiến độ bước kiểm tra hiện tại" /><span>{(progress.done ?? 0).toLocaleString("vi-VN")}/{progress.total.toLocaleString("vi-VN")} {progress.phase === "checking_pairs" ? "lô so sánh" : "cấu kiện"}</span></>}
      <small>Đã chạy {Math.floor(progress.elapsed_seconds ?? 0)} giây{progress.issues !== undefined ? ` · ${progress.issues.toLocaleString("vi-VN")} bằng chứng đang thu thập` : ""}. Chưa có kết luận cho tới khi hoàn tất.</small>
      <ProcessingMemory stats={progress} />
    </div>}
    {error && <p className="coord-error" role="alert">{error}</p>}
    {report && <div className="clash-results">
      {!!report.project_id && <p className="project-current">{report.status === "failed" ? "Lượt kiểm tra chưa hoàn tất đã được lưu trong lịch sử dự án." : initialReport?.id === report.id ? "Đang xem lượt kiểm tra đã lưu. Xác nhận tọa độ nếu muốn chạy một lượt mới." : "Lượt kiểm tra đã lưu trong dự án."}</p>}
      <div className={`clash-verdict ${report.status}`} role="status"><ScanLine size={20} /><div><strong>{report.status === "completed" ? "Hoàn tất trong phạm vi đã chọn" : report.status === "partial" ? "Đã kiểm tra một phần — cần xem lại" : "Kiểm tra chưa hoàn tất"}</strong><p>{report.status === "failed" ? "Chưa có kết luận va chạm." : `${report.issues.length} cặp cần xem xét${report.elapsed_seconds !== undefined ? ` · ${report.elapsed_seconds.toFixed(1)} giây` : ""}`}{report.verdict === "clear_in_scope" ? " · Không phát hiện trong hình học đã kiểm tra." : ""}</p></div><button className="button" onClick={() => void download()}><Download size={16} />Tải kết quả va chạm JSON</button></div>
      {report.coverage && <><div className="clash-metrics"><div><strong>{report.coverage.tested_elements}</strong><span>Cấu kiện đã kiểm tra</span></div><div><strong>{report.coverage.routing_elements}</strong><span>Ống / gió / cáp có hình học</span></div><div><strong>{report.coverage.missing_geometry}</strong><span>Thiếu hình học</span></div><div><strong>{report.coverage.nonmanifold}</strong><span>Hình học chưa kín</span></div></div>{!report.coverage.routing_elements && <p className="clash-scope-note"><AlertTriangle size={16} />Không có tuyến ống, ống gió hoặc cáp trong phạm vi này. Chưa đánh giá xung đột các hệ đó.</p>}</>}
      {diagnostics.length > 0 && <div className="clash-diagnostics" role="note">{diagnostics.map(code => <p key={code}><AlertTriangle size={15} />{errorMessage(code)}</p>)}</div>}
      {!!report.coverage?.reference_elements && <p className="clash-scope-note">Đã thống kê riêng {report.coverage.reference_elements.toLocaleString("vi-VN")} đối tượng đường/điểm tham chiếu. Các đối tượng này không được tính là thiếu hình học vật lý.</p>}
      {!!report.geometry_diagnostics?.length && <details className="inspection-elements"><summary>Cấu kiện chưa đánh giá · {report.geometry_diagnostics.length.toLocaleString("vi-VN")}</summary>
        {report.geometry_diagnostics.slice(0, 100).map((item, index) => <div key={`${item.source_id}-${item.guid}-${index}`}><strong>{item.name || item.ifc_type}</strong><small>{item.source_name} · {errorMessage(item.reason)}</small><code>{item.guid}</code>{item.detail && <small>{item.detail}</small>}</div>)}
        {report.geometry_diagnostics.length > 100 && <p>Hiển thị 100 mục đầu. Tải JSON để xem toàn bộ.</p>}
      </details>}
      {report.diagnostics.filter(item => item.code === "processing_memory_limit" && item.peak_memory_bytes !== undefined && item.memory_limit_bytes !== undefined).map((item, index) => <p className="clash-scope-note" key={`memory-${index}`}>RAM tiến trình cao nhất: {(item.peak_memory_bytes! / 1024 ** 3).toFixed(2)} GiB · Ngân sách: {(item.memory_limit_bytes! / 1024 ** 3).toFixed(2)} GiB{item.elapsed_seconds !== undefined ? ` · Dừng sau ${Math.floor(item.elapsed_seconds)} giây` : ""}. Chưa có kết luận va chạm.</p>)}
      {report.evaluation && <div className="clash-evaluation"><strong>{report.evaluation.cases} ca mẫu · Precision {(report.evaluation.precision * 100).toFixed(0)}% · Recall {(report.evaluation.recall * 100).toFixed(0)}%</strong><p>Đánh giá ca bị gắn cờ, gồm bề mặt cần rà soát, trên dữ liệu tổng hợp với ngưỡng 1 mm / 50 mm; không phải tỷ lệ lỗi thiết kế đã xác nhận.</p>{report.evaluation.uncertain_cases !== undefined && <p>{report.evaluation.assessed_cases}/{report.evaluation.cases} ca có hai mesh kín · {report.evaluation.uncertain_cases} ca cần rà soát/thiếu dữ liệu · Đúng cả loại kết quả: {((report.evaluation.typed_case_accuracy ?? 0) * 100).toFixed(1)}%. Danh sách sai khác được giữ trong bộ ca bên dưới.</p>}</div>}
      <div className="review-actions"><button className="button" disabled={!report.project_id || !reviews || reviewBusy} onClick={() => void exportDataset()}><Download size={16} />Xuất bộ nhãn JSON</button>{report.project_id && <button className="button" disabled={reviewBusy || aiBusy} onClick={() => { setReviewReload(value => value + 1); setConclusionRefresh(value => value + 1); }}>Tải lại nhãn</button>}<span className="review-count">{report.project_id ? reviews ? `${reviews.issues.filter(item => item.review.state !== "unreviewed").length}/${report.issues.length} bằng chứng có nhận xét` : "Chưa tải được nhãn người dùng" : "Báo cáo cũ chưa gắn với dự án. Nhập lại vào dự án để lưu các lần rà soát mới."}</span></div>
      {reviewError && <p className="coord-error" role="alert">{reviewError}</p>}
      {report.project_id && report.status !== "failed" && !!report.coverage?.tested_elements && <RunConclusion key={report.id} connection={connection} projectId={report.project_id} runId={report.id} locked={uploadsBusy || busy || reviewBusy || aiBusy} canGenerate={canReview} refreshKey={conclusionRefresh} onFocus={onFocus} onBusyChange={value => { setConclusionBusy(value); onBusyChange(value || issueAiBusy || busy); }} />}
      {report.issues.length > 0 && <>
        <p className="clash-scope-note">Chọn một cặp để cô lập và tô hai màu trên 3D phía trên. Chỉ số xuyên/giao của bộ máy không phải khoảng dịch chuyển tối ưu để sửa lỗi.</p>
        <div className="review-controls">
          <label>Loại va chạm<select aria-label="Lọc loại va chạm" value={kindFilter} onChange={event => setKindFilter(event.target.value)}><option value="all">Tất cả</option><option value="intersection">Giao hình học</option><option value="clearance">Khoảng hở</option><option value="surface_review">Bề mặt cần rà soát</option></select></label>
          <label>Bộ môn<select aria-label="Lọc bộ môn va chạm" value={disciplineFilter} onChange={event => setDisciplineFilter(event.target.value)}><option value="all">Mọi bộ môn</option>{[...new Set(models.map(model => model.discipline))].map(value => <option key={value} value={value}>{value}</option>)}</select></label>
          <label>Tầng<select aria-label="Lọc tầng va chạm" value={storeyFilter} onChange={event => setStoreyFilter(event.target.value)}><option value="all">Mọi tầng</option>{storeys.map(([guid, name]) => <option key={guid} value={guid}>{name}</option>)}</select></label>
          <label>Trạng thái rà soát<select aria-label="Lọc trạng thái rà soát" value={stateFilter} disabled={!!report.project_id && !reviews} onChange={event => setStateFilter(event.target.value)}><option value="all">Tất cả</option>{Object.entries(issueStates).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        </div>
        <label className="review-group-toggle"><input type="checkbox" checked={grouped} onChange={event => setGrouped(event.target.checked)} />Gộp theo cặp nguồn/cấu kiện chính và loại đo</label>
        <p className="review-count">{rows.length} {grouped ? "nhóm" : "cặp"} · {rows.reduce((count, group) => count + group.length, 0)} bằng chứng theo bộ lọc. Các bằng chứng gốc được giữ nguyên.</p>
        <div className="clash-table-wrap"><table className="clash-table"><caption>Các cặp cấu kiện cần phối hợp</caption><thead><tr><th scope="col">Cặp</th><th scope="col">Cấu kiện</th><th scope="col">Kết quả hình học</th><th scope="col">Gợi ý xem xét theo quy tắc</th><th scope="col">Rà soát</th></tr></thead><tbody>{rows.slice(currentPage * 100, (currentPage + 1) * 100).map((group, offset) => {
          const index = currentPage * 100 + offset;
          const issue = group[0];
          const states = new Set(group.map(member => reviewMap.get(member.id)?.state ?? "unreviewed"));
          return <tr key={issue.id} data-testid="clash-row"><td><button className="button" aria-label={`Xem va chạm ${index + 1} trong 3D`} onClick={() => onFocus(issue)}><Focus size={16} />{String(index + 1).padStart(2, "0")}</button>{group.length > 1 && <GroupEvidence group={group} onChoose={member => { onFocus(member); setSelectedIssue(member.id); }} />}</td><td>{[issue.a, issue.b].map((element, i) => <div className={`clash-element element-${i}`} key={`${element.source_id}:${element.guid}`}><strong>{element.name || element.ifc_type}</strong><small>{element.source_name} · {element.ifc_type}</small><code>{element.guid}</code></div>)}</td><td><strong>{issue.kind === "intersection" ? "Giao hình học" : issue.kind === "clearance" ? "Thiếu khoảng hở" : "Giao bề mặt cần xem lại"}</strong>{issue.distance_m !== null && <p>{issue.kind === "clearance" ? "Khoảng cách" : "Chỉ số giao"} {(issue.distance_m * 1000).toFixed(1)} mm</p>}{issue.required_clearance_m !== null && <small>Yêu cầu đã chọn: {(issue.required_clearance_m * 1000).toFixed(0)} mm</small>}</td><td>{issue.recommendation}<small>Cần người thiết kế xác nhận.</small></td><td><span className="review-tag">{report.project_id && !reviews ? "Chưa tải nhãn" : states.size > 1 ? "Nhãn trong nhóm khác nhau" : issueStates[[...states][0]]}</span><button className="button" aria-label={`Rà soát cặp ${index + 1}`} disabled={!report.project_id || !reviews || reviewBusy || aiBusy || uploadsBusy} onClick={() => setSelectedIssue(issue.id)}>Rà soát</button></td></tr>;
        })}</tbody></table></div>
        {!rows.length && <p className="project-muted">Không có bằng chứng khớp bộ lọc.</p>}
        {rows.length > 100 && <nav className="review-actions" aria-label="Phân trang kết quả va chạm"><button className="button" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>100 cặp trước</button><span role="status">Trang {currentPage + 1}/{Math.ceil(rows.length / 100)} · {currentPage * 100 + 1}–{Math.min((currentPage + 1) * 100, rows.length)}/{rows.length}</span><button className="button" disabled={(currentPage + 1) * 100 >= rows.length} onClick={() => setPage(currentPage + 1)}>Xem thêm 100 cặp</button></nav>}
      </>}
      {report.project_id && reviewedIssue && reviews && <ReviewEditor key={`${reviewedIssue.id}:${reviewReload}`} connection={connection} projectId={report.project_id} runId={report.id} itemId={reviewedIssue.id} kind="issues" initial={reviewMap.get(reviewedIssue.id) ?? { ...emptyReview, state: "unreviewed" }} locked={uploadsBusy || busy || aiBusy || !canReview} onSaved={review => saveIssue(reviewedIssue.id, review)} onBusyChange={setReviewBusy} defaultReviewer={reviewer} />}
      {report.project_id && reviewedIssue && <AiAdvice key={`${report.id}:${reviewedIssue.id}`} connection={connection} projectId={report.project_id} runId={report.id} issueId={reviewedIssue.id} documents={documents.filter(document => document.project_id === report.project_id)} locked={uploadsBusy || busy || aiBusy || !canReview} onBusyChange={value => { setIssueAiBusy(value); onBusyChange(value || conclusionBusy || busy); }} />}
      {!!caseRecords.length && <CaseReviewPanel cases={caseRecords} connection={connection} projectId={report.project_id} runId={report.id} locked={uploadsBusy || busy || aiBusy} readOnly={!canReview} onFocus={onFocus} onSaved={saveCase} onBusyChange={setReviewBusy} reviewer={reviewer} reloadKey={reviewReload} />}
    </div>}
  </section>;
}

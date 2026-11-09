import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Download, Layers3, Link2, MoveUpRight } from "lucide-react";
import { processorFetch, type ClashReport, type FocusedPair, type Connection, type Inspection, type LinkResult } from "./inspection-api";
import "./Coordination.css";

const CadViewer = lazy(() => import("./CadViewer"));
const IfcViewer = lazy(() => import("./IfcViewer"));
const ClashWorkspace = lazy(() => import("./ClashWorkspace"));

export default function CoordinationWorkspace({ reports, connection, active, uploadsBusy, pauseViewer = false, onClashBusyChange, initialReport, projectName, onRunSaved, canEdit = true, canReview = true }: { reports: Inspection[]; connection: Connection; active: boolean; uploadsBusy: boolean; pauseViewer?: boolean; onClashBusyChange: (busy: boolean) => void; initialReport?: ClashReport | null; projectName?: string; onRunSaved?: (report: ClashReport) => void; canEdit?: boolean; canReview?: boolean }) {
  const initialLink = initialReport?.drawing_link;
  const drawings = useMemo(() => reports.filter(report => (report.kind === "dxf" || report.kind === "dwg" && report.result?.conversion) && report.assets?.drawing), [reports]);
  const models = useMemo(() => reports.filter(report => report.kind === "ifc" && report.assets?.mapping), [reports]);
  const viewerModels = useMemo(() => models.filter(report => report.assets?.model), [models]);
  const [drawingId, setDrawingId] = useState(initialLink?.drawing_id ?? "");
  const [modelId, setModelId] = useState(initialLink?.model_id ?? "");
  const [storeyId, setStoreyId] = useState(initialLink?.storey_guid ?? "");
  const [hiddenModels, setHiddenModels] = useState<Set<string>>(new Set());
  const [project, setProject] = useState(initialLink?.project_name ?? projectName ?? "");
  const [x, setX] = useState(String(initialLink?.dx_m ?? 0)), [y, setY] = useState(String(initialLink?.dy_m ?? 0)), [rotation, setRotation] = useState(String(initialLink?.rotation_deg ?? 0));
  const [sourcesConfirmed, setSourcesConfirmed] = useState(false);
  const [link, setLink] = useState<LinkResult | null>(initialLink ?? null);
  const [focus, setFocus] = useState<FocusedPair | null>(null);
  const viewerPane = useRef<HTMLElement>(null);
  const focusIssue = useCallback((issue: FocusedPair | null) => {
    setFocus(issue);
    // WebView2 can cancel a second smooth scroll when switching pairs quickly.
    if (issue) viewerPane.current?.scrollIntoView({ block: "start", behavior: "auto" });
  }, []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  const drawing = drawings.find(report => report.id === drawingId) ?? drawings[0];
  const reference = models.find(report => report.id === modelId) ?? models[0];
  const storeys = reference?.result?.storeys ?? [];
  const storey = storeys.find(item => item.guid === storeyId) ?? (storeys.length === 1 ? storeys[0] : undefined);
  const payload = { drawing_id: drawing?.id, model_id: reference?.id, storey_guid: storey?.guid, project_name: project.trim(), dx_m: Number(x), dy_m: Number(y), rotation_deg: Number(rotation) };
  const signature = JSON.stringify(payload);
  const lastSignature = useRef(signature);
  useEffect(() => { if (lastSignature.current === signature) return; lastSignature.current = signature; request.current?.abort(); setLink(null); setError(""); setSourcesConfirmed(false); setBusy(false); }, [signature]);
  useEffect(() => () => request.current?.abort(), []);
  const duplicates = useMemo(() => {
    const seen = new Set<string>(), shared = new Set<string>();
    for (const model of models) for (const guid of new Set(model.result?.source_guids ?? [])) {
      if (seen.has(guid)) shared.add(guid); seen.add(guid);
    }
    return shared.size;
  }, [models]);
  const canCompare = !uploadsBusy && !!drawing && !!reference && !!storey && !!project.trim() && [x, y, rotation].every(value => value.trim() && Number.isFinite(Number(value)));
  const markerLink = focus?.point_m && link?.confirmed && link.drawing_id === drawing?.id && [focus.a, focus.b].some(element => element.source_id === link.model_id && element.storey_guid === link.storey_guid) ? link : null;
  useEffect(() => { if (focus) setHiddenModels(current => { const next = new Set(current); next.delete(focus.a.source_id); next.delete(focus.b.source_id); return next.size === current.size ? current : next; }); }, [focus]);
  async function compare(confirmed: boolean) {
    if (!canCompare || busy) return;
    const abort = new AbortController(); request.current = abort; setBusy(true); setError("");
    try {
      const response = await processorFetch(connection, "/api/inspections/alignments", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...payload, confirmed, same_revision_confirmed: sourcesConfirmed }), signal: abort.signal });
      const result: LinkResult = await response.json();
      if (!abort.signal.aborted) setLink(result);
    } catch (error) { if (!abort.signal.aborted) setError(error instanceof Error ? error.message : "Chưa liên kết được hồ sơ."); }
    finally { if (!abort.signal.aborted) setBusy(false); }
  }
  async function downloadLink() {
    if (!link?.link_url) return;
    try {
      const response = await processorFetch(connection, link.link_url);
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a"); anchor.href = url; anchor.download = `drawing-link-${link.id}.json`; anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { setError(error instanceof Error ? error.message : "Không tải được liên kết."); }
  }
  if (!drawings.length && !models.length) return null;
  return <section className="coordination-workspace" aria-label="Phối hợp bản vẽ và mô hình" hidden={!active}>
    <div className="coord-heading"><div><span className="section-index">03 / ĐỐI CHIẾU CÔNG TRÌNH</span><h2>Từ nét vẽ, đến không gian.</h2><p>Mở hồ sơ thật, đối chiếu trục và chọn đúng tầng trước khi kiểm tra xung đột.</p></div><span className="coord-badge"><Layers3 size={16} /> DXF × IFC</span></div>
    {!!duplicates && <div className="coord-notice"><AlertTriangle size={18} /><p><strong>{duplicates} GUID có mặt ở nhiều tệp IFC.</strong> Cần xác định phạm vi bộ môn và đối tượng cha/con trước khi kiểm tra va chạm. Trùng GUID giữa các tệp chưa được coi là hai cấu kiện độc lập.</p></div>}
    <div className="coord-panes">
      <article className="coord-pane">
        <label className="coord-source">Bản vẽ DWG / DXF<select aria-label="Bản vẽ CAD phối hợp" value={drawing?.id ?? ""} disabled={busy} onChange={event => { setDrawingId(event.target.value); setStoreyId(""); }}>
          {!drawings.length && <option value="">Thêm DWG hoặc DXF trong ô hồ sơ phía trên</option>}{drawings.map(report => <option key={report.id} value={report.id}>{report.name}</option>)}
        </select></label>
        {drawing && active ? <Suspense fallback={<p className="coord-placeholder">Đang mở bản vẽ…</p>}><CadViewer report={drawing} connection={connection} marker={focus?.point_m && markerLink ? { point: focus.point_m, link: markerLink } : undefined} /></Suspense> : <div className="coord-placeholder"><Layers3 size={32} /><p>Nhập DWG hoặc DXF để mở bản vẽ và layer tại đây.</p></div>}
        {focus && <p className="coord-level-note">{!focus.point_m ? "Cặp tham chiếu của ca dữ liệu chưa có giao điểm đã xác lập để đánh dấu trên DXF." : markerLink ? "Chiếu XY điểm kiểm tra lên mặt bằng của tầng đã liên kết." : "Chưa định vị trên bản vẽ: cần liên kết DXF đã xác nhận, đúng nguồn IFC và tầng của cặp cấu kiện."}</p>}
      </article>
      <article className="coord-pane" ref={viewerPane}>
        <div className="coord-source">Mô hình 3D IFC <span className="coord-local-tag">{models.length > 0 && models.every(model => !!model.dataset) ? "Bộ mẫu tổng hợp để kiểm chứng kỹ thuật" : "Hình học từ hồ sơ của bạn"}</span></div>
        {viewerModels.length > 0 && active && !pauseViewer ? <Suspense fallback={<p className="coord-placeholder">Đang mở trình xem 3D…</p>}><IfcViewer reports={viewerModels} connection={connection} hiddenIds={hiddenModels} focus={focus} onClearFocus={setFocus} /></Suspense> : <div className="coord-placeholder"><Layers3 size={32} /><p>{pauseViewer ? "Đang dành RAM cho bộ xử lý. Mô hình 3D sẽ mở lại khi tác vụ kết thúc." : "Nhập IFC để xoay, chọn và đối chiếu cấu kiện."}</p></div>}
        {models.length > viewerModels.length && <p className="coord-notice">{models.length - viewerModels.length} IFC chưa có bản xem 3D trong giới hạn bộ nhớ. Vẫn có thể chọn để kiểm tra hình học và xuất báo cáo; mô hình chưa hiển thị sẽ không cô lập được cấu kiện trên 3D.</p>}
        {models.length > 0 && <div className="coord-model-list">{models.map(model => <label key={model.id}><input type="checkbox" aria-label={`Hiển thị ${model.name}`} checked={!hiddenModels.has(model.id)} onChange={() => { setFocus(null); setHiddenModels(current => { const next = new Set(current); if (next.has(model.id)) next.delete(model.id); else next.add(model.id); return next; }); }} /><span title={model.name}>{model.name}</span><small>{model.discipline}</small></label>)}</div>}
      </article>
    </div>
    <div className="coord-link-panel">
      <div className="coord-link-heading"><Link2 size={21} /><div><h3>Liên kết mặt bằng với tầng IFC</h3><p>So nhiều trục XY trong sai số 1 mm. Liên kết này xác nhận trục và tầng đã chọn; chưa kiểm chứng mọi cấu kiện.</p></div></div>
      <div className="coord-form">
        <label>Tên dự án<input aria-label="Tên dự án phối hợp" value={project} maxLength={120} disabled={busy || !canEdit} onChange={event => setProject(event.target.value)} placeholder="Ví dụ: Nha02" /></label>
        <label>IFC tham chiếu<select aria-label="IFC tham chiếu căn khớp" value={reference?.id ?? ""} disabled={busy || !canEdit} onChange={event => { setModelId(event.target.value); setStoreyId(""); }}>{!models.length && <option value="">Chưa có IFC</option>}{models.map(model => <option key={model.id} value={model.id}>{model.name}</option>)}</select></label>
        <label>Tầng IFC<select aria-label="Tầng IFC liên kết" value={storey?.guid ?? ""} disabled={busy || !canEdit} onChange={event => setStoreyId(event.target.value)}><option value="">Chọn tầng đúng với bản vẽ</option>{storeys.map(item => <option key={item.guid} value={item.guid}>{item.name} · {item.elevation_m.toFixed(3)} m</option>)}</select></label>
        <label>Dịch X (m)<input aria-label="Dịch X (m)" type="number" step="0.001" value={x} disabled={busy || !canEdit} onChange={event => setX(event.target.value)} /></label>
        <label>Dịch Y (m)<input aria-label="Dịch Y (m)" type="number" step="0.001" value={y} disabled={busy || !canEdit} onChange={event => setY(event.target.value)} /></label>
        <label>Góc xoay (°)<input aria-label="Góc xoay (°)" type="number" step="0.1" min={-360} max={360} value={rotation} disabled={busy || !canEdit} onChange={event => setRotation(event.target.value)} /></label>
        <button className="button coord-compare" disabled={!canCompare || busy || !canEdit} onClick={() => void compare(false)}><MoveUpRight size={17} />{busy ? "Đang đối chiếu…" : "So trục XY"}</button>
      </div>
      <p className="coord-level-note">DXF mặt bằng 2D thường có Z = 0. Cao độ liên kết lấy từ tầng IFC bạn chọn. Bản vẽ và mô hình hiển thị theo tọa độ nguồn; phép dịch/xoay trên đây được dùng để so trục và lưu liên kết.</p>
      {error && <p className="coord-error" role="alert">{error}</p>}
      {link && <div className={`coord-link-result ${link.grid_xy_ready ? "ready" : "review"}`} role="status">
        {link.grid_xy_ready ? <CheckCircle2 size={19} /> : <AlertTriangle size={19} />}<div><strong>{link.confirmed ? "Đã lưu liên kết tầng" : link.grid_xy_ready ? `Khớp ${link.matched_axes}/${link.total_axes} trục XY` : "Chưa đủ cơ sở xác nhận căn khớp"}</strong><p>{link.matched_axes}/{link.total_axes} trục · Cao độ {link.elevation_m.toFixed(3)} m{link.max_distance_m !== null ? ` · Lệch lớn nhất ${(link.max_distance_m * 1000).toFixed(3)} mm` : ""}</p></div>
        {link.confirmed && <button className="button" onClick={() => void downloadLink()}><Download size={16} />Tải liên kết JSON</button>}
      </div>}
      <label className="coord-confirm"><input type="checkbox" checked={sourcesConfirmed} disabled={busy || !canEdit} onChange={event => setSourcesConfirmed(event.target.checked)} aria-label="Tôi xác nhận bản vẽ và mô hình cùng công trình và đúng tầng" /><span>Tôi xác nhận bản vẽ và mô hình cùng công trình và đúng tầng.</span></label>
      <button className="button button-primary" disabled={!link?.grid_xy_ready || link.confirmed || !sourcesConfirmed || busy || !canEdit} onClick={() => void compare(true)}><Link2 size={17} />Xác nhận và lưu liên kết</button>
    </div>
    <Suspense fallback={<p className="coord-placeholder">Đang mở kiểm tra va chạm…</p>}><ClashWorkspace models={models} documents={reports.filter(report => report.kind === "pdf")} connection={connection} link={link?.confirmed ? link : null} uploadsBusy={uploadsBusy} onFocus={focusIssue} onBusyChange={onClashBusyChange} initialReport={initialReport} onRunSaved={onRunSaved} canEdit={canEdit} canReview={canReview} /></Suspense>
  </section>;
}

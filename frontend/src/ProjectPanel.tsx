import { useEffect, useRef, useState } from "react";
import { FolderKanban, History, Plus, RefreshCw, Trash2 } from "lucide-react";
import { processorFetch, type ClashReport, type Connection, type Inspection, type ProjectInfo, type RunSummary, type WorkspaceContext } from "./inspection-api";
import "./Project.css";
import StoragePanel from "./StoragePanel";
import ProjectSharing from "./ProjectSharing";
import { accountStorageKey } from "./account-api";
import Dialog from "./Dialog";

function preferenceKey(sharedOnly = false) { return accountStorageKey(sharedOnly ? "workspace.shared.v1" : "workspace.v1"); }
function remembered(sharedOnly = false): { project_id: string; run_id?: string } | null {
  try { const data = JSON.parse(localStorage.getItem(preferenceKey(sharedOnly)) || "null"); return data && /^[a-f0-9-]{36}$/.test(data.project_id) ? {project_id:data.project_id, run_id:data.run_id} : null; } catch { return null; }
}
function date(value?: string) { return value ? new Date(value).toLocaleString("vi-VN") : "Chưa có thời gian"; }

export default function ProjectPanel({ connection, locked, refreshKey, savedRun, onChange, onInspect, onBusyChange, onBlockedChange, sharedOnly = false, initialProject }: {
  connection: Connection | null; locked: boolean; refreshKey: number; savedRun: ClashReport | null;
  onChange: (context: WorkspaceContext) => void; onInspect: (report: Inspection) => void;
  onBusyChange: (busy: boolean) => void; onBlockedChange: (blocked: boolean) => void;
  sharedOnly?: boolean;
  initialProject?: ProjectInfo;
}) {
  const preference = useRef(initialProject ? {project_id: initialProject.id, run_id: undefined as string | undefined} : remembered(sharedOnly));
  const [open, setOpen] = useState(true);
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [projectTotal, setProjectTotal] = useState(0), [projectOffset, setProjectOffset] = useState(0);
  const [selected, setSelected] = useState<ProjectInfo | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false), [notice, setNotice] = useState("");
  const [name, setName] = useState("");
  const [files, setFiles] = useState<Inspection[]>([]), [fileTotal, setFileTotal] = useState(0);
  const [reports, setReports] = useState<Inspection[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]), [runTotal, setRunTotal] = useState(0);
  const [busy, setBusy] = useState(false), [listBusy, setListBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null), listRequest = useRef<AbortController | null>(null);
  const booted = useRef(false), loadedList = useRef(false), previousRefresh = useRef(refreshKey);
  const current = useRef<WorkspaceContext>({ project: null, reports: [], restoredRun: null });
  const onChangeRef = useRef(onChange); onChangeRef.current = onChange;
  function remember(context: WorkspaceContext, runId?: string) {
    preference.current = context.project ? {project_id:context.project.id, run_id:runId ?? context.restoredRun?.id} : null;
    try { if (preference.current) localStorage.setItem(preferenceKey(sharedOnly), JSON.stringify(preference.current)); else localStorage.removeItem(preferenceKey(sharedOnly)); } catch {}
  }
  function publish(context: WorkspaceContext) { current.current = context; setReports(context.reports); onChangeRef.current(context); remember(context); onBlockedChange(false); }
  async function list(append = false) {
    if (!connection) return;
    const abort = new AbortController(); listRequest.current?.abort(); listRequest.current = abort; setListBusy(true); setError("");
    try {
      const response = await processorFetch(connection, `/api/projects?limit=20&offset=${append ? projectOffset : 0}&scope=${sharedOnly ? "shared" : "all"}`, { signal: abort.signal });
      const data: { items: ProjectInfo[]; total: number; offset: number; storage?: { database: string; host: string } } = await response.json();
      if (abort.signal.aborted) return;
      setProjects(previous => [...new Map([...(append ? previous : []), ...data.items, ...(current.current.project ? [current.current.project] : [])].map(item => [item.id, item])).values()]);
      setProjectTotal(data.total); setProjectOffset(data.offset + data.items.length); loadedList.current = true;
      if (!append && !current.current.project && !request.current) {
        const saved = preference.current && data.items.find(item => item.id === preference.current?.project_id);
        // A complete list can identify preferences pointing at projects removed during cleanup.
        if (preference.current && (saved || data.total > data.items.length)) {
          void load(preference.current.project_id, preference.current.run_id);
        } else {
          if (preference.current) remember({project:null, reports:[], restoredRun:null});
          const project = data.items.find(item => item.permissions?.edit) ?? data.items[0];
          if (project) void load(project.id);
        }
      }
    } catch (error) { if (!abort.signal.aborted) setError(error instanceof Error ? error.message : "Chưa tải được dự án."); }
    finally { if (!abort.signal.aborted) setListBusy(false); }
  }
  async function load(identifier: string, runId?: string) {
    request.current?.abort();
    if (!identifier) return;
    if (!connection) return;
    const abort = new AbortController(); request.current = abort; setBusy(true); onBusyChange(true); setError("");
    const base = `/api/projects/${encodeURIComponent(identifier)}`;
    try {
      const project: ProjectInfo = await processorFetch(connection, base, { signal: abort.signal }).then(response => response.json());
      if (abort.signal.aborted) return;
      if (project.deleting) {
        setSelected(project);
        setFiles([]); setFileTotal(0); setRuns([]); setRunTotal(0);
        publish({project, reports:[], restoredRun:null});
        return;
      }
      let restored: { report: ClashReport; inspections: Inspection[] } | null = null;
      if (runId) { restored = await processorFetch(connection, `${base}/runs/${encodeURIComponent(runId)}`, { signal: abort.signal }).then(response => response.json()); }
      const [sources, history] = await Promise.all([
        processorFetch(connection, `${base}/inspections?limit=20`, { signal: abort.signal }).then(response => response.json() as Promise<{ items: Inspection[]; total: number }>),
        processorFetch(connection, `${base}/runs?limit=20`, { signal: abort.signal }).then(response => response.json() as Promise<{ items: RunSummary[]; total: number }>),
      ]);
      if (abort.signal.aborted) return;
      setSelected(project);
      setProjects(previous => [...new Map([...previous, project].map(item => [item.id, item])).values()]);
      setFiles(sources.items); setFileTotal(sources.total); setRuns(history.items); setRunTotal(history.total);
      publish({ project, reports: restored?.inspections ?? sources.items.slice(0, connection.processing_limits.open_files), restoredRun: restored?.report ?? null });
    } catch (error) { if (!abort.signal.aborted) {
      const unavailable = error instanceof Error && "status" in error && [403, 404].includes(Number(error.status));
      if (unavailable) {
        setSelected(null); setFiles([]); setRuns([]); setProjects(previous => previous.filter(item => item.id !== identifier));
        publish({ project: null, reports: [], restoredRun: null });
      }
      setError(error instanceof Error ? error.message : "Chưa mở được dự án."); onBlockedChange(!unavailable);
    } }
    finally { if (!abort.signal.aborted) { request.current = null; setBusy(false); onBusyChange(false); } }
  }
  async function create() {
    if (!connection || !name.trim() || busy) return;
    const abort = new AbortController(); request.current = abort; setBusy(true); onBusyChange(true); setError("");
    try {
      const project: ProjectInfo = await processorFetch(connection, "/api/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: name.trim() }), signal: abort.signal }).then(response => response.json());
      if (!abort.signal.aborted) { setName(""); await load(project.id); void list(); }
    } catch (error) { if (!abort.signal.aborted) { setError(error instanceof Error ? error.message : "Chưa tạo được dự án."); setBusy(false); onBusyChange(false); } }
  }
  async function removeProject() {
    if (!connection || !selected?.permissions?.delete || busy || locked) return;
    const target = selected;
    const abort = new AbortController(); request.current = abort;
    setBusy(true); onBusyChange(true); setError(""); setNotice("");
    try {
      await processorFetch(connection, `/api/projects/${target.id}`, {method:"DELETE", signal:abort.signal});
      if (abort.signal.aborted) return;
      setSelected(null); setFiles([]); setFileTotal(0); setRuns([]); setRunTotal(0);
      setProjects(previous => previous.filter(item => item.id !== target.id));
      publish({project:null, reports:[], restoredRun:null});
      setConfirmDelete(false); request.current = null;
      setNotice(`Đã xóa dự án ${target.name} và dữ liệu liên quan.`);
      void list();
    } catch (error) {
      if (!abort.signal.aborted) {
        setConfirmDelete(false);
        await load(target.id);
        setError(error instanceof Error ? error.message : "Xóa chưa hoàn tất. Hãy thử lại.");
      }
    } finally { if (!abort.signal.aborted) { request.current = null; setBusy(false); onBusyChange(false); } }
  }
  useEffect(() => {
    if (!connection || booted.current) return;
    booted.current = true;
    void list();
  }, [connection?.base_url, connection?.token]);
  useEffect(() => {
    if (previousRefresh.current === refreshKey) return;
    previousRefresh.current = refreshKey;
    if (current.current.project) void load(current.current.project.id);
  }, [refreshKey]);
  useEffect(() => {
    if (!connection || !savedRun?.project_id || savedRun.project_id !== current.current.project?.id) return;
    current.current = { ...current.current, restoredRun: savedRun };
    remember(current.current, savedRun.id);
    const abort = new AbortController();
    processorFetch(connection, `/api/projects/${savedRun.project_id}/runs?limit=20`, { signal: abort.signal }).then(response => response.json()).then(data => { if (!abort.signal.aborted && current.current.project?.id === savedRun.project_id) { setRuns(data.items); setRunTotal(data.total); } }).catch(error => { if (!abort.signal.aborted && current.current.project?.id === savedRun.project_id) setError(error.message); });
    return () => abort.abort();
  }, [savedRun?.id]);
  useEffect(() => () => { request.current?.abort(); listRequest.current?.abort(); onBusyChange(false); }, [onBusyChange]);
  function toggle(report: Inspection) {
    const exists = reports.some(item => item.id === report.id);
    const sameSource = (item: Inspection) => (item.logical_source || item.name) === (report.logical_source || report.name);
    if (!exists && !reports.some(sameSource) && reports.length >= (connection?.processing_limits.open_files ?? 0)) { setError(`Trình xem mở tối đa ${connection?.processing_limits.open_files ?? 0} tệp. Bỏ chọn một tệp trước khi mở thêm.`); return; }
    publish({ ...current.current, reports: exists ? reports.filter(item => item.id !== report.id) : [...reports.filter(item => !sameSource(item)), report], restoredRun: null });
  }
  async function more(kind: "files" | "runs") {
    if (!selected || !connection) return;
    const abort = new AbortController(); request.current = abort; setBusy(true); onBusyChange(true);
    try {
      const offset = kind === "files" ? files.length : runs.length;
      const url = kind === "files" ? `inspections?limit=20&offset=${offset}` : `runs?limit=20&offset=${offset}`;
      const data = await processorFetch(connection, `/api/projects/${selected.id}/${url}`, { signal: abort.signal }).then(response => response.json());
      if (!abort.signal.aborted) { if (kind === "files") setFiles(previous => [...previous, ...data.items]); else setRuns(previous => [...previous, ...data.items]); }
    } catch (error) { if (!abort.signal.aborted) setError(error instanceof Error ? error.message : "Chưa tải thêm được."); }
    finally { if (!abort.signal.aborted) { setBusy(false); onBusyChange(false); } }
  }
  return <details className="project-panel" open={open} onToggle={event => { setOpen(event.currentTarget.open); if (event.currentTarget.open && !loadedList.current) void list(); }}>
    <summary><FolderKanban size={20} /><span>Dự án và lịch sử</span><small>{selected ? selected.name : "Chọn dự án để bắt đầu"}</small></summary>
    <section aria-label="Quản lý dự án và lịch sử" aria-busy={busy}>
      <p className="project-intro">Tệp và kết quả được lưu theo dự án. Bản cập nhật được quản lý tự động; lịch sử giữ đúng tệp của từng lượt. Mở lại dự án để tiếp tục công việc; đồng bộ lên R2 để có bản sao tệp trên cloud.</p>
      <div className="project-controls">
        <label>Dự án đang mở<select aria-label="Dự án đang mở" value={selected?.id || ""} disabled={busy || locked || !connection} onChange={event => void load(event.target.value)}><option value="" disabled>Chọn dự án…</option>{projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
        <button className="button" disabled={busy || locked || !connection} onClick={() => { void list(); if (selected) void load(selected.id, current.current.restoredRun?.id); }}><RefreshCw size={16} />Tải lại</button>
        {selected?.permissions?.delete && <button className="button project-delete" disabled={busy || locked} onClick={() => setConfirmDelete(true)}><Trash2 size={16} />Xóa dự án</button>}
      </div>
      {projectOffset < projectTotal && <button className="button" disabled={listBusy || busy || locked} onClick={() => void list(true)}>Thêm dự án ({projectOffset}/{projectTotal})</button>}
      <form className="project-create" onSubmit={event => { event.preventDefault(); void create(); }}><label>Dự án mới<input aria-label="Dự án mới" value={name} maxLength={120} disabled={busy || locked} placeholder="Ví dụ: Nha02" onChange={event => setName(event.target.value)} /></label><button className="button" disabled={!name.trim() || busy || locked || !connection}><Plus size={16} />Tạo dự án</button></form>
      <p className="project-current" role="status">{busy ? "Đang mở hồ sơ dự án…" : selected ? `Dự án: ${selected.name}` : "Chọn dự án đã có hoặc tạo dự án mới trước khi đưa hồ sơ vào."}</p>
      {notice && <p className="project-current" role="status">{notice}</p>}
      {selected?.deleting && <p className="coord-error" role="status">Dự án đang chờ xóa. {selected.permissions?.delete ? "Bấm Xóa dự án để tiếp tục; kiểm tra kết nối MongoDB/R2 nếu lần trước bị gián đoạn." : "Chủ dự án cần hoàn tất việc dọn dữ liệu."}</p>}
      {selected && !selected.deleting && <StoragePanel key={`storage:${selected.id}`} connection={connection} projectId={selected.id} locked={locked || busy || !selected.permissions?.edit} />}
      {selected && <p className="project-muted">Chủ dự án: {selected.owner_name || "Chưa có tên"} · Quyền của bạn: {selected.permissions?.edit ? "Chủ sở hữu" : selected.permissions?.review ? "Rà soát" : "Chỉ xem"}</p>}
      {selected?.permissions?.share && !selected.deleting && connection && <ProjectSharing key={`members:${selected.id}`} project={selected} connection={connection} locked={busy || locked} />}
      {error && <p className="coord-error" role="alert">{error} Chọn dự án khác hoặc bấm Tải lại để tiếp tục.</p>}
      {selected && !selected.deleting && <div className="project-history-grid">
        <div><h3>Hồ sơ hiện tại</h3><p className="project-muted">Đang mở {reports.length}/{fileTotal} tệp trong trình xem · tối đa {connection?.processing_limits.open_files ?? 0} tệp. Nhập bản cập nhật cùng nguồn để thay tệp hiện tại; lịch sử kiểm tra được giữ lại.</p><div className="project-file-list">{files.map(report => <div key={report.id}><input type="checkbox" aria-label={`Mở hồ sơ ${report.name}`} checked={reports.some(item => item.id === report.id)} disabled={busy || locked} onChange={() => toggle(report)} /><button className="project-file-detail" title={report.name} onClick={() => onInspect(report)}><strong>{report.name}</strong><small>{report.logical_source} · {report.discipline}</small></button></div>)}{!files.length && <p className="project-muted">Chưa có tệp trong dự án. Nhập hồ sơ ở ô bên dưới.</p>}</div>{files.length < fileTotal && <button className="button" disabled={busy || locked} onClick={() => void more("files")}>Thêm 20 hồ sơ</button>}</div>
        <div><h3><History size={17} />Lịch sử kiểm tra</h3><p className="project-muted">Mở lại đúng nguồn, tham số và liên kết của từng lượt. Một lần chạy mới vẫn cần xác nhận tọa độ.</p><div className="project-run-list">{runs.map(run => <button key={run.id} disabled={busy || locked} aria-label={`Mở lượt kiểm tra ${run.id}`} onClick={() => void load(selected.id, run.id)}><strong>{date(run.created_at)}</strong><span>{run.issue_count} cặp · {run.status === "completed" ? "Hoàn tất" : run.status === "partial" ? "Cần rà soát" : "Lỗi"}</span></button>)}{!runs.length && <p className="project-muted">Chạy kiểm tra IFC để lưu lượt đầu tiên.</p>}</div>{runs.length < runTotal && <button className="button" disabled={busy || locked} onClick={() => void more("runs")}>Thêm 20 lượt kiểm tra</button>}{current.current.restoredRun && <button className="button" disabled={busy || locked} onClick={() => void load(selected.id)}>Về hồ sơ hiện tại</button>}</div>
      </div>}
      {confirmDelete && selected && <Dialog title="Xóa dự án" onClose={() => { if (!busy) setConfirmDelete(false); }}><div className="project-delete-confirm"><p>Bạn sắp xóa dự án <strong>{selected.name}</strong>.</p><p>Toàn bộ tệp đã nhập, bản xem 3D, kết quả, nhận xét và dữ liệu dự án trên R2 sẽ được xóa. Thao tác này không thể hoàn tác. Tệp dùng chung được giữ cho dự án còn sử dụng.</p><div className="project-delete-actions"><button autoFocus className="button" disabled={busy} onClick={() => setConfirmDelete(false)}>Giữ dự án</button><button className="button project-delete" disabled={busy || locked} onClick={() => void removeProject()}><Trash2 size={16} />{busy ? "Đang xóa dữ liệu…" : "Xóa toàn bộ dự án"}</button></div></div></Dialog>}
    </section>
  </details>;
}

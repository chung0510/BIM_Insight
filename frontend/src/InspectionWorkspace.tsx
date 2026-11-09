import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Box,
  CheckCircle2,
  Download,
  FileText,
  FolderOpen,
  LoaderCircle,
  RefreshCw,
  ScanLine,
  ShieldCheck,
  Upload,
  X,
  XCircle,
} from "lucide-react";
import {
  authHeaders,
  connectProcessor,
  errorMessage,
  inspectFile,
  processorFetch,
  type Connection,
  type Inspection,
  type ClashReport,
  type WorkspaceContext,
  type ProjectInfo,
  type FileKind,
  type ProcessingProgress,
} from "./inspection-api";
import ProcessingMemory, {processingPhase} from "./ProcessingMemory";
import ProjectPanel from "./ProjectPanel";
import "./Inspection.css";
import "./Clash.css";
const CoordinationWorkspace = lazy(() => import("./CoordinationWorkspace"));

type FileState =
  | "pending"
  | "uploading"
  | "processing"
  | "completed"
  | "partial"
  | "failed"
  | "cancelled";
type Item = {
  id: string;
  file: File;
  state: FileState;
  progress: number;
  report?: Inspection;
  error?: string;
  logicalSource?: string;
  runtime?: ProcessingProgress;
};
const labels: Record<FileState, string> = {
  pending: "Chờ kiểm tra",
  uploading: "Đang nhập tệp",
  processing: "Đang kiểm tra",
  completed: "Đọc được",
  partial: "Cần xem lại",
  failed: "Không hoàn tất",
  cancelled: "Đã hủy",
};
const count = new Intl.NumberFormat("vi-VN");
function size(bytes: number) {
  if (bytes >= 1024**3) return `${(bytes / 1024**3).toFixed(1)} GiB`;
  return bytes < 1024 ** 2
    ? `${(bytes / 1024).toFixed(1)} KiB`
    : `${(bytes / 1024 ** 2).toFixed(1)} MiB`;
}
function StatusIcon({ state }: { state: FileState }) {
  if (state === "completed") return <CheckCircle2 size={15} />;
  if (state === "partial") return <AlertTriangle size={15} />;
  if (state === "failed" || state === "cancelled") return <XCircle size={15} />;
  if (state === "processing" || state === "uploading")
    return <LoaderCircle size={15} className="inspection-spin" />;
  return <span className="inspection-pending-dot" />;
}

export default function InspectionWorkspace({
  active,
  query,
  sharedOnly = false,
  initialProject,
}: {
  active: boolean;
  query: string;
  sharedOnly?: boolean;
  initialProject?: ProjectInfo;
}) {
  const [items, setItems] = useState<Item[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [connectionState, setConnectionState] = useState<
    "idle" | "connecting" | "ready" | "error"
  >("idle");
  const [connectionError, setConnectionError] = useState("");
  const [message, setMessage] = useState("");
  const [announcement, setAnnouncement] = useState("");
  const [busy, setBusy] = useState(false);
  const [clashBusy, setClashBusy] = useState(false);
  const [converter, setConverter] = useState<{ available: boolean; version?: string } | null>(null);
  const [projectBusy, setProjectBusy] = useState(false), [projectBlocked, setProjectBlocked] = useState(false);
  const [projectRefresh, setProjectRefresh] = useState(0), [savedRun, setSavedRun] = useState<ClashReport | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceContext>({ project: null, reports: [], restoredRun: null });
  const workspaceRef = useRef(workspace);
  const [historicReport, setHistoricReport] = useState<Inspection | null>(null);
  const canEdit = workspace.project?.permissions?.edit === true && !workspace.project.deleting;
  const canReview = workspace.project?.permissions?.review === true && !workspace.project.deleting;
  const locked = busy || clashBusy || projectBusy || projectBlocked || !canEdit || connectionState !== "ready";
  const changeWorkspace = useCallback((next: WorkspaceContext) => {
    const previous = workspaceRef.current;
    const changed = previous.project?.id !== next.project?.id || previous.project?.deleting !== next.project?.deleting;
    if (changed) {
      setItems([]);
      setSelectedId(null);
    }
    const changedRun = previous.restoredRun?.id !== next.restoredRun?.id;
    workspaceRef.current = next; setWorkspace(next);
    setHistoricReport(current => changed || changedRun ? next.reports[0] ?? null : current ? next.reports.find(report => report.id === current.id) ?? next.reports[0] ?? null : null);
  }, []);
  const [dragging, setDragging] = useState(false);
  const [pageIndex, setPageIndex] = useState(0);
  const connection = useRef<Connection | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const request = useRef<XMLHttpRequest | null>(null);
  const cancelled = useRef(false);
  const alive = useRef(true);

  async function connect() {
    setConnectionState("connecting");
    try {
      const next = await connectProcessor();
      if (alive.current) {
        connection.current = next;
        setConnectionState("ready");
        setConnectionError("");
        void processorFetch(next, "/api/inspections/dwg-converter").then(response => response.json()).then(data => { if (alive.current) setConverter(data); }).catch(() => { if (alive.current) setConverter(null); });
      }
      return next;
    } catch (error) {
      if (alive.current) {
        setConnectionState("error");
        setConnectionError(
          error instanceof Error
            ? error.message
            : "Chưa kết nối được bộ xử lý.",
        );
      }
      throw error;
    }
  }
  useEffect(() => {
    if (active && !connection.current) void connect().catch(() => {});
  }, [active]);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      cancelled.current = true;
      request.current?.abort();
    };
  }, []);

  function addFiles(files: File[]) {
    if (locked) return;
    const next = [...items];
    const problems: string[] = [];
    for (const file of files) {
      const kind = file.name.split(".").pop()?.toLowerCase();
      if (!kind || !["ifc", "pdf", "dxf", "dwg"].includes(kind)) {
        problems.push(
          `${file.name}: hỗ trợ IFC/PDF/DXF/DWG. Xuất RVT/RTE sang IFC trước khi kiểm tra.`,
        );
        continue;
      }
      const limit = connection.current!.file_limits[kind as FileKind];
      if (!file.size || file.size > limit) {
        problems.push(
          `${file.name}: tệp phải có dữ liệu và tối đa ${size(limit)}.`,
        );
        continue;
      }
      if (
        next.some(
          (item) =>
            item.file.name === file.name &&
            item.file.size === file.size &&
            item.file.lastModified === file.lastModified,
        )
      ) {
        problems.push(`${file.name}: đã có trong danh sách.`);
        continue;
      }
      if (next.length >= connection.current!.processing_limits.queue_files) {
        problems.push(
          `Hàng đợi nhận tối đa ${connection.current!.processing_limits.queue_files} tệp. Bỏ bớt tệp đã xử lý trước khi thêm.`,
        );
        break;
      }
      next.push({
        id: crypto.randomUUID(),
        file,
        logicalSource: file.name.slice(0, 120),
        state: "pending",
        progress: 0,
      });
    }
    setItems(next);
    if (!selectedId && next.length) setSelectedId(next[0].id);
    setMessage(problems.join(" "));
    setAnnouncement(`Danh sách hiện có ${next.length} tệp.`);
    if (input.current) input.current.value = "";
  }
  function update(id: string, values: Partial<Item>) {
    if (alive.current)
      setItems((current) =>
        current.map((item) => (item.id === id ? { ...item, ...values } : item)),
      );
  }
  async function run() {
    const pending = items.filter((item) =>
      ["pending", "failed", "cancelled"].includes(item.state),
    );
    if (!pending.length || locked || !workspace.project) return;
    setBusy(true);
    if (workspace.restoredRun) { const next = { ...workspace, restoredRun: null }; workspaceRef.current = next; setWorkspace(next); }
    setMessage("");
    cancelled.current = false;
    try {
      const processor = await connect();
      for (const item of pending) {
        if (cancelled.current || !alive.current) break;
        update(item.id, {
          state: "uploading",
          progress: 0,
          report: undefined,
          error: undefined,
          runtime: undefined,
        });
        setAnnouncement(`Đang kiểm tra ${item.file.name}.`);
        try {
          const report = await inspectFile(
            processor,
            item.file,
            (progress) =>
              update(item.id, {
                progress,
                state: progress === 100 ? "processing" : "uploading",
              }),
            (next) => {
              request.current = next;
            },
            { project_id: workspace.project.id, logical_source: item.logicalSource?.trim() || item.file.name.slice(0, 120) },
            value => update(item.id, {runtime: value, state: "processing"}),
          );
          update(item.id, { report, state: report.status, progress: 100 });
          setAnnouncement(`${item.file.name}: ${labels[report.status]}.`);
        } catch (error) {
          const aborted =
            error instanceof DOMException && error.name === "AbortError";
          update(item.id, {
            state: aborted ? "cancelled" : "failed",
            error: aborted
              ? "Đã hủy. Bạn có thể chạy lại tệp này."
              : error instanceof Error
                ? error.message
                : "Không hoàn tất được kiểm tra.",
          });
        }
      }
    } catch {
      setMessage("Chưa kết nối được bộ xử lý. Hãy kết nối lại để tiếp tục.");
    } finally {
      request.current = null;
      if (alive.current) setBusy(false);
      if (alive.current && workspace.project) setProjectRefresh(value => value + 1);
    }
  }
  async function downloadReport(report: Inspection, converted = false) {
    try {
      const processor = connection.current ?? (await connect());
      const response = await fetch(
        `${processor.base_url}${converted ? report.assets?.converted_dxf : `${report.report_url}?full=true`}`,
        { headers: authHeaders(processor) },
      );
      if (!response.ok)
        throw new Error("Không tải được báo cáo. Hãy kết nối lại rồi thử lại.");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = converted ? report.name.replace(/\.dwg$/i, ".dxf") : `${report.name}.inspection.json`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Không tải được báo cáo.",
      );
    }
  }
  const selected = historicReport ? undefined : items.find((item) => item.id === selectedId) ?? items[0];
  const report = historicReport ?? selected?.report;
  const selectedName = selected?.file.name ?? report?.name ?? "";
  const selectedState = selected?.state ?? report?.status ?? "pending";
  const result = report?.result;
  const pages = result?.pages ?? [];
  const pdfPage = pages[pageIndex] ?? pages[0];
  const finished = items.filter((item) =>
    ["completed", "partial", "failed"].includes(item.state),
  ).length;
  const visibleItems = items.filter((item) =>
    item.file.name
      .toLocaleLowerCase("vi")
      .includes(query.toLocaleLowerCase("vi")),
  );
  const canRun = items.some((item) =>
    ["pending", "failed", "cancelled"].includes(item.state),
  );
  const reports = useMemo(() => workspace.reports, [workspace.reports]);
  const running = items.find(item => item.state === "processing" || item.state === "uploading");

  return (
    <section
      className="inspection-workspace"
      hidden={!active}
      aria-label="Kiểm tra hồ sơ IFC, PDF và CAD"
    >
      <div className="inspection-statusline">
        <span className={`inspection-connection ${connectionState}`}>
          <span />
          {connectionState === "ready"
            ? "Sẵn sàng kiểm tra"
            : connectionState === "connecting"
              ? "Đang chuẩn bị bộ xử lý…"
              : connectionState === "error"
                ? "Chưa kết nối được"
                : "Bộ xử lý local"}
        </span>
        <span>
          <ShieldCheck size={14} /> Tệp được xử lý trên thiết bị của bạn
        </span>
      </div>
      {connectionError && (
        <div className="inspection-error" role="alert">
          <AlertTriangle size={18} />
          <span>{connectionError}</span>
          <button type="button" onClick={() => void connect().catch(() => {})}>
            <RefreshCw size={15} /> Kết nối lại
          </button>
        </div>
      )}
      <ProjectPanel connection={connection.current} locked={busy || clashBusy} refreshKey={projectRefresh} savedRun={savedRun} onChange={changeWorkspace} onInspect={setHistoricReport} onBusyChange={setProjectBusy} onBlockedChange={setProjectBlocked} sharedOnly={sharedOnly} initialProject={initialProject} />
      {!workspace.project && <p className="work-notice">Mở hoặc tạo dự án ở phía trên để bắt đầu. Mọi tệp và kết quả mới đều được lưu vào dự án.</p>}
      {workspace.project && !workspace.project.deleting && !canEdit && <p className="work-notice">{canReview ? "Bạn có quyền xem và rà soát hồ sơ. Tệp nguồn và các lượt chạy do chủ dự án quản lý." : "Bạn đang ở chế độ chỉ xem. Liên hệ chủ dự án nếu cần quyền rà soát."}</p>}
      <div className="inspection-layout">
        <div className="inspection-input-panel">
          <div className="inspection-panel-heading">
            <div>
              <span className="section-index">01 / ĐƯA HỒ SƠ VÀO</span>
              <h2>Mỗi tệp, một góc nhìn.</h2>
            </div>
            <span className="inspection-format-tag">DWG / DXF + IFC + PDF</span>
          </div>
          <div
            className={`inspection-dropzone ${dragging ? "dragging" : ""} ${locked ? "is-busy" : ""}`}
            onDragOver={(event) => {
              event.preventDefault();
              if (!locked) setDragging(true);
            }}
            onDragLeave={(event) => {
              if (
                !event.currentTarget.contains(
                  event.relatedTarget as Node | null,
                )
              )
                setDragging(false);
            }}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              addFiles(Array.from(event.dataTransfer.files));
            }}
          >
            <input
              ref={input}
              className="inspection-file-input"
              type="file"
              accept=".ifc,.pdf,.dxf,.dwg"
              multiple
              aria-label="Chọn tệp IFC, PDF, DXF hoặc DWG"
              disabled={locked}
              onChange={(event) =>
                addFiles(Array.from(event.target.files ?? []))
              }
            />
            <div className="inspection-upload-symbol">
              <Upload size={28} strokeWidth={1.5} />
              <span>+</span>
            </div>
            <h3>Kéo thả hồ sơ của bạn vào đây</h3>
            <p>Bản vẽ DWG/DXF, mô hình IFC và tài liệu PDF của cùng công trình.</p>
            <button
              type="button"
              className="button button-primary"
              disabled={locked}
              onClick={() => input.current?.click()}
            >
              <FolderOpen size={17} /> Chọn tệp từ máy
            </button>
            <small>{connection.current ? `IFC ≤ ${size(connection.current.file_limits.ifc)} · DWG/DXF ≤ ${size(connection.current.file_limits.dxf)} · PDF ≤ ${size(connection.current.file_limits.pdf)} · Tối đa ${connection.current.processing_limits.queue_files} tệp` : "Đang tải giới hạn nhập hồ sơ…"}</small>
            {connection.current && <small>Xử lý lần lượt · Tối đa {Math.ceil(connection.current.processing_limits.timeout_seconds / 60)} phút mỗi tệp · Có thể hủy khi đang chạy</small>}
          </div>
          <div className="inspection-converter" role="status"><strong>DWG → DXF</strong><p>{converter?.available ? `ODA File Converter ${converter.version ?? ""} đã sẵn sàng. DWG được chuyển trên máy, giữ nguyên nguồn và lưu DXF cùng dự án.` : converter ? "Chưa có ODA File Converter trên máy. Cài bộ chuyển rồi bấm Kết nối lại; IFC, DXF và PDF vẫn sử dụng được." : "Đang kiểm tra bộ chuyển DWG trên máy…"}</p>{!converter?.available && <><a href="https://www.opendesign.com/guestfiles/oda_file_converter" target="_blank" rel="noopener noreferrer">Tải ODA File Converter</a><button className="button" onClick={() => void connect().catch(() => {})} disabled={busy || clashBusy || connectionState === "connecting"}>Kết nối lại</button></>}</div>
          {message && (
            <div className="inspection-error" role="alert">
              <AlertTriangle size={18} />
              <span>{message}</span>
              <button
                aria-label="Đóng thông báo tệp"
                onClick={() => setMessage("")}
              >
                <X size={16} />
              </button>
            </div>
          )}
          <div className="inspection-queue-heading">
            <h3>
              Hàng đợi nhập hồ sơ{" "}
              <span>{items.length.toString().padStart(2, "0")}</span>
            </h3>
            <span>
              {items.length
                ? `Đã xử lý ${finished}/${items.length} tệp`
                : "Thêm tệp để bắt đầu"}
            </span>
          </div>
          <div className="inspection-queue" aria-busy={busy} role="region" aria-label="Danh sách tệp trong hàng đợi" tabIndex={0}>
            {!items.length && (
              <div className="inspection-empty-queue">
                <FileText size={20} />
                <p>
                  Kiến trúc, kết cấu, cơ điện.
                  <br />
                  <span>Gom các góc nhìn vào cùng một phiên kiểm tra.</span>
                </p>
              </div>
            )}
            {items.length > 0 && !visibleItems.length && (
              <p className="inspection-empty-queue">
                Không có tệp khớp với tìm kiếm.
              </p>
            )}
            {visibleItems.map((item) => (
              <article
                className={`inspection-file ${selected?.id === item.id ? "selected" : ""} ${workspace.project ? "project-associated" : ""}`}
                key={item.id}
              >
                <div
                  className={`inspection-file-icon ${item.file.name.toLowerCase().endsWith(".pdf") ? "pdf" : "ifc"}`}
                >
                  {item.file.name.toLowerCase().endsWith(".pdf") ? (
                    <FileText size={22} />
                  ) : (
                    <Box size={22} />
                  )}
                  <small>
                    {item.file.name.split(".").pop()?.toUpperCase()}
                  </small>
                </div>
                <div className="inspection-file-copy">
                  <button
                    className="inspection-file-name"
                    title={item.file.name}
                    aria-label={`Xem kết quả ${item.file.name}`}
                    onClick={() => {
                      setHistoricReport(null);
                      setSelectedId(item.id);
                      setPageIndex(0);
                    }}
                  >
                    {item.file.name}
                  </button>
                  <div className={`inspection-file-status ${item.state}`}>
                    <StatusIcon state={item.state} />
                    <span>{labels[item.state]}</span>
                    <span className="inspection-size">
                      {size(item.file.size)}
                    </span>
                  </div>
                  {["uploading", "processing"].includes(item.state) && (
                    <progress
                      max={100}
                      value={
                        item.state === "processing" ? undefined : item.progress
                      }
                      aria-label={`Tiến trình ${item.file.name}`}
                    />
                  )}
                </div>
                {workspace.project && <label className="project-logical-source"><span>Nguồn logic</span><input aria-label={`Nguồn logic của ${item.file.name}`} maxLength={120} value={item.logicalSource ?? item.file.name.slice(0, 120)} disabled={locked || !!item.report} onChange={event => update(item.id, { logicalSource: event.target.value })} /></label>}
                <button
                  type="button"
                  className="inspection-remove"
                  disabled={locked}
                  aria-label={`Bỏ ${item.file.name}`}
                  onClick={() =>
                    setItems((current) =>
                      current.filter((other) => other.id !== item.id),
                    )
                  }
                >
                  <X size={17} />
                </button>
              </article>
            ))}
          </div>
          {busy && running?.runtime && <div className="clash-progress" data-testid="inspection-progress" role="status" aria-live="polite">
            <strong>{processingPhase(running.runtime.phase)}</strong>
            <span>{running.file.name}</span>
            {running.runtime.total !== undefined && running.runtime.total > 0 && <><progress aria-label="Tiến độ đọc IFC" value={running.runtime.done ?? 0} max={running.runtime.total} /><span>{running.runtime.done ?? 0}/{running.runtime.total} đối tượng</span></>}
            <ProcessingMemory stats={running.runtime} />
            <small>Đã chạy {Math.floor(running.runtime.elapsed_seconds ?? 0)} giây. Chưa có kết quả cho tới khi hoàn tất.</small>
          </div>}
          <div className="inspection-run-bar">
            <span>
              <ScanLine size={17} /> Từng tệp được kiểm tra lần lượt.
            </span>
            {busy ? (
              <button
                className="button inspection-cancel"
                onClick={() => {
                  cancelled.current = true;
                  request.current?.abort();
                }}
              >
                <X size={16} /> Hủy kiểm tra
              </button>
            ) : (
              <button
                className="button button-primary"
                disabled={!canRun || locked || connectionState !== "ready"}
                onClick={() => void run()}
              >
                {items.some((item) => item.state === "pending") || !items.length
                  ? "Bắt đầu kiểm tra"
                  : canRun
                    ? "Thử lại tệp lỗi"
                    : "Đã xử lý các tệp"}
                <ArrowRight size={17} />
              </button>
            )}
          </div>
        </div>
        <aside className="inspection-results" aria-label="Chi tiết kiểm tra">
          <div className="inspection-panel-heading">
            <div>
              <span className="section-index">02 / ĐỌC KẾT QUẢ</span>
              <h2>Hiểu hồ sơ trước khi phối hợp.</h2>
            </div>
            <ScanLine size={25} strokeWidth={1.5} />
          </div>
          {!selected && !report ? (
            <div className="inspection-empty-result">
              <div className="inspection-blueprint" aria-hidden="true">
                <svg viewBox="0 0 240 180" fill="none">
                  <path d="M35 55h170v105H35zM35 55l85-38 85 38M120 17v143M35 111h170M76 55v56m85 0v49M20 160h200M35 172h170M23 55v105" />
                  <path d="M50 70h45v28H50zm86 0h50v28h-50zM50 126h45v22H50zm125-4h15v28h-15z" />
                  <circle cx="120" cy="111" r="4" />
                </svg>
                <span>HỒ SƠ / CHỜ KIỂM TRA</span>
              </div>
              <h3>
                Một bước nhỏ,
                <br />
                <em>rõ hơn cả công trình.</em>
              </h3>
              <p>
                Chọn IFC để xem cấu kiện và hình học.
                <br />
                Chọn PDF để kiểm tra trang và nội dung chữ.
              </p>
              <div className="inspection-steps">
                <span>
                  <b>1</b> Chọn hồ sơ
                </span>
                <span>
                  <b>2</b> Chạy kiểm tra
                </span>
                <span>
                  <b>3</b> Xem và tải kết quả
                </span>
              </div>
            </div>
          ) : (
            <div className="inspection-detail-content">
              <div className="inspection-selected-name">
                <span>
                  {selectedName.toLowerCase().endsWith(".ifc")
                    ? "MÔ HÌNH IFC"
                    : selectedName.toLowerCase().endsWith(".pdf") ? "TÀI LIỆU PDF" : "BẢN VẼ CAD"}
                </span>
                <h3>{selectedName}</h3>
                <div className={`inspection-file-status ${selectedState}`}>
                  <StatusIcon state={selectedState} />
                  {labels[selectedState]}
                </div>
              </div>
              {selected?.error && (
                <p className="inspection-detail-error">{selected.error}</p>
              )}
              {report?.error_code && (
                <p className="inspection-detail-error">
                  {errorMessage(report.error_code)}
                </p>
              )}
              {report?.processing && <><ProcessingMemory stats={report.processing} finished />{report.error_code && report.processing.last_progress && <p className="inspection-metadata-note">Dừng ở bước: {processingPhase(report.processing.last_progress.phase)}.</p>}</>}
              {!report && !selected?.error && (
                <p className="inspection-waiting">
                  {busy && ["uploading", "processing"].includes(selectedState)
                    ? "Đang đọc hồ sơ. Kết quả sẽ xuất hiện tại đây."
                    : "Tệp đã ở trong hàng đợi. Bấm Bắt đầu kiểm tra để xem kết quả."}
                </p>
              )}
              {result && report?.kind === "ifc" && (
                <>
                  <div className="inspection-metrics">
                    <div>
                      <strong>{count.format(result.element_count ?? 0)}</strong>
                      <span>
                        {count.format(result.element_count ?? 0)} cấu kiện
                      </span>
                    </div>
                    <div>
                      <strong>
                        {count.format(result.excluded_count ?? 0)}
                      </strong>
                      <span>Chưa có hình học hợp lệ</span>
                    </div>
                    <div>
                      <strong>{result.ifc_schema}</strong>
                      <span>Phiên bản mô hình</span>
                    </div>
                    <div>
                      <strong>
                        {count.format(result.triangle_count ?? 0)}
                      </strong>
                      <span>Tam giác hình học</span>
                    </div>
                  </div>
                  <div className="inspection-type-list">
                    {Object.entries(result.type_counts ?? {}).map(
                      ([type, total]) => (
                        <span key={type}>
                          {type}
                          <b>{count.format(total)}</b>
                        </span>
                      ),
                    )}
                  </div>
                  <p className="inspection-metadata-note">
                    Tọa độ hình học được quy đổi về mét. Hệ số từ đơn vị nguồn:{" "}
                    {result.project_unit_scale_to_m}.
                    {!!result.aggregate_count && <> Có {result.aggregate_count} đối tượng cha dùng hình học từ thành phần con.</>}
                    {!!result.subtraction_count && <> Tệp có {count.format(result.subtraction_count)} lỗ mở/phần khoét, được thống kê riêng với cấu kiện vật lý.</>}
                    {!!result.reference_count && <> Có {count.format(result.reference_count)} đối tượng đường/điểm tham chiếu, được thống kê riêng và không tính là cấu kiện thiếu hình học.</>}
                    {result.geometry_settings?.scope === "import_preview_only" && <> Bản xem 3D đã được tối ưu; kiểm tra va chạm dựng lại hình học từ IFC gốc.</>}
                  </p>
                  {!result.geometry_policy && <p className="inspection-metadata-note">Báo cáo này dùng bộ đọc IFC cũ. Nhập lại cùng tệp để cập nhật phân loại hình học; lịch sử kiểm tra cũ được giữ nguyên.</p>}
                  {!!result.reference_elements?.length && <details className="inspection-elements">
                    <summary>Đối tượng tham chiếu · {count.format(result.reference_count ?? 0)}{result.reference_elements_truncated ? " (20 mẫu đầu)" : ""}</summary>
                    {result.reference_elements.map(item => <div key={item.guid}><strong>{item.name || item.ifc_type}</strong><code>{item.guid}</code><small>Chỉ có đường/điểm, không có bề mặt hoặc khối để kiểm tra va chạm.</small></div>)}
                  </details>}
                  {result.viewer_optimization && report.assets?.model && <p className="inspection-metadata-note">
                    Bản xem 3D: {size(result.viewer_optimization.after_bytes)}.
                    {result.viewer_optimization.after_bytes < result.viewer_optimization.before_bytes && <> Đã gộp dữ liệu hình học trùng lặp từ {size(result.viewer_optimization.before_bytes)}, giữ nguyên cấu kiện và vật liệu.</>}
                  </p>}
                  {!!result.elements?.length && (
                    <details className="inspection-elements">
                      <summary>
                        Mã và tọa độ cấu kiện{" "}
                        {result.elements_truncated ? "(20 mẫu đầu)" : ""}
                      </summary>
                      {result.elements.map((element) => (
                        <div key={element.guid}>
                          <strong>{element.name || element.ifc_type}</strong>
                          <code>{element.guid}</code>
                          <small>
                            Min:{" "}
                            {element.bounds_m.min
                              .map((n) => n.toFixed(3))
                              .join(" · ")}{" "}
                            m<br />
                            Max:{" "}
                            {element.bounds_m.max
                              .map((n) => n.toFixed(3))
                              .join(" · ")}{" "}
                            m
                          </small>
                        </div>
                      ))}
                    </details>
                  )}
                </>
              )}
              {result && (report?.kind === "dxf" || report?.kind === "dwg" && result.conversion) && <>
                {result.conversion && <p className="inspection-metadata-note">Đã chuyển DWG bằng {result.conversion.converter} {result.conversion.version} · {result.conversion.output_format}. Tệp DWG gốc được giữ nguyên.</p>}
                <div className="inspection-metrics">
                  <div><strong>{count.format(result.modelspace_count ?? 0)}</strong><span>Thực thể model space</span></div>
                  <div><strong>{result.layers?.length ?? 0}</strong><span>Layer bản vẽ</span></div>
                  <div><strong>{result.unit_name}</strong><span>Đơn vị nguồn</span></div>
                  <div><strong>{result.dxf_version}</strong><span>Phiên bản DXF</span></div>
                </div>
                <p className="inspection-metadata-note">Bản vẽ và layer được mở trong khu vực phối hợp bên dưới. DXF 2D cần chọn đúng tầng IFC; Z = 0 không tự xác định cao độ tầng.</p>
                <div className="inspection-type-list">{Object.entries(result.entity_types ?? {}).map(([type, total]) => <span key={type}>{type}<b>{count.format(total)}</b></span>)}</div>
                <details className="inspection-elements"><summary>Layout và phạm vi đọc</summary>{result.layouts?.map(layout => <p key={layout.name}>{layout.name}: {layout.entity_count} thực thể</p>)}<p>Preview hiển thị Model space. Xref và đối tượng chưa hỗ trợ được báo riêng.</p></details>
              </>}
              {result && report?.kind === "pdf" && (
                <>
                  <div className="inspection-metrics">
                    <div>
                      <strong>{result.page_count}</strong>
                      <span>Trang bản vẽ</span>
                    </div>
                    <div>
                      <strong>{result.processed_pages}</strong>
                      <span>Trang đã kiểm tra</span>
                    </div>
                  </div>
                  <p className="inspection-metadata-note">
                    {result.text_status === "detected"
                      ? "Đã trích xuất được chữ trong phạm vi các trang đã kiểm tra."
                      : "Chưa trích xuất được chữ từ các trang đã kiểm tra."}
                  </p>
                  {pdfPage && (
                    <div className="inspection-pdf-preview">
                      <label htmlFor="inspection-pdf-page">
                        Trang PDF
                        <select
                          id="inspection-pdf-page"
                          value={pageIndex < pages.length ? pageIndex : 0}
                          onChange={(event) =>
                            setPageIndex(Number(event.target.value))
                          }
                        >
                          {pages.map((page, index) => (
                            <option key={page.page} value={index}>
                              Trang {page.page}
                            </option>
                          ))}
                        </select>
                      </label>
                      <div className="inspection-page-size">
                        {pdfPage.width_mm} × {pdfPage.height_mm} mm · Xoay{" "}
                        {pdfPage.rotation}°
                      </div>
                      <pre>
                        {pdfPage.text_preview ||
                          "Trang này chưa có chữ có thể trích xuất."}
                      </pre>
                      <small>
                        Mẫu văn bản tối đa 2.000 ký tự mỗi trang; chưa nhận dạng
                        chữ trong ảnh.
                      </small>
                    </div>
                  )}
                </>
              )}
              {!!result?.diagnostics.length && (
                <div className="inspection-diagnostics">
                  <h4>
                    <AlertTriangle size={16} /> Nội dung cần xem lại
                  </h4>
                  {result.diagnostics.map((diagnostic, index) => {
                    const failure = result.geometry_failures?.find(item => item.guid === diagnostic.guid);
                    return (
                    <p key={`${diagnostic.code}-${index}`}>
                      {errorMessage(diagnostic.code)}
                      {diagnostic.page ? ` Trang ${diagnostic.page}.` : ""}
                      {diagnostic.guid && <code>{diagnostic.guid}</code>}
                      {failure && <small>{failure.name || failure.ifc_type}{" · "}{failure.detail}</small>}
                    </p>
                    );
                  })}
                  {result.diagnostics_truncated && (
                    <p>Danh sách hiển thị tối đa 100 mục.</p>
                  )}
                </div>
              )}
              {report && (
                <div className="inspection-report-footer">
                  <span>
                    {report.elapsed_seconds.toFixed(1)} giây ·{" "}
                    {size(report.size_bytes)}
                  </span>
                  <button
                    className="button inspection-download"
                    onClick={() => void downloadReport(report)}
                  >
                    <Download size={16} /> Tải báo cáo JSON
                  </button>
                  {report.assets?.converted_dxf && <button className="button inspection-download" onClick={() => void downloadReport(report, true)}><Download size={16} />Tải DXF đã chuyển</button>}
                  <details>
                    <summary>Dấu kiểm tệp SHA-256</summary>
                    <code>{report.sha256}</code>
                  </details>
                </div>
              )}
            </div>
          )}
        </aside>
      </div>
      {!!reports.length && connection.current && <Suspense fallback={<p className="inspection-waiting">Đang mở khu vực phối hợp…</p>}>
        <p className="inspection-metadata-note">Chỉ kiểm tra các cấu kiện có trong IFC đã nhập. Hệ thống không tự suy ra tuyến ống còn thiếu.</p>
        <CoordinationWorkspace key={`${workspace.project?.id}:${workspace.restoredRun?.id ?? "new"}`} reports={reports} connection={connection.current} active={active} uploadsBusy={busy || projectBusy || projectBlocked} pauseViewer={busy || clashBusy || projectBusy} onClashBusyChange={setClashBusy} initialReport={workspace.restoredRun} projectName={workspace.project?.name} onRunSaved={setSavedRun} canEdit={canEdit} canReview={canReview} />
      </Suspense>}
      <div className="inspection-scope">
        <ScanLine size={19} />
        <p>
          <strong>Kiểm tra theo hình học đã nhập.</strong> Đọc DWG/DXF, IFC và PDF ở trên, căn khớp bản vẽ và chạy va chạm 3D ở dưới. Kết quả ghi rõ phần đã kiểm tra và phần còn thiếu hình học.
        </p>
      </div>
      <div
        className="sr-only"
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        {announcement}
      </div>
    </section>
  );
}

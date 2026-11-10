import { lazy, Suspense, useEffect, useState } from "react";
import { ArrowDownToLine, ArrowRight, Bell, Box, ChevronRight, Files, FolderKanban, LayoutDashboard, LogOut, Menu, NotebookPen, Ruler, ScanLine, Search, ShieldCheck, UsersRound, UserRound } from "lucide-react";
import "./App.css";
import "./Library.css";
import "./Workbench.css";
import AccountGate from "./AccountGate";
import RoleWorkspace from "./RoleWorkspace";
import {rolePageDescriptions,roleIntroductions,roleNavigation,roleScreenModels,type RoleView} from "./role-navigation";
import AccountProfile from "./AccountProfile";
import { accountRequest, accountStorageKey, roleDescriptions, roleLabels, type Account, type AccountSession } from "./account-api";
import { type Connection, type ProjectInfo } from "./inspection-api";
import { DrawingLibrary, DrawingViewer, type Drawing } from "./Drawings";
import { models, screenModels, type ModelVariant } from "./models";
import ResidencePreview from "./ResidencePreview";
import InspectionWorkspace from "./InspectionWorkspace";
import Dialog from "./Dialog";

const HouseModel = lazy(() => import("./HouseModel"));
type View = "overview" | "inspection" | "shared" | "drawings" | "models" | "notes" | "accounts" | "account" | RoleView;
const commonNavigation = [
  { id: "overview" as const, label: "Tổng quan", icon: LayoutDashboard },
  { id: "inspection" as const, label: "Kiểm tra hồ sơ", icon: ScanLine },
  { id: "drawings" as const, label: "Thư viện bản vẽ", icon: Ruler },
  { id: "models" as const, label: "Mô hình minh họa", icon: Box },
  { id: "notes" as const, label: "Sổ tay dự án", icon: NotebookPen },
];
const homeTitles = { admin: "Tổng quan hệ thống", teacher: "Không gian giảng dạy BIM", student: "Không gian thực hành BIM", user: "Không gian dự án BIM" };
type Summary = { owned_projects: number; shared_projects: number; accounts?: Record<string, number> };

function Workbench({ user, connection, onSession, onAccount }: { user: Account; connection: Connection; onSession: (session: AccountSession | null) => void; onAccount:(account:Account)=>void }) {
  const navigation = user.role === "user" ? commonNavigation : roleNavigation[user.role];
  const personalNavigation = user.role === "user" ? [] : [...commonNavigation.filter(item => item.id !== "overview" && !navigation.some(target => target.id === item.id)), ...(user.role === "teacher" ? [{id:"shared" as const,label:"Hồ sơ được chia sẻ",icon:UsersRound}] : []), ...(["teacher","student"].includes(user.role)?[{id:"assignments" as const,label:"Bài thực hành chưa gán lớp",icon:Files}]:[])];
  function validView(value: string): View { if(value === "students" && user.role === "teacher")return "classes"; return (value === "notifications" && ["teacher","student"].includes(user.role)) || value === "account" || [...navigation,...personalNavigation].some(item => item.id === value) ? value as View : "overview"; }
  const [view, setView] = useState<View>(() => validView(location.hash.slice(1)));
  const [menuOpen, setMenuOpen] = useState(false), [query, setQuery] = useState("");
  const [personalOpen,setPersonalOpen] = useState(false);
  const [summary, setSummary] = useState<Summary | null>(null), [recent, setRecent] = useState<ProjectInfo[]>([]);
  const [error, setError] = useState(""), [reload, setReload] = useState(0), [leaving, setLeaving] = useState(false);
  const [drawing, setDrawing] = useState<Drawing | null>(null), [model, setModel] = useState<ModelVariant | null>(null);
  const [note, setNote] = useState(() => { try { return localStorage.getItem(accountStorageKey("notes.v1")) ?? ""; } catch { return ""; } });
  const [noteMessage, setNoteMessage] = useState("");
  const [projectRequest, setProjectRequest] = useState<{project?: ProjectInfo; sequence: number} | null>(null);
  useEffect(() => {
    if (view !== "inspection") setProjectRequest(previous => previous?.project ? {sequence: previous.sequence} : previous);
  }, [view]);
  function navigate(next: View) { location.hash = next; setView(next); setMenuOpen(false); setQuery(""); requestAnimationFrame(() => document.getElementById("workspace-main")?.focus({ preventScroll: true })); }
  useEffect(() => {
    const change = () => { setView(validView(location.hash.slice(1))); setMenuOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setMenuOpen(false); };
    window.addEventListener("hashchange", change); window.addEventListener("keydown", escape);
    return () => { window.removeEventListener("hashchange", change); window.removeEventListener("keydown", escape); };
  }, [user.role]);
  useEffect(() => {
    if (view !== "overview" || user.role !== "user") return;
    const abort = new AbortController(); setError("");
    Promise.all([accountRequest<Summary>(connection, "/api/auth/summary", undefined, abort.signal), accountRequest<{ items: ProjectInfo[] }>(connection, "/api/projects?limit=4", undefined, abort.signal)]).then(([nextSummary, projects]) => { if (!abort.signal.aborted) { setSummary(nextSummary); setRecent(projects.items); } }).catch(reason => { if (!abort.signal.aborted) setError(reason.message); });
    return () => abort.abort();
  }, [connection, view, reload]);
  async function logout() {
    if (leaving) return;
    setLeaving(true);
    try { await accountRequest(connection, "/api/auth/logout", {}); }
    catch { /* Clear the local session even if the processor is unavailable. */ }
    finally { onSession(null); }
  }
  function openProject(project: ProjectInfo) {
    setProjectRequest(previous => ({project, sequence: (previous?.sequence ?? 0) + 1}));
    try { localStorage.setItem(accountStorageKey("workspace.v1"), JSON.stringify({ project_id: project.id })); } catch { /* Preferences do not grant access. */ }
    navigate("inspection");
  }
  function saveNote() {
    try { localStorage.setItem(accountStorageKey("notes.v1"), note); setNoteMessage("Đã lưu sổ tay cho tài khoản này trên máy."); }
    catch { setNoteMessage("Chưa lưu được sổ tay trên máy."); }
  }
  function exportNote() {
    const url = URL.createObjectURL(new Blob([note], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url; link.download = `bim-note-${user.id}.txt`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const surfaceModel = view === "overview" ? screenModels[user.role] : roleScreenModels[view] ?? screenModels[view as keyof typeof screenModels];
  const currentTitle = view === "overview" ? homeTitles[user.role] : view === "account" ? "Tài khoản của tôi" : view === "notifications" ? "Thông báo" : [...navigation,...personalNavigation].find(item => item.id === view)?.label ?? "BIM Insight";
  return <div className={user.role === "user" ? "work-shell" : `work-shell work-role work-role-${user.role}`}>
    <a className="work-skip" href="#workspace-main" onClick={event => { event.preventDefault(); document.getElementById("workspace-main")?.focus(); }}>Đi đến nội dung chính</a>
    {menuOpen && <button className="work-scrim" aria-label="Đóng menu" onClick={() => setMenuOpen(false)} />}
    <aside className={`work-sidebar ${menuOpen ? "open" : ""}`}><a href="#overview" className="work-brand" onClick={() => navigate("overview")} aria-label="BIM Insight — Tổng quan"><span>BI</span><div>BIM INSIGHT<small>HIỂU MÔ HÌNH. RÕ HỒ SƠ.</small></div></a>
      <div className="work-current-role"><span className={`work-role-badge ${user.role}`}>{roleLabels[user.role]}</span><small>Không gian của {user.display_name}</small></div>
      <nav aria-label="Điều hướng chính">{navigation.map(({ id, label, icon: Icon }) => <button key={id} className={`work-nav ${view === id ? "active" : ""}`} aria-current={view === id ? "page" : undefined} onClick={() => navigate(id)}><Icon size={19} aria-hidden="true" /><span>{label}</span>{view === id && <ChevronRight size={15} aria-hidden="true" />}</button>)}</nav>
      {user.role !== "user" && <details className="work-personal-nav" open={personalOpen || personalNavigation.some(item=>item.id===view)} onToggle={event=>setPersonalOpen(event.currentTarget.open)}><summary><FolderKanban size={16}/>Không gian cá nhân</summary>{personalNavigation.map(({id,label,icon:Icon})=><button key={id} className={`work-nav ${view===id?"active":""}`} aria-current={view===id?"page":undefined} onClick={()=>navigate(id)}><Icon size={17} aria-hidden="true"/><span>{label}</span></button>)}</details>}
      {user.role === "user" ? <div className="work-sidebar-note"><FolderKanban size={24} aria-hidden="true" /><strong>Mỗi hồ sơ,<br />một bước rõ hơn.</strong><p>Đúng nguồn. Đúng tọa độ.<br />Rà soát có bằng chứng.</p></div> : <div className="work-sidebar-note"><FolderKanban size={24} aria-hidden="true"/><strong>{user.role === "admin" ? "Quản trị rõ ràng." : user.role === "teacher" ? "Đánh giá có căn cứ." : "Thực hành, cải thiện."}</strong><p>{user.role === "admin" ? "Đúng danh tính. Đúng quyền." : "Từ minh chứng đến phản hồi."}</p></div>}
      <button className={`work-nav work-profile-link ${view === "account" ? "active" : ""}`} onClick={() => navigate("account")}><UserRound size={19} aria-hidden="true" />Tài khoản của tôi</button>
      <small className="work-sidebar-footer">BIM Insight · Workspace 0.12</small>
    </aside>
    <div className="work-main-area"><header className="work-topbar"><button className="icon-button work-menu-toggle" aria-label="Mở menu" aria-expanded={menuOpen} onClick={() => setMenuOpen(value => !value)}><Menu size={22} /></button><div className="work-breadcrumb">BIM Insight <ChevronRight size={14} aria-hidden="true" /><span>{view === "overview" ? "Tổng quan" : currentTitle}</span></div><div className="work-topbar-user">{["teacher","student"].includes(user.role)&&<button className="button role-notification-button" onClick={()=>navigate("notifications")}><Bell size={16} aria-hidden="true"/>Thông báo</button>}<span>{user.display_name}<small>{roleLabels[user.role]}</small></span><button className="button" onClick={() => void logout().catch(() => {})} disabled={leaving}><LogOut size={16} aria-hidden="true" />{leaving ? "Đang thoát…" : "Đăng xuất"}</button></div></header>
      <main id="workspace-main" tabIndex={-1} className="work-content">{connection.deployment === "web_demo" && <aside className="work-notice" aria-label="Giới hạn bản thử nghiệm"><span><strong>Bản thử nghiệm miễn phí.</strong> Tệp tải lên có thể mất khi dịch vụ khởi động lại. Chỉ dùng tệp mẫu, tối đa 20 MB; IFC lớn có thể vượt bộ nhớ. DWG, AI và email khôi phục chưa khả dụng trên bản này.</span></aside>}<div className="work-page-heading"><div><span className="work-eyebrow">WORKSPACE / {roleLabels[user.role].toUpperCase()}</span><h1>{currentTitle}</h1><p>{view === "overview" ? user.role === "user" ? roleDescriptions[user.role] : roleIntroductions[user.role] : user.role !== "user" && rolePageDescriptions[view] ? rolePageDescriptions[view] : view === "shared" ? "Hồ sơ được chia sẻ với bạn; khả năng rà soát phụ thuộc quyền trong từng dự án." : view === "inspection" ? "Nhập hồ sơ, đối chiếu mô hình và lưu bằng chứng trong dự án của bạn." : view === "accounts" ? "Quản lý vai trò và trạng thái tài khoản." : view === "models" || view === "drawings" ? "Mẫu minh họa để tham khảo thao tác; hồ sơ thật được mở trong Kiểm tra hồ sơ." : "Không gian cá nhân theo tài khoản đang đăng nhập."}</p></div>{(view === "inspection" || view === "drawings") && <label className="work-search"><Search size={18} aria-hidden="true" /><input aria-label="Tìm trong hồ sơ đang xem" placeholder="Tìm hồ sơ, bản vẽ…" value={query} onChange={event => setQuery(event.target.value)} /></label>}{(view !== "overview" || user.role !== "user") && <div className="work-page-residence"><ResidencePreview variant={surfaceModel} paused={!!model || !!drawing}/></div>}</div>
      {view === "overview" && user.role === "user" && <><section className="work-hero"><div><span className="work-eyebrow">XIN CHÀO, {user.display_name.toUpperCase()}</span><h2>Từ bản vẽ,<br /><em>hiểu cả công trình.</em></h2><p>Đưa hồ sơ BIM vào, xem mô hình và kiểm tra những điểm cần phối hợp.</p><button className="button primary" onClick={() => navigate("inspection")}>Mở không gian dự án<ArrowRight size={18} aria-hidden="true" /></button></div><div className="work-hero-residence"><ResidencePreview variant={surfaceModel} paused={!!model || !!drawing}/></div></section>
        {error && <div className="account-error" role="alert">{error}<button className="button" onClick={() => setReload(value => value + 1)}>Thử lại</button></div>}
        <section className="work-metrics" aria-label="Thống kê tài khoản"><article><FolderKanban size={20} /><span>Dự án của bạn</span><strong>{summary?.owned_projects ?? "—"}</strong><small>Hồ sơ do tài khoản này sở hữu</small></article><article><UsersRound size={20} /><span>Hồ sơ được chia sẻ</span><strong>{summary?.shared_projects ?? "—"}</strong><small>Quyền xem hoặc rà soát riêng từng dự án</small></article><article><ShieldCheck size={20} /><span>Quyền đang sử dụng</span><strong className="work-text-metric">{roleLabels[user.role]}</strong><small>Chỉ truy cập hồ sơ được cấp quyền</small></article></section>
        <section className="work-panel"><div className="work-section-heading"><div><span className="work-eyebrow">HỒ SƠ CỦA BẠN</span><h2>Tiếp tục công việc.</h2></div><button className="button" onClick={() => navigate("inspection")}>Mở dự án<ArrowRight size={16} /></button></div>{recent.length ? <div className="work-project-cards">{recent.map(project => <button key={project.id} onClick={() => openProject(project)}><div><FolderKanban size={23} /><span className="work-access-tag">{project.permissions?.edit ? "Chủ sở hữu" : project.permissions?.review ? "Rà soát" : "Chỉ xem"}</span></div><h3>{project.name}</h3><p>{project.description || "Hồ sơ và lịch sử kiểm tra"}</p><span>Mở hồ sơ<ArrowRight size={16} /></span></button>)}</div> : <div className="work-empty"><Files size={33} /><h3>{summary ? "Bắt đầu từ một bộ hồ sơ." : "Đang tải dự án…"}</h3><p>Tạo dự án riêng hoặc mở hồ sơ đã được chủ dự án chia sẻ.</p><button className="button" onClick={() => navigate("inspection")}>Đến Kiểm tra hồ sơ</button></div>}</section>
        <div className="work-notice"><ShieldCheck size={19} /><p>Kết quả kiểm tra luôn ghi phạm vi dữ liệu. Đề xuất AI cần được người phụ trách rà soát trước khi thay đổi thiết kế.</p></div>
      </>}
      <InspectionWorkspace key={view === "shared" ? "shared" : `inspection:${projectRequest?.sequence ?? 0}`} active={view === "inspection" || view === "shared"} query={query} sharedOnly={view === "shared"} initialProject={view === "shared" ? undefined : projectRequest?.project} />
      {user.role !== "user" && ["overview","accounts","provision","services","audit","assignments","submissions","grades","students","classes","notifications"].includes(view) && <RoleWorkspace key={view} user={user} connection={connection} view={view} onNavigate={next=>navigate(validView(next))} />}
      {view === "account" && <AccountProfile user={user} connection={connection} onSession={onSession} onAccount={onAccount} />}
      {view === "drawings" && <DrawingLibrary query={query} onOpen={setDrawing} onOpenModel={setModel} />}
      {view === "models" && <section className="work-model-grid" aria-label="Mô hình 3D minh họa">{models.map(item => <button key={item.id} onClick={() => setModel(item.id)}><img src={item.image} alt={item.name} loading="lazy" decoding="async"/><span>{item.discipline}</span><h2>{item.name}</h2><p>{item.description}</p><strong>Mở mô hình tương tác<ArrowRight size={17} /></strong></button>)}</section>}
      {view === "notes" && <section className="work-panel work-notebook" aria-label="Sổ tay cá nhân"><span className="work-eyebrow">GHI CHÚ TRÊN MÁY NÀY</span><h2>Ghi lại điều cần kiểm tra.</h2><p>Sổ tay được tách theo tài khoản và hệ thống đang sử dụng.</p><label htmlFor="project-note">Nội dung ghi chú</label><textarea id="project-note" value={note} onChange={event => { setNote(event.target.value); setNoteMessage(""); }} maxLength={50000} placeholder="Nguồn hồ sơ, các điểm cần phối hợp và việc cần làm tiếp…" /><div><button className="button primary" onClick={saveNote}>Lưu sổ tay</button><button className="button" onClick={exportNote}><ArrowDownToLine size={17} />Xuất TXT</button></div>{noteMessage && <p role="status" className="work-success">{noteMessage}</p>}</section>}
      <footer className="work-footer">BIM Insight · Làm việc từ dữ liệu, phản hồi bằng chứng.</footer></main>
    </div>
    {drawing && <Dialog title={drawing.title} onClose={() => setDrawing(null)}><DrawingViewer drawing={drawing} onOpenModel={next => { setDrawing(null); setModel(next); }} /></Dialog>}
    {model && <Dialog title={models.find(item => item.id === model)?.name ?? "Mô hình 3D"} onClose={() => setModel(null)}><Suspense fallback={<p className="work-loading">Đang mở mô hình…</p>}><HouseModel variant={model} /></Suspense></Dialog>}
  </div>;
}

export default function App() { return <AccountGate>{(user, connection, onSession, onAccount) => <Workbench key={`${user.realm_id}:${user.id}:${user.role}`} user={user} connection={connection} onSession={onSession} onAccount={onAccount} />}</AccountGate>; }

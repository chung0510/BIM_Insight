import { useEffect, useState } from "react";
import { CheckCircle2, RefreshCw, ShieldCheck } from "lucide-react";
import { accountRequest, roleLabels, type Account, type AccountRole } from "./account-api";
import type { Connection } from "./inspection-api";
import AccountProvision from "./AccountProvision";
import GmailSettings from "./GmailSettings";
import "./AccountManagement.css";

export default function AdminAccounts({ connection, current }: { connection: Connection; current: Account }) {
  const [items, setItems] = useState<Account[]>([]), [total, setTotal] = useState(0), [offset, setOffset] = useState(0);
  const [choices, setChoices] = useState<Record<string, AccountRole>>({});
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState("");
  const [error, setError] = useState(""), [message, setMessage] = useState("");
  const [reload, setReload] = useState(0);
  const [tab,setTab]=useState<"list"|"provision"|"mail">("list");
  useEffect(() => {
    const abort = new AbortController(); setLoading(true); setError("");
    accountRequest<{ items: Account[]; total: number }>(connection, `/api/admin/users?limit=20&offset=${offset}`, undefined, abort.signal).then(result => {
      if (!abort.signal.aborted) { setItems(result.items); setTotal(result.total); setChoices({}); }
    }).catch(reason => { if (!abort.signal.aborted) setError(reason.message); }).finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [connection, offset, reload]);
  async function update(user: Account, kind: "role" | "status") {
    if (busy) return;
    setBusy(user.id); setError(""); setMessage("");
    try {
      const payload = kind === "role" ? { role: choices[user.id], expected_revision: user.revision } : { disabled: !user.disabled, expected_revision: user.revision };
      await accountRequest<Account>(connection, `/api/admin/users/${user.id}/${kind}`, payload);
      setMessage(kind === "role" ? "Đã cập nhật vai trò." : "Đã cập nhật trạng thái tài khoản.");
      setReload(value => value + 1);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Chưa cập nhật được tài khoản."); setReload(value => value + 1); }
    finally { setBusy(""); }
  }
  return <><nav className="admin-account-tabs" aria-label="Chức năng quản trị tài khoản"><button aria-pressed={tab==="list"} onClick={()=>setTab("list")}>Danh sách tài khoản</button><button aria-pressed={tab==="provision"} onClick={()=>setTab("provision")}>Cấp tài khoản</button><button aria-pressed={tab==="mail"} onClick={()=>setTab("mail")}>Email khôi phục</button></nav>
    {tab==="provision"&&<AccountProvision connection={connection} onCreated={()=>setReload(value=>value+1)}/>}{tab==="mail"&&<GmailSettings connection={connection}/>}
    {tab==="list"&&<section className="work-panel" aria-label="Quản lý tài khoản" aria-busy={loading}>
    <div className="work-section-heading"><div><span className="work-eyebrow">QUẢN TRỊ / TÀI KHOẢN</span><h2>Đúng người, đúng quyền.</h2><p>Tài khoản tự đăng ký là Người dùng. Chọn Cấp tài khoản để tạo giảng viên và sinh viên bằng mã hoặc Excel.</p></div><button className="button" disabled={loading || !!busy} onClick={() => setReload(value => value + 1)}><RefreshCw size={16} />Tải lại danh sách</button></div>
    <div className="work-notice"><ShieldCheck size={19} aria-hidden="true" /><p>Mọi vai trò đều có dự án cá nhân. Giảng viên chỉ rà soát dự án được chia sẻ; Admin không tự có quyền xem hồ sơ riêng của người khác.</p></div>
    {error && <p className="account-error" role="alert">{error}</p>}{message && <p className="work-success" role="status"><CheckCircle2 size={17} />{message}</p>}
    <div className="work-account-list">{items.map(user => <article className="work-account-row" key={user.id}>
      <div className="work-avatar" aria-hidden="true">{user.display_name.slice(0, 1).toUpperCase()}</div>
      <div className="work-account-name"><strong>{user.display_name}{user.id === current.id && <small> · Bạn</small>}</strong><span>@{user.username}</span>{user.login_email&&<span>{user.login_email}</span>}<small>{user.disabled ? "Đã khóa" : user.must_change_password?"Chờ đổi mật khẩu lần đầu":"Đang hoạt động"}</small></div>
      <label className="work-role-field">Vai trò<select aria-label={`Vai trò của ${user.username}`} value={choices[user.id] ?? user.role} disabled={loading || !!busy || user.id === current.id || user.disabled} onChange={event => { setChoices(previous => ({ ...previous, [user.id]: event.target.value as AccountRole })); setMessage(""); }}>{Object.entries(roleLabels).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label>
      <div className="work-account-actions"><button className="button" aria-label={`Lưu vai trò của ${user.username}`} disabled={loading || !!busy || !choices[user.id] || choices[user.id] === user.role || user.id === current.id || user.disabled} onClick={() => void update(user, "role")}>{busy === user.id ? "Đang lưu…" : "Lưu vai trò"}</button><button className="button work-text-button" aria-label={`${user.disabled ? "Mở khóa" : "Khóa"} ${user.username}`} disabled={loading || !!busy || user.protected || user.id === current.id} onClick={() => void update(user, "status")}>{user.disabled ? "Mở khóa" : "Khóa tài khoản"}</button>{user.protected && <small>Tài khoản quản trị được bảo vệ</small>}</div>
    </article>)}</div>
    {loading && !items.length && <p className="project-muted" role="status">Đang tải tài khoản…</p>}
    <div className="work-pagination"><button className="button" disabled={!offset || loading || !!busy} onClick={() => setOffset(value => Math.max(0, value - 20))}>Trang trước</button><span>{total ? `${offset + 1}–${Math.min(total, offset + 20)}` : "0"} / {total} tài khoản</span><button className="button" disabled={offset + 20 >= total || loading || !!busy} onClick={() => setOffset(value => value + 20)}>Trang sau</button></div>
  </section>}</>;
}

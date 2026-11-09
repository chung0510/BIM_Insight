import { useEffect, useRef, useState } from "react";
import { Share2, UserMinus } from "lucide-react";
import { accountRequest, roleLabels, type AccountRole } from "./account-api";
import type { Connection, ProjectInfo } from "./inspection-api";

type Member = { user_id: string; username: string; display_name: string; role: AccountRole; access: "view" | "review"; disabled: boolean };
export default function ProjectSharing({ project, connection, locked }: { project: ProjectInfo; connection: Connection; locked: boolean }) {
  const [members, setMembers] = useState<Member[]>([]), [username, setUsername] = useState("");
  const [access, setAccess] = useState<"view" | "review">("review");
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(true), [error, setError] = useState(""), [message, setMessage] = useState("");
  const request = useRef<AbortController | null>(null);
  const base = `/api/projects/${project.id}/members`;
  useEffect(() => {
    const abort = new AbortController(); request.current = abort;
    accountRequest<{ items: Member[] }>(connection, base, undefined, abort.signal).then(result => { if (!abort.signal.aborted) setMembers(result.items); }).catch(reason => { if (!abort.signal.aborted) setError(reason.message); }).finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => request.current?.abort();
  }, [connection, base]);
  async function change(member?: Member) {
    if (busy || locked || loading) return;
    const abort = new AbortController(); request.current = abort; setBusy(true); setError(""); setMessage("");
    try {
      const result = await accountRequest<{ items: Member[] }>(connection, member ? `${base}/${member.user_id}/remove` : base, member ? {} : { username: username.trim().toLowerCase(), access }, abort.signal);
      if (!abort.signal.aborted) { setMembers(result.items); setUsername(""); setMessage(member ? "Đã thu hồi quyền truy cập dự án." : "Đã chia sẻ dự án."); }
    } catch (reason) { if (!abort.signal.aborted) setError(reason instanceof Error ? reason.message : "Chưa thay đổi được quyền chia sẻ."); }
    finally { if (!abort.signal.aborted) setBusy(false); }
  }
  return <details className="project-sharing"><summary><Share2 size={17} />Chia sẻ và quyền truy cập <span>{members.length} tài khoản</span></summary><p className="project-muted">Nhập tên đăng nhập đã có. Người được chia sẻ không thể thay tệp nguồn hoặc cấp quyền cho người khác.</p><form className="project-sharing-form" onSubmit={event => { event.preventDefault(); void change(); }}><label>Tên đăng nhập nhận chia sẻ<input aria-label="Tên đăng nhập nhận chia sẻ" value={username} onChange={event => setUsername(event.target.value.toLowerCase())} minLength={3} maxLength={48} required disabled={busy || locked || loading} /></label><label>Quyền truy cập<select aria-label="Quyền truy cập chia sẻ" value={access} onChange={event => setAccess(event.target.value as "view" | "review")} disabled={busy || locked || loading}><option value="view">Chỉ xem hồ sơ</option><option value="review">Rà soát — Giảng viên / Admin</option></select></label><button className="button" disabled={busy || locked || loading || !username.trim()}>{busy ? "Đang lưu…" : "Chia sẻ dự án"}</button></form>
    {error && <p className="account-error" role="alert">{error}</p>}{message && <p className="work-success" role="status">{message}</p>}
    <div className="project-member-list">{members.map(member => <div key={member.user_id}><span><strong>{member.display_name}</strong><small>@{member.username} · {roleLabels[member.role]} · {member.access === "review" && ["teacher", "admin"].includes(member.role) ? "Rà soát" : "Chỉ xem"}{member.disabled ? " · Đã khóa" : ""}</small></span><button className="button" aria-label={`Thu hồi quyền của ${member.username}`} disabled={busy || locked || loading} onClick={() => void change(member)}><UserMinus size={16} />Thu hồi</button></div>)}</div>{!loading && !members.length && <p className="project-muted">Dự án hiện chỉ có bạn truy cập.</p>}
  </details>;
}

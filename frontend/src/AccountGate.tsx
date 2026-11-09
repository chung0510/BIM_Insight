import { useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowRight, Eye, EyeOff, LoaderCircle, LockKeyhole, ShieldCheck, UserRound } from "lucide-react";
import { connectProcessor, type Connection } from "./inspection-api";
import { accountRequest, getAccount, refreshAccount, rememberSession, type Account, type AccountSession } from "./account-api";
import ResidencePreview from "./ResidencePreview";
import {modelInfo,screenModels} from "./models";
import "./Account.css";
import {ForcedPassword,RecoveryForm} from "./PasswordFlows";

export default function AccountGate({ children }: { children: (account: Account, connection: Connection, onSession: (session: AccountSession | null) => void, onAccount:(account:Account)=>void) => ReactNode }) {
  const [connection, setConnection] = useState<Connection | null>(null);
  const [user, setUser] = useState<Account | null>(null);
  const [mode, setMode] = useState<"loading" | "login" | "register" | "setup" | "forgot">("loading");
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false), [visible, setVisible] = useState(false);
  const [formFocused,setFormFocused]=useState(false);
  const [username, setUsername] = useState(""), [name, setName] = useState(""), [password, setPassword] = useState(""), [confirmation, setConfirmation] = useState("");
  const [registrationEmail,setRegistrationEmail]=useState("");const temporaryPassword=useRef("");
  function accept(session: AccountSession | null) {
    rememberSession(session); setFormFocused(false); setUser(session?.user ?? null); setPassword(""); setConfirmation(""); setError("");
    if(!session?.user.must_change_password)temporaryPassword.current="";
    if (!session) { history.replaceState(null, "", `${location.pathname}${location.search}#overview`); setMode("login"); }
  }
  function updateAccount(account:Account) {
    const current=getAccount();
    if(!current||current.id!==account.id||current.realm_id!==account.realm_id||account.revision<current.revision)return;
    refreshAccount(account);setUser(previous=>previous&&previous.id===account.id&&previous.realm_id===account.realm_id?account:previous);
  }
  useEffect(() => {
    let alive = true;
    setMode("loading"); setError("");
    connectProcessor().then(async next => {
      const status = await accountRequest<{ setup_required: boolean }>(next, "/api/auth/state");
      if (alive) { setConnection(next); setMode(status.setup_required ? "setup" : "login"); }
    }).catch(reason => { if (alive) setError(reason instanceof Error ? reason.message : "Chưa kết nối được hệ thống tài khoản."); });
    return () => { alive = false; };
  }, [attempt]);
  useEffect(() => {
    function expire() { accept(null); setError("Phiên đăng nhập đã hết hạn hoặc bị thu hồi. Hãy đăng nhập lại."); }
    window.addEventListener("bim-account-expired", expire);
    return () => window.removeEventListener("bim-account-expired", expire);
  }, []);
  useEffect(() => {
    if (!user || !connection) return;
    let alive = true;
    const abort = new AbortController();
    async function check() {
      try {
        const account = await accountRequest<Account>(connection!, "/api/auth/me", undefined, abort.signal);
        if (alive) updateAccount(account);
      } catch { /* The request layer clears expired sessions; transient outages keep the current screen. */ }
    }
    const interval = window.setInterval(() => { void check(); }, 60000);
    window.addEventListener("focus", check);
    return () => { alive = false; abort.abort(); clearInterval(interval); window.removeEventListener("focus", check); };
  }, [user?.id, connection]);
  async function submit() {
    if (!connection || busy) return;
    if (mode !== "login" && password !== confirmation) { setError("Hai mật khẩu chưa khớp."); return; }
    setBusy(true); setError("");
    try {
      const session = await accountRequest<AccountSession>(connection, `/api/auth/${mode === "setup" ? "bootstrap" : mode === "register" ? "register" : "login"}`, { username: username.trim().toLowerCase(), password, ...(mode === "login" ? {} : { display_name: name.trim(),email:registrationEmail.trim() }) });
      if(session.user.must_change_password)temporaryPassword.current=password;
      accept(session);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Chưa hoàn tất đăng nhập.");
      if (mode === "setup") {
        try {
          const state = await accountRequest<{ setup_required: boolean }>(connection, "/api/auth/state");
          if (!state.setup_required) { setMode("login"); setError("Tài khoản quản trị đã được tạo. Đăng nhập bằng tài khoản vừa nhập để tiếp tục nhận hồ sơ cũ."); }
        } catch { /* A reconnect can recover setup after a database outage. */ }
      }
    }
    finally { setBusy(false); }
  }
  if (user && connection&&!user.must_change_password) return children(user, connection, accept, updateAccount);
  const forced=!!user?.must_change_password;
  const title = forced?"Đổi mật khẩu lần đầu":mode==="forgot"?"Khôi phục mật khẩu":mode === "setup" ? "Tạo tài khoản quản trị đầu tiên" : mode === "register" ? "Tạo không gian BIM của bạn" : "Chào mừng bạn trở lại";
  const variant=screenModels[forced||mode==="setup"?"setup":mode==="register"?"register":"login"],residence=modelInfo(variant);
  function switchMode(next:"login"|"register"|"forgot") {setMode(next);setError("");setPassword("");setConfirmation("");setRegistrationEmail("");setVisible(false);setFormFocused(false);}
  async function logoutForced(){try{if(connection)await accountRequest(connection,"/api/auth/logout",{});}finally{accept(null);}}
  return <main className="account-page" data-auth-mode={forced?"force":mode}>
    <section className="account-story" aria-label="BIM Insight">
      <div className="account-story-top"><div className="account-brand"><span className="account-brand-mark">BI</span><span>BIM<span>INSIGHT</span></span></div><span className="account-edition">ARCHITECTURE<br/>IN MOTION / 01</span></div>
      <div className="account-story-copy"><span className="account-eyebrow">KHÔNG GIAN CHO NHỮNG Ý TƯỞNG LỚN</span><h1>{mode==="register"?<>Bắt đầu từ<br/><em>một góc nhìn mới.</em></>:<>Hiểu mô hình.<br/><em>Nhìn rõ vấn đề.</em></>}</h1><p>Khám phá kiến trúc. Kết nối hồ sơ.<br/>Đưa những ý tưởng tốt đến gần thực tế hơn.</p></div>
      <div className="account-residence"><ResidencePreview variant={variant} paused={busy||formFocused}/></div>
      <div className="account-story-bottom"><div><span className="account-eyebrow">GÓC NHÌN KIẾN TRÚC</span><p>{residence.architect}</p></div><span className="account-orbit-hint">Kéo mô hình để khám phá<br/>Xoay · Thu phóng · Đổi góc nhìn</span></div>
    </section>
    <section className="account-form-panel" aria-label="Đăng nhập BIM Insight" onFocusCapture={()=>setFormFocused(true)} onBlurCapture={event=>{if(!event.currentTarget.contains(event.relatedTarget))setFormFocused(false);}}>
      <div className="account-form-wrap"><div className="account-mobile-brand">BI<span>BIM INSIGHT</span></div><span className="account-eyebrow">{mode==="setup"?"THIẾT LẬP KHÔNG GIAN CỦA BẠN":"CHÀO BẠN ĐẾN VỚI BIM INSIGHT"}</span>
        {!forced&&(mode==="login"||mode==="register")&&<div className="account-tabs" aria-label="Chọn đăng nhập hoặc đăng ký"><button type="button" aria-label="Chuyển sang đăng nhập" aria-pressed={mode==="login"} disabled={busy} onClick={()=>switchMode("login")}>Đăng nhập</button><button type="button" aria-label="Chuyển sang đăng ký" aria-pressed={mode==="register"} disabled={busy} onClick={()=>switchMode("register")}>Đăng ký</button></div>}
        <h2>{title}</h2><p className="account-description">{forced?`${user?.display_name}, hãy thay mật khẩu tạm được cấp trước khi sử dụng BIM Insight.`:mode==="forgot"?"Nhận mã xác nhận qua email đã gắn với tài khoản và chọn mật khẩu mới.":mode === "setup" ? "Bạn sẽ quản lý tài khoản và phân quyền. Hồ sơ đã có trên máy được giữ nguyên và nhận vào tài khoản này." : mode === "register" ? "Một tài khoản cho những dự án của riêng bạn. Nhập hồ sơ, khám phá mô hình và chia sẻ để nhận góp ý." : "Tiếp tục công việc, khám phá mô hình và phối hợp hồ sơ của bạn."}</p>
        {forced&&connection?<ForcedPassword connection={connection} initialPassword={temporaryPassword.current} onSession={accept} onLogout={()=>void logoutForced().catch(()=>{})}/>:mode==="forgot"&&connection?<RecoveryForm connection={connection} onBack={()=>switchMode("login")}/>:mode === "loading" ? <div className="account-connection" role="status">{error ? "Chưa kết nối được hệ thống tài khoản." : "Đang kết nối hệ thống tài khoản…"}</div> : <form key={mode} className="account-fields" onSubmit={event => { event.preventDefault(); void submit(); }}>
          {mode !== "login" && <label>Tên hiển thị<input aria-label="Tên hiển thị" value={name} onChange={event => setName(event.target.value)} minLength={2} maxLength={80} autoComplete="name" required disabled={busy} /></label>}
          <label>Tên đăng nhập<div className="account-input"><UserRound size={18} aria-hidden="true" /><input aria-label="Tên đăng nhập" value={username} onChange={event => setUsername(event.target.value.toLowerCase())} pattern={mode==="login"?undefined:"[a-z0-9][a-z0-9_.\\-]{2,47}"} minLength={3} maxLength={mode==="login"?254:48} autoComplete="username" autoCapitalize="none" spellCheck={false} required disabled={busy} /></div><small>{mode==="login"?"Mã giảng viên, mã sinh viên, tên đăng nhập hoặc email đã xác nhận.":"3–48 ký tự: chữ thường, số, dấu chấm, gạch dưới hoặc gạch ngang."}</small></label>
          {mode==="register"&&<label>Email đăng ký<input type="email" value={registrationEmail} onChange={event=>setRegistrationEmail(event.target.value)} maxLength={254} autoComplete="email" disabled={busy}/><small>Bạn xác nhận email trong Tài khoản của tôi để đăng nhập và khôi phục mật khẩu.</small></label>}
          <label>Mật khẩu<div className="account-input"><LockKeyhole size={18} aria-hidden="true" /><input aria-label="Mật khẩu" type={visible ? "text" : "password"} value={password} onChange={event => setPassword(event.target.value)} minLength={mode === "login" ? 1 : 12} maxLength={128} autoComplete={mode === "login" ? "current-password" : "new-password"} required disabled={busy} /><button type="button" className="icon-button" aria-label={visible ? "Ẩn mật khẩu" : "Hiện mật khẩu"} onClick={() => setVisible(value => !value)}>{visible ? <EyeOff size={18} /> : <Eye size={18} />}</button></div>{mode !== "login" && <small>Ít nhất 12 ký tự. Bạn có thể dùng trình quản lý mật khẩu.</small>}</label>
          {mode !== "login" && <label>Xác nhận mật khẩu<input aria-label="Xác nhận mật khẩu" type={visible ? "text" : "password"} value={confirmation} onChange={event => setConfirmation(event.target.value)} minLength={12} maxLength={128} autoComplete="new-password" required disabled={busy} /></label>}
          {error && <p className="account-error" role="alert">{error}</p>}
          <button className="button primary account-submit" disabled={busy}>{busy ? "Đang xử lý…" : mode === "setup" ? "Tạo tài khoản quản trị" : mode === "register" ? "Đăng ký tài khoản" : "Đăng nhập"}{busy?<LoaderCircle size={18} className="account-spinner" aria-hidden="true"/>:<ArrowRight size={18} aria-hidden="true" />}</button>
        </form>}
        {mode === "loading" && error && <><p className="account-error" role="alert">{error}</p><button className="button" onClick={() => setAttempt(value => value + 1)}>Kết nối lại</button></>}
        {!forced&&mode==="login"&&<div className="account-forgot"><button type="button" disabled={busy} onClick={()=>switchMode("forgot")}>Quên mật khẩu?</button></div>}
        {!forced&&(mode === "login" || mode === "register") && <div className="account-switch"><span>{mode === "login" ? "Bạn chưa có tài khoản?" : "Bạn đã có tài khoản?"}</span><button disabled={busy} onClick={()=>switchMode(mode==="login"?"register":"login")}>{mode === "login" ? "Tạo tài khoản" : "Về đăng nhập"}</button></div>}
        <div className="account-trust"><ShieldCheck size={16} aria-hidden="true"/><span>Không gian riêng. Quyền truy cập rõ ràng.</span></div><p className="account-footer">BIM INSIGHT <span>Hồ sơ tốt hơn. Phối hợp rõ hơn.</span></p>
      </div>
    </section>
  </main>;
}

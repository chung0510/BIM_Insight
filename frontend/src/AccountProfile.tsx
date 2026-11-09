import {useEffect,useRef,useState} from "react";
import {LockKeyhole,Save,UserRound} from "lucide-react";
import {accountRequest,roleDescriptions,roleLabels,type Account,type AccountSession,type PersonalProfile} from "./account-api";
import type {Connection} from "./inspection-api";
import "./Profile.css";
import AccountEmail from "./AccountEmail";

type Draft=Omit<PersonalProfile,"user">&{display_name:string};
const toDraft=({user,...fields}:PersonalProfile):Draft=>({...fields,display_name:user.display_name});
export default function AccountProfile({user,connection,onSession,onAccount}:{user:Account;connection:Connection;onSession:(session:AccountSession)=>void;onAccount:(account:Account)=>void}) {
  const [saved,setSaved]=useState<PersonalProfile|null>(null),[draft,setDraft]=useState<Draft>({display_name:user.display_name,email:"",phone:"",organization:"",job_title:"",bio:""});
  const [loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState(""),[message,setMessage]=useState(""),[reload,setReload]=useState(0);
  const [current,setCurrent]=useState(""),[password,setPassword]=useState(""),[confirmation,setConfirmation]=useState("");
  const [passwordError,setPasswordError]=useState(""),[passwordMessage,setPasswordMessage]=useState("");
  const request=useRef<AbortController|null>(null);
  useEffect(()=>{
    const abort=new AbortController();setLoading(true);setError("");setMessage("");
    accountRequest<PersonalProfile>(connection,"/api/auth/profile",undefined,abort.signal).then(profile=>{
      if(!abort.signal.aborted){setSaved(profile);setDraft(toDraft(profile));onAccount(profile.user);}
    }).catch(reason=>{if(!abort.signal.aborted)setError(reason instanceof Error?reason.message:"Chưa tải được hồ sơ.");})
      .finally(()=>{if(!abort.signal.aborted)setLoading(false);});
    return()=>abort.abort();
  },[connection,reload]);
  useEffect(()=>()=>request.current?.abort(),[]);
  async function saveProfile() {
    if(busy||loading||!saved)return;
    const abort=new AbortController();request.current=abort;setBusy(true);setError("");setMessage("");
    try {
      const profile=await accountRequest<PersonalProfile>(connection,"/api/auth/profile",{...draft,expected_revision:saved.user.revision},abort.signal);
      if(abort.signal.aborted)return;
      setSaved(profile);setDraft(toDraft(profile));onAccount(profile.user);setMessage("Đã lưu hồ sơ cá nhân.");
    }catch(reason){if(!abort.signal.aborted)setError(reason instanceof Error?reason.message:"Chưa lưu được hồ sơ.");}
    finally{if(!abort.signal.aborted)setBusy(false);}
  }
  async function savePassword() {
    if(busy||loading)return;
    setPasswordError("");setPasswordMessage("");
    if(password!==confirmation){setPasswordError("Hai mật khẩu mới chưa khớp.");return;}
    const abort=new AbortController();request.current=abort;setBusy(true);
    try {
      const session=await accountRequest<AccountSession>(connection,"/api/auth/password",{current_password:current,new_password:password},abort.signal);
      if(abort.signal.aborted)return;
      onSession(session);setCurrent("");setPassword("");setConfirmation("");setPasswordMessage("Đã đổi mật khẩu và thu hồi các phiên đăng nhập cũ.");
      // The password response has no contact fields; keep the profile revision to prevent stale overwrites.
    }catch(reason){if(!abort.signal.aborted)setPasswordError(reason instanceof Error?reason.message:"Chưa đổi được mật khẩu.");}
    finally{if(!abort.signal.aborted)setBusy(false);}
  }
  const initials=user.display_name.trim().split(/\s+/).slice(-2).map(word=>word[0]).join("").toUpperCase();
  const dirty=saved&&JSON.stringify(draft)!==JSON.stringify(toDraft(saved));
  const field=(name:keyof Draft,value:string)=>{setDraft(previous=>({...previous,[name]:value}));setMessage("");};
  return <section className="work-profile-grid" aria-label="Tài khoản của tôi">
    <article className="work-panel profile-identity"><span className="work-eyebrow">HỒ SƠ CÁ NHÂN</span><div className="profile-avatar" aria-hidden="true">{initials}</div><h2>{user.display_name}</h2><p className="project-muted">@{user.username}</p><span className={`work-role-badge ${user.role}`}>{roleLabels[user.role]}</span><p>{roleDescriptions[user.role]}</p><dl><div><dt>Tên đăng nhập</dt><dd>{user.username}</dd></div><div><dt>Vai trò</dt><dd>{roleLabels[user.role]}</dd></div></dl><p className="project-muted">Tên đăng nhập giữ nguyên. Quản trị viên quản lý vai trò tài khoản.</p></article>
    <div className="profile-editors"><article className="work-panel"><span className="work-eyebrow">THÔNG TIN CỦA BẠN</span><h2><UserRound size={22}/>Chỉnh sửa hồ sơ</h2><p className="project-muted">Tên hiển thị xuất hiện khi phối hợp và gửi nhận xét. Thông tin liên hệ chỉ hiển thị trong hồ sơ của bạn.</p>
      <form className="work-form profile-form" aria-label="Chỉnh sửa hồ sơ" onSubmit={event=>{event.preventDefault();void saveProfile();}}>
        <fieldset disabled={busy||loading||!saved}><div className="profile-fields">
          <label className="profile-wide">Tên hiển thị<input value={draft.display_name} onChange={event=>field("display_name",event.target.value)} required minLength={2} maxLength={80} autoComplete="name"/></label>
          <label>Email liên hệ<input aria-label="Email liên hệ" type="email" value={draft.email} onChange={event=>field("email",event.target.value)} maxLength={254} autoComplete="email"/><small>Email này không thay tên đăng nhập.</small></label>
          <label>Số điện thoại<input type="tel" value={draft.phone} onChange={event=>field("phone",event.target.value)} maxLength={25} autoComplete="tel"/></label>
          <label>Đơn vị<input value={draft.organization} onChange={event=>field("organization",event.target.value)} maxLength={120} autoComplete="organization"/></label>
          <label>Chức vụ<input value={draft.job_title} onChange={event=>field("job_title",event.target.value)} maxLength={80} autoComplete="organization-title"/></label>
          <label className="profile-wide">Giới thiệu<textarea aria-label="Giới thiệu" value={draft.bio} onChange={event=>field("bio",event.target.value)} maxLength={500} rows={4}/><small>{draft.bio.length}/500 ký tự</small></label>
        </div></fieldset>
        {loading&&<p role="status" className="project-muted">Đang tải hồ sơ…</p>}{error&&<p className="account-error" role="alert">{error}</p>}{message&&<p className="work-success" role="status">{message}</p>}
        <div className="profile-actions"><button className="button button-primary" disabled={busy||loading||!saved||!dirty}><Save size={16}/>{busy?"Đang lưu…":"Lưu hồ sơ"}</button><button type="button" className="button" disabled={busy||loading||!saved||!dirty} onClick={()=>{if(saved)setDraft(toDraft(saved));setError("");setMessage("");}}>Hủy thay đổi</button>{error&&<button type="button" className="button" disabled={busy||loading} onClick={()=>setReload(value=>value+1)}>Tải lại hồ sơ</button>}</div>
      </form></article>
      <AccountEmail user={user} connection={connection} onAccount={onAccount}/>
      <article className="work-panel"><h2><LockKeyhole size={22}/>Đổi mật khẩu</h2><p className="project-muted">Mật khẩu mới sẽ thu hồi tất cả phiên cũ.</p><form className="work-form" onSubmit={event=>{event.preventDefault();void savePassword();}}>
        <label>Mật khẩu hiện tại<input type="password" value={current} onChange={event=>setCurrent(event.target.value)} autoComplete="current-password" required disabled={busy||loading} maxLength={128}/></label><label>Mật khẩu mới<input type="password" value={password} onChange={event=>setPassword(event.target.value)} autoComplete="new-password" required minLength={12} maxLength={128} disabled={busy||loading}/></label><label>Xác nhận mật khẩu mới<input type="password" value={confirmation} onChange={event=>setConfirmation(event.target.value)} autoComplete="new-password" required minLength={12} maxLength={128} disabled={busy||loading}/></label>
        {passwordError&&<p className="account-error" role="alert">{passwordError}</p>}{passwordMessage&&<p className="work-success" role="status">{passwordMessage}</p>}<button className="button button-primary" disabled={busy||loading}>{busy?"Đang lưu…":"Đổi mật khẩu"}</button>
      </form></article></div>
  </section>;
}

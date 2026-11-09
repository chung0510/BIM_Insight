import {useEffect,useRef,useState} from "react";
import {ArrowLeft,LockKeyhole,Mail} from "lucide-react";
import {accountRequest,type AccountSession} from "./account-api";
import type {Connection} from "./inspection-api";

export function ForcedPassword({connection,initialPassword,onSession,onLogout}:{connection:Connection;initialPassword:string;onSession:(session:AccountSession)=>void;onLogout:()=>void}) {
  const [current,setCurrent]=useState(initialPassword),[password,setPassword]=useState(""),[confirmation,setConfirmation]=useState("");
  const [busy,setBusy]=useState(false),[error,setError]=useState("");const request=useRef<AbortController|null>(null);
  useEffect(()=>()=>request.current?.abort(),[]);
  async function save(){
    if(busy)return;setError("");
    if(password!==confirmation){setError("Hai mật khẩu mới chưa khớp.");return;}
    if(password===current){setError("Hãy chọn mật khẩu khác mật khẩu tạm.");return;}
    const abort=new AbortController();request.current=abort;setBusy(true);
    try{const session=await accountRequest<AccountSession>(connection,"/api/auth/password",{current_password:current,new_password:password},abort.signal);if(!abort.signal.aborted)onSession(session);}
    catch(reason){if(!abort.signal.aborted)setError(reason instanceof Error?reason.message:"Chưa đổi được mật khẩu.");}
    finally{if(!abort.signal.aborted)setBusy(false);}
  }
  return <form className="account-fields" aria-label="Đổi mật khẩu lần đầu" onSubmit={event=>{event.preventDefault();void save();}}>
    <label>Mật khẩu tạm<input type="password" value={current} onChange={event=>setCurrent(event.target.value)} required maxLength={128} autoComplete="current-password" disabled={busy}/></label>
    <label>Mật khẩu mới<input aria-label="Mật khẩu mới" type="password" value={password} onChange={event=>setPassword(event.target.value)} minLength={12} maxLength={128} required autoComplete="new-password" disabled={busy}/><small>Ít nhất 12 ký tự, khác mật khẩu tạm được cấp.</small></label>
    <label>Xác nhận mật khẩu mới<input type="password" value={confirmation} onChange={event=>setConfirmation(event.target.value)} minLength={12} maxLength={128} required autoComplete="new-password" disabled={busy}/></label>
    {error&&<p className="account-error" role="alert">{error}</p>}
    <button className="button account-submit" disabled={busy}><LockKeyhole size={18}/>{busy?"Đang đổi mật khẩu…":"Đổi mật khẩu và tiếp tục"}</button>
    <button type="button" className="button" onClick={onLogout}>Đăng xuất</button>
  </form>;
}

export function RecoveryForm({connection,onBack}:{connection:Connection;onBack:()=>void}) {
  const [identifier,setIdentifier]=useState(""),[challenge,setChallenge]=useState(""),[code,setCode]=useState(""),[password,setPassword]=useState(""),[confirmation,setConfirmation]=useState("");
  const [busy,setBusy]=useState(false),[error,setError]=useState(""),[message,setMessage]=useState(""),[complete,setComplete]=useState(false);
  const request=useRef<AbortController|null>(null);useEffect(()=>()=>request.current?.abort(),[]);
  async function send(){
    if(busy)return;const abort=new AbortController();request.current=abort;setBusy(true);setError("");setMessage("");
    try{const result=await accountRequest<{challenge_id:string;message:string}>(connection,"/api/auth/recovery/request",{identifier:identifier.trim()},abort.signal);if(!abort.signal.aborted){setChallenge(result.challenge_id);setCode("");setMessage(result.message);}}
    catch(reason){if(!abort.signal.aborted)setError(reason instanceof Error?reason.message:"Chưa gửi được yêu cầu.");}
    finally{if(!abort.signal.aborted)setBusy(false);}
  }
  async function reset(){
    if(busy)return;setError("");if(password!==confirmation){setError("Hai mật khẩu mới chưa khớp.");return;}
    const abort=new AbortController();request.current=abort;setBusy(true);
    try{await accountRequest(connection,"/api/auth/recovery/confirm",{challenge_id:challenge,code,new_password:password},abort.signal);if(!abort.signal.aborted){setComplete(true);setPassword("");setConfirmation("");setCode("");}}
    catch(reason){if(!abort.signal.aborted)setError(reason instanceof Error?reason.message:"Chưa đặt lại được mật khẩu.");}
    finally{if(!abort.signal.aborted)setBusy(false);}
  }
  if(complete)return <div className="account-fields"><p role="status" className="work-success">Đã đặt lại mật khẩu. Hãy đăng nhập bằng mật khẩu mới.</p><button className="button account-submit" onClick={onBack}>Về đăng nhập</button></div>;
  return <form className="account-fields" aria-label="Khôi phục mật khẩu" onSubmit={event=>{event.preventDefault();void(challenge?reset():send());}}>
    <label>Mã hoặc email<input aria-label="Mã hoặc email" value={identifier} onChange={event=>setIdentifier(event.target.value)} minLength={3} maxLength={254} autoComplete="username" required disabled={busy||!!challenge}/><small>Dùng mã giảng viên, mã sinh viên, tên đăng nhập hoặc email đã xác nhận.</small></label>
    {challenge&&<><label>Mã xác nhận<input value={code} onChange={event=>setCode(event.target.value.replace(/\D/g,""))} inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" minLength={6} maxLength={6} required disabled={busy}/></label><label>Mật khẩu mới<input type="password" value={password} onChange={event=>setPassword(event.target.value)} minLength={12} maxLength={128} required autoComplete="new-password" disabled={busy}/></label><label>Xác nhận mật khẩu mới<input type="password" value={confirmation} onChange={event=>setConfirmation(event.target.value)} minLength={12} maxLength={128} required autoComplete="new-password" disabled={busy}/></label></>}
    {message&&<p role="status" className="project-muted">{message} Kiểm tra cả thư mục Spam.</p>}{error&&<p role="alert" className="account-error">{error}</p>}
    <button className="button account-submit" disabled={busy}><Mail size={18}/>{busy?"Đang xử lý…":challenge?"Đặt lại mật khẩu":"Gửi mã khôi phục"}</button>
    {challenge&&<button type="button" className="button" disabled={busy} onClick={()=>void send()}>Gửi lại mã</button>}
    <button type="button" className="button" onClick={onBack}><ArrowLeft size={16}/>Về đăng nhập</button>
  </form>;
}

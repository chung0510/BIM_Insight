import {useEffect,useRef,useState} from "react";
import {MailCheck} from "lucide-react";
import {accountRequest,type Account} from "./account-api";
import type {Connection} from "./inspection-api";

export default function AccountEmail({user,connection,onAccount}:{user:Account;connection:Connection;onAccount:(account:Account)=>void}){
  const [email,setEmail]=useState(user.pending_email||user.login_email||""),[challenge,setChallenge]=useState(""),[code,setCode]=useState("");
  const [busy,setBusy]=useState(false),[error,setError]=useState(""),[message,setMessage]=useState("");const request=useRef<AbortController|null>(null);
  useEffect(()=>()=>request.current?.abort(),[]);
  async function submit(confirm:boolean){
    if(busy)return;const abort=new AbortController();request.current=abort;setBusy(true);setError("");setMessage("");
    try{
      if(confirm){const account=await accountRequest<Account>(connection,"/api/auth/email/confirm",{challenge_id:challenge,code},abort.signal);if(!abort.signal.aborted){onAccount(account);setChallenge("");setCode("");setMessage("Đã xác nhận email đăng nhập và khôi phục mật khẩu.");}}
      else{const result=await accountRequest<{challenge_id:string}>(connection,"/api/auth/email/request",{email},abort.signal);if(!abort.signal.aborted){setChallenge(result.challenge_id);setCode("");setMessage("Đã gửi yêu cầu xác nhận. Kiểm tra email và thư mục Spam; mã có hiệu lực 10 phút.");}}
    }catch(reason){if(!abort.signal.aborted)setError(reason instanceof Error?reason.message:"Chưa xác nhận được email.");}
    finally{if(!abort.signal.aborted)setBusy(false);}
  }
  return <article className="work-panel"><h2><MailCheck size={22}/>Email đăng nhập và khôi phục</h2><p className="project-muted">{user.login_email?<>Đã xác nhận: <strong>{user.login_email}</strong>. Bạn có thể đăng nhập bằng email này.</>:"Xác nhận email để đăng nhập và lấy lại mật khẩu. Email liên hệ trong hồ sơ được quản lý riêng."}</p>
    <form className="work-form" aria-label="Xác nhận email tài khoản" onSubmit={event=>{event.preventDefault();void submit(!!challenge);}}>
      <label>Email đăng nhập<input type="email" value={email} onChange={event=>setEmail(event.target.value)} required maxLength={254} autoComplete="email" disabled={busy||!!challenge}/></label>
      {challenge&&<label>Mã xác nhận email<input value={code} onChange={event=>setCode(event.target.value.replace(/\D/g,""))} inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" minLength={6} maxLength={6} required disabled={busy}/></label>}
      {error&&<p role="alert" className="account-error">{error}</p>}{message&&<p role="status" className="work-success">{message}</p>}
      <div className="profile-actions"><button className="button button-primary" disabled={busy||(!challenge&&email.trim().toLowerCase()===user.login_email)}>{busy?"Đang xử lý…":challenge?"Xác nhận email":"Gửi mã xác nhận email"}</button>{challenge&&<><button type="button" className="button" disabled={busy} onClick={()=>void submit(false)}>Gửi lại mã email</button><button type="button" className="button" disabled={busy} onClick={()=>{setChallenge("");setCode("");setMessage("");}}>Đổi địa chỉ email</button></>}</div>
    </form></article>;
}

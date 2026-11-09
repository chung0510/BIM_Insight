import {useEffect,useRef,useState} from "react";
import {Mail,ShieldCheck} from "lucide-react";
import {accountRequest} from "./account-api";
import type {Connection} from "./inspection-api";
import {isTauri} from "@tauri-apps/api/core";
import {openUrl} from "@tauri-apps/plugin-opener";

export default function GmailSettings({connection}:{connection:Connection}){
  const [email,setEmail]=useState(""),[password,setPassword]=useState(""),[configured,setConfigured]=useState(false),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState(""),[message,setMessage]=useState("");
  const request=useRef<AbortController|null>(null);
  useEffect(()=>{const abort=new AbortController();accountRequest<{configured:boolean;email:string}>(connection,"/api/admin/mail",undefined,abort.signal).then(status=>{if(!abort.signal.aborted){setConfigured(status.configured);setEmail(status.email);}}).catch(reason=>{if(!abort.signal.aborted)setError(reason.message);}).finally(()=>{if(!abort.signal.aborted)setLoading(false);});return()=>{abort.abort();request.current?.abort();};},[connection]);
  async function save(){
    if(busy)return;const abort=new AbortController();request.current=abort;setBusy(true);setError("");setMessage("");
    try{const status=await accountRequest<{configured:boolean;email:string}>(connection,"/api/admin/mail",{email,app_password:password},abort.signal);if(!abort.signal.aborted){setConfigured(status.configured);setEmail(status.email);setPassword("");setMessage("Đã lưu và kiểm tra kết nối Gmail thành công.");}}
    catch(reason){if(!abort.signal.aborted)setError(reason instanceof Error?reason.message:"Chưa lưu được cấu hình email.");}
    finally{if(!abort.signal.aborted)setBusy(false);}
  }
  return <section className="work-panel admin-mail" aria-label="Cấu hình Gmail khôi phục"><span className="work-eyebrow">QUẢN TRỊ / EMAIL</span><h2><Mail size={22}/>Gmail gửi mã xác nhận</h2><p className="project-muted">{configured?"Đã có cấu hình Gmail trên máy này. Nhập lại Mật khẩu ứng dụng nếu muốn cập nhật.":"Thiết lập Gmail để người dùng xác nhận email và khôi phục mật khẩu."}</p>
    <ol className="admin-mail-steps"><li>Bật Xác minh 2 bước trong tài khoản Google dùng gửi thư.</li><li>Tạo <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noreferrer" onClick={event=>{if(isTauri()){event.preventDefault();void openUrl("https://myaccount.google.com/apppasswords").catch(()=>setError("Chưa mở được trình duyệt. Mở myaccount.google.com/apppasswords trong trình duyệt của bạn."));}}}>Mật khẩu ứng dụng</a> cho BIM Insight.</li><li>Nhập Gmail và mật khẩu 16 ký tự ở dưới rồi kiểm tra kết nối.</li></ol>
    <form className="work-form" aria-label="Thiết lập Gmail" onSubmit={event=>{event.preventDefault();void save();}}><label>Gmail gửi thư<input type="email" value={email} onChange={event=>setEmail(event.target.value)} required maxLength={254} autoComplete="username" disabled={loading||busy}/></label><label>Mật khẩu ứng dụng Gmail<input aria-label="Mật khẩu ứng dụng Gmail" type="password" value={password} onChange={event=>setPassword(event.target.value)} required minLength={16} maxLength={32} autoComplete="off" disabled={loading||busy}/><small>Dùng Mật khẩu ứng dụng, không dùng mật khẩu đăng nhập Google.</small></label>
      {error&&<p role="alert" className="account-error">{error}</p>}{message&&<p role="status" className="work-success">{message}</p>}<button className="button button-primary" disabled={loading||busy}>{busy?"Đang kiểm tra kết nối…":"Lưu và kiểm tra Gmail"}</button>
    </form><p className="admin-secret-note"><ShieldCheck size={16}/>Thông tin gửi thư được mã hóa trên máy này. Không nhập mật khẩu/key vào nội dung chia sẻ.</p>
  </section>;
}

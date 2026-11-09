import {useEffect,useRef,useState} from "react";
import {Download,FileSpreadsheet,UserPlus} from "lucide-react";
import {accountRequest,downloadAccountFile,roleLabels} from "./account-api";
import {errorMessage,processorFetch,type Connection} from "./inspection-api";

type Row={role:"teacher"|"student";code:string;display_name:string;email:string;values:string[];source_row:number};
type Preview={columns:string[];rows:Row[];errors:{row:number;code:string}[];valid_count:number};
type Batch={batch_id:string;created:number;failed:number;state:string;created_at:string;expires_at:string};
export default function AccountProvision({connection,onCreated}:{connection:Connection;onCreated:()=>void}){
  const [mode,setMode]=useState<"single"|"excel">("single"),[role,setRole]=useState<"teacher"|"student">("teacher");
  const [name,setName]=useState(""),[code,setCode]=useState(""),[email,setEmail]=useState(""),[preview,setPreview]=useState<Preview|null>(null),[fileName,setFileName]=useState("");
  const [busy,setBusy]=useState(false),[error,setError]=useState(""),[message,setMessage]=useState(""),[recent,setRecent]=useState<Batch[]>([]),[reload,setReload]=useState(0);
  const batchId=useRef(""),request=useRef<AbortController|null>(null);
  useEffect(()=>{const abort=new AbortController();accountRequest<{items:Batch[]}>(connection,"/api/admin/provision/batches",undefined,abort.signal).then(result=>{if(!abort.signal.aborted)setRecent(result.items);}).catch(reason=>{if(!abort.signal.aborted)setError(reason.message);});return()=>abort.abort();},[connection,reload]);
  useEffect(()=>()=>request.current?.abort(),[]);
  function changed(){batchId.current="";setMessage("");setError("");}
  async function upload(file:File){
    if(busy)return;changed();setPreview(null);setFileName(file.name);
    if(file.size>2*1024*1024){setError("File Excel tối đa 2 MiB.");return;}
    const abort=new AbortController();request.current=abort;setBusy(true);
    try{const body=new FormData();body.append("file",file);const response=await processorFetch(connection,"/api/admin/provision/preview",{method:"POST",body,signal:abort.signal});const result:Preview=await response.json();if(!abort.signal.aborted)setPreview(result);}
    catch(reason){if(!abort.signal.aborted)setError(reason instanceof Error?reason.message:"Chưa đọc được Excel.");}
    finally{if(!abort.signal.aborted)setBusy(false);}
  }
  async function issue(resume?:string){
    if(busy)return;
    const prepared=mode==="excel"?preview:{columns:["Họ và tên",role==="teacher"?"Mã giảng viên":"Mã sinh viên","email"],rows:[{role,code:code.trim(),display_name:name.trim(),email:email.trim(),values:[name,code,email],source_row:2}],errors:[],valid_count:1};
    if(!resume&&(!prepared||prepared.errors.length||!prepared.rows.length))return;
    if(!batchId.current)batchId.current=crypto.randomUUID().replace(/-/g,"");
    const abort=new AbortController();request.current=abort;setBusy(true);setError("");setMessage("");
    try{
      const result=await accountRequest<Batch>(connection,resume?`/api/admin/provision/batches/${resume}/resume`:"/api/admin/provision/batches",resume?{}:{batch_id:batchId.current,columns:prepared!.columns,rows:prepared!.rows},abort.signal);
      if(abort.signal.aborted)return;
      onCreated();setReload(value=>value+1);setMessage(`Đã cấp ${result.created} tài khoản${result.failed?`; ${result.failed} dòng trùng mã/email chưa cấp`:""}. File Excel có mật khẩu tạm dùng cho lần đăng nhập đầu.`);
      await downloadAccountFile(connection,`/api/admin/provision/batches/${result.batch_id}/export`,`BIM_Insight_TaiKhoan_${result.batch_id.slice(0,8)}.xlsx`,abort.signal);
    }catch(reason){if(!abort.signal.aborted)setError(reason instanceof Error?reason.message:"Chưa hoàn tất cấp tài khoản. Bạn có thể thử lại hoặc tải Excel ở các lô gần đây.");}
    finally{if(!abort.signal.aborted)setBusy(false);}
  }
  async function download(url:string,filename:string){
    if(busy)return;const abort=new AbortController();request.current=abort;setBusy(true);setError("");
    try{await downloadAccountFile(connection,url,filename,abort.signal);}catch(reason){if(!abort.signal.aborted)setError(reason instanceof Error?reason.message:"Chưa tải được Excel.");}finally{if(!abort.signal.aborted)setBusy(false);}
  }
  return <section className="work-panel account-provision" aria-label="Cấp tài khoản giảng viên và sinh viên"><span className="work-eyebrow">QUẢN TRỊ / CẤP TÀI KHOẢN</span><h2><UserPlus size={22}/>Cấp tài khoản đúng danh tính</h2><p className="project-muted">Dùng mã giảng viên hoặc mã sinh viên làm tên đăng nhập. Người được cấp cũng có thể đăng nhập bằng email trong danh sách.</p>
    <div className="admin-mode-tabs"><button type="button" aria-pressed={mode==="single"} disabled={busy} onClick={()=>{setMode("single");changed();}}>Cấp từng tài khoản</button><button type="button" aria-pressed={mode==="excel"} disabled={busy} onClick={()=>{setMode("excel");changed();}}><FileSpreadsheet size={16}/>Import Excel</button></div>
    {mode==="single"?<form className="work-form" onSubmit={event=>{event.preventDefault();void issue();}}><fieldset disabled={busy}><div className="profile-fields">
      <label>Loại tài khoản<select value={role} onChange={event=>{setRole(event.target.value as "teacher"|"student");changed();}}><option value="teacher">Giảng viên</option><option value="student">Sinh viên</option></select></label><label>Họ và tên<input value={name} onChange={event=>{setName(event.target.value);changed();}} minLength={2} maxLength={80} required autoComplete="off"/></label>
      <label>Mã giảng viên hoặc sinh viên<input aria-label="Mã giảng viên hoặc sinh viên" value={code} onChange={event=>{setCode(event.target.value);changed();}} minLength={3} maxLength={48} pattern={"[A-Za-z0-9][A-Za-z0-9_.\\-]{2,47}"} required autoComplete="off"/><small>Giữ nguyên các số 0 đầu mã.</small></label><label>Email tài khoản<input type="email" value={email} onChange={event=>{setEmail(event.target.value);changed();}} maxLength={254} required autoComplete="off"/></label>
    </div></fieldset><button className="button button-primary" disabled={busy}><UserPlus size={16}/>{busy?"Đang cấp tài khoản…":"Cấp tài khoản và tải Excel"}</button></form>:<div className="admin-import"><p>Excel .xlsx, tối đa 200 tài khoản và 2 MiB. Các cột: <strong>Họ và tên, Mã giảng viên hoặc Mã sinh viên, email</strong>. Có thể giữ thêm cột thông tin khác.</p>
      <div className="profile-actions"><button className="button" disabled={busy} onClick={()=>void download("/api/admin/provision/template?role=teacher","Mau_GiangVien.xlsx")}><Download size={16}/>Mẫu giảng viên</button><button className="button" disabled={busy} onClick={()=>void download("/api/admin/provision/template?role=student","Mau_SinhVien.xlsx")}><Download size={16}/>Mẫu sinh viên</button></div>
      <label className="admin-upload">File Excel cấp tài khoản<input type="file" accept=".xlsx" disabled={busy} onChange={event=>{const file=event.target.files?.[0];event.target.value="";if(file)void upload(file);}}/></label>{fileName&&<p className="project-muted">File đã chọn: {fileName}. Định dạng cột mã là Text để giữ số 0 đầu và mã dài.</p>}
      {preview&&<><p className="admin-preview-count">{preview.valid_count} tài khoản hợp lệ · {preview.errors.length} lỗi cần sửa</p>{preview.errors.length>0&&<div className="account-error" role="alert"><p>Sửa lỗi trong file rồi tải lại trước khi cấp.</p><ul>{preview.errors.map((item,index)=><li key={index}>Dòng {item.row}: {errorMessage(item.code)}</li>)}</ul></div>}
        <div className="admin-preview-table"><table><thead><tr><th>Dòng</th><th>Họ và tên</th><th>Mã</th><th>Email</th><th>Vai trò</th></tr></thead><tbody>{preview.rows.map((row,index)=><tr key={index}><td>{row.source_row}</td><td>{row.display_name}</td><td>{row.code}</td><td>{row.email}</td><td>{roleLabels[row.role]}</td></tr>)}</tbody></table></div>
        <button className="button button-primary" disabled={busy||!preview.rows.length||!!preview.errors.length} onClick={()=>void issue()}>{busy?"Đang cấp tài khoản…":`Cấp ${preview.rows.length} tài khoản và tải Excel`}</button>
      </>}
    </div>}
    {error&&<p role="alert" className="account-error">{error}</p>}{message&&<p role="status" className="work-success">{message}</p>}
    <p className="admin-secret-note">File xuất giữ thông tin ban đầu và thêm mật khẩu tạm riêng cho từng tài khoản. Chia sẻ riêng cho đúng người; app yêu cầu đổi mật khẩu trước khi sử dụng.</p>
    {recent.length>0&&<div className="admin-batches"><h3>Các lô cấp gần đây</h3><p className="project-muted">Có thể tải lại Excel trong 24 giờ trên máy đã cấp.</p>{recent.map(batch=><article key={batch.batch_id}><div><strong>{batch.state==="completed"?`${batch.created} tài khoản đã cấp`:"Lô chưa hoàn tất"}</strong><small>{new Date(batch.created_at).toLocaleString("vi-VN")}{batch.failed?` · ${batch.failed} dòng chưa cấp`:""}</small></div>{batch.state==="completed"?<button className="button" disabled={busy} onClick={()=>void download(`/api/admin/provision/batches/${batch.batch_id}/export`,`BIM_Insight_TaiKhoan_${batch.batch_id.slice(0,8)}.xlsx`)}><Download size={16}/>Tải lại Excel</button>:<button className="button" disabled={busy} onClick={()=>void issue(batch.batch_id)}>Tiếp tục cấp</button>}</article>)}</div>}
  </section>;
}

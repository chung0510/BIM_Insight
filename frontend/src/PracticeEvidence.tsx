import {lazy,Suspense,useEffect,useRef,useState} from 'react';
import {BrainCircuit,Download,Focus,RefreshCw,X} from 'lucide-react';
import {accountRequest,downloadAccountFile} from './account-api';
import {type Connection,type FocusedPair} from './inspection-api';
import {type Analysis,type PracticeEvidenceData,type Submission} from './practice-api';
import './Coordination.css';

const IfcViewer=lazy(()=>import('./IfcViewer'));
const CadViewer=lazy(()=>import('./CadViewer'));
const checks:Record<string,string>={verify_geometry:'Xác minh chất lượng hình học',review_design_intent:'Đối chiếu ý đồ thiết kế',review_system_requirements:'Kiểm tra yêu cầu vận hành và bảo trì',structural_approval:'Xin xác nhận của người phụ trách kết cấu',recheck_geometry:'Kiểm tra lại sau khi chỉnh mô hình'};

export default function PracticeEvidence({connection,submission,teacher,onBusyChange}:{connection:Connection;submission:Submission;teacher:boolean;onBusyChange:(busy:boolean)=>void}){
 const [data,setData]=useState<PracticeEvidenceData|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(true),[reload,setReload]=useState(0);
 const [selected,setSelected]=useState<string[]>([]),[documentId,setDocumentId]=useState(''),[focus,setFocus]=useState<FocusedPair|null>(null),[page,setPage]=useState(0);
 const [analysis,setAnalysis]=useState<Analysis|undefined>(submission.analysis),[aiBusy,setAiBusy]=useState(false),[runtime,setRuntime]=useState<{configured:boolean;files_present:boolean;error?:string}|null>(null);
 const request=useRef<AbortController|null>(null),busyRef=useRef(onBusyChange);busyRef.current=onBusyChange;
 const base=`/api/practice/submissions/${submission.id}`;
 useEffect(()=>{
  const abort=new AbortController();setLoading(true);setError('');setData(null);setFocus(null);setPage(0);
  accountRequest<PracticeEvidenceData>(connection,base+'/evidence',undefined,abort.signal).then(value=>{if(!abort.signal.aborted){setData(value);setSelected(value.reports.filter(file=>!!file.assets?.model).slice(0,2).map(file=>file.id));}}).catch(reason=>{if(!abort.signal.aborted)setError(reason.message);}).finally(()=>{if(!abort.signal.aborted)setLoading(false);});
  if(teacher)accountRequest<{configured:boolean;files_present:boolean}>(connection,'/api/projects/ai/runtime',undefined,abort.signal).then(value=>{if(!abort.signal.aborted)setRuntime(value);}).catch(()=>{});
  return()=>{abort.abort();request.current?.abort();busyRef.current(false);};
 },[connection.base_url,connection.token,submission.id,reload,teacher]);
 const models=(data?.reports??[]).filter(file=>!!file.assets?.model),active=models.filter(file=>selected.includes(file.id)),issues=data?.run?.issues??[];
 async function download(url:string,name:string){try{await downloadAccountFile(connection,url,name);}catch(reason){setError(reason instanceof Error?reason.message:'Chưa tải được minh chứng.');}}
 function choose(pair:FocusedPair){setSelected([...new Set([pair.a.source_id,pair.b.source_id])]);setFocus(pair);}
 async function analyze(){
  if(aiBusy)return;const abort=new AbortController();request.current=abort;setAiBusy(true);busyRef.current(true);setError('');
  try{const value=await accountRequest<Analysis>(connection,base+'/analysis',{},abort.signal);if(!abort.signal.aborted)setAnalysis(value);}
  catch(reason){if(!abort.signal.aborted)setError(reason instanceof Error?reason.message:'Chưa phân tích được bằng Qwen.');}
  finally{if(request.current===abort){setAiBusy(false);busyRef.current(false);}}
 }
 const document=data?.reports.find(file=>file.id===documentId);
 return <section className="practice-evidence role-panel" aria-label="Minh chứng bài nộp">
  <div className="role-lead"><div><h2>Minh chứng bài nộp</h2><p className="role-muted">Đúng hồ sơ tại lần nộp {submission.attempt}. Dữ liệu dự án sửa sau đó không thay bản này.</p></div><button className="button" disabled={aiBusy||loading} onClick={()=>setReload(value=>value+1)}><RefreshCw size={16}/>Tải lại minh chứng</button></div>
  {loading&&<p role="status">Đang mở hồ sơ đã nộp…</p>}
  {error&&<p className="role-error" role="alert">{error}</p>}
  {!!models.length&&<><fieldset disabled={aiBusy}><legend>Mô hình để đối chiếu</legend><div className="role-checks">{models.map(file=><label key={file.id}><input type="checkbox" checked={selected.includes(file.id)} onChange={event=>{setFocus(null);setSelected(previous=>event.target.checked?[...previous,file.id]:previous.filter(id=>id!==file.id));}}/><span>{file.name}</span></label>)}</div></fieldset>
   {aiBusy?<p className="role-note" role="status">Đang dành bộ nhớ cho Qwen. Mô hình mở lại khi phân tích kết thúc.</p>:active.length?<Suspense fallback={<p>Đang mở trình xem IFC…</p>}><IfcViewer reports={active} connection={connection} hiddenIds={new Set()} focus={focus} onClearFocus={setFocus}/></Suspense>:<p className="role-muted">Chọn mô hình để mở bản xem.</p>}
  </>}
  {data&&!models.length&&<p className="role-note">Bài nộp chưa có bản xem IFC. Đối chiếu tài liệu đã nộp và tải tệp nguồn để đánh giá.</p>}
  {submission.files.map(file=><div className="practice-file" key={file.id}><div><strong>{file.name}</strong><small>{file.kind.toUpperCase()} · {(file.size_bytes/1024**2).toFixed(1)} MiB · SHA-256 {file.sha256.slice(0,16)}…</small></div><div className="role-actions"><button className="button" disabled={aiBusy} onClick={()=>void download(base+`/files/${file.id}`,file.name)}><Download size={15}/>Tải tệp nguồn</button>{data?.reports.find(item=>item.id===file.id)?.assets?.drawing&&<button className="button" disabled={aiBusy} onClick={()=>setDocumentId(file.id)}>Xem bản vẽ</button>}</div></div>)}
  {document?.assets?.drawing&&!aiBusy&&<Suspense fallback={<p>Đang mở bản vẽ…</p>}><CadViewer report={document} connection={connection}/></Suspense>}
  {data?.run&&<><p className="role-note">{issues.length.toLocaleString('vi-VN')} cặp cần xem xét · {data.run.status==='completed'?'Hoàn tất trong phạm vi đã kiểm tra':'Kiểm tra một phần; cần xem giới hạn hình học'}. Số cặp cần xem xét chưa phải điểm bài thực hành.</p>
   {!!issues.length&&<div className="role-table-wrap"><table className="role-table"><caption>Bằng chứng hình học đã lưu</caption><thead><tr><th>Cặp</th><th>Cấu kiện</th><th>Kết quả</th></tr></thead><tbody>{issues.slice(page*20,(page+1)*20).map((issue,index)=><tr key={issue.id}><td><button className="button" disabled={aiBusy} aria-label={`Xem minh chứng ${page*20+index+1} trong 3D`} onClick={()=>choose(issue)}><Focus size={15}/>{page*20+index+1}</button></td><td>{issue.a.ifc_type} ↔ {issue.b.ifc_type}<p>{issue.a.name} / {issue.b.name}</p></td><td>{issue.kind==='intersection'?'Giao hình học':issue.kind==='clearance'?'Khoảng hở':'Bề mặt cần rà soát'}</td></tr>)}</tbody></table>{issues.length>20&&<div className="role-pagination"><button className="button" disabled={!page} onClick={()=>setPage(value=>value-1)}>20 cặp trước</button><span>{page*20+1}–{Math.min((page+1)*20,issues.length)} / {issues.length}</span><button className="button" disabled={(page+1)*20>=issues.length} onClick={()=>setPage(value=>value+1)}>20 cặp tiếp</button></div>}</div>}
  </>}
  {teacher&&<section className="practice-analysis" aria-label="Qwen hỗ trợ xem minh chứng"><h3>Qwen phân tích minh chứng</h3><p className="role-muted">Model gốc chưa fine-tune chuyên ngành. Phân tích này hỗ trợ người chấm đối chiếu hình học; điểm và kết quả công bố do giảng viên xác nhận theo tiêu chí.</p>
   <div className="role-actions"><button className="button" disabled={loading||aiBusy||!!submission.class_context?.archived||!submission.run_id||!runtime?.configured||!runtime.files_present} onClick={()=>void analyze()}><BrainCircuit size={16}/>Phân tích bài nộp bằng Qwen</button>{aiBusy&&<button className="button" onClick={()=>{request.current?.abort();setAiBusy(false);busyRef.current(false);}}><X size={16}/>Hủy phân tích Qwen</button>}</div>
   {submission.class_context?.archived&&<p className="role-muted">Lớp đã lưu trữ; phân tích đã có vẫn xem được, không tạo phân tích mới.</p>}
   {!submission.run_id&&<p className="role-muted">Bài này chưa kèm lượt kiểm tra va chạm để Qwen tổng hợp bằng chứng hình học.</p>}
   {runtime&&(!runtime.configured||!runtime.files_present)&&<p className="role-muted">Qwen local chưa sẵn sàng trên môi trường này. Giảng viên vẫn có thể đánh giá trực tiếp.</p>}
   {aiBusy&&<p role="status">Đang xác minh trọng số và chạy Qwen…</p>}
   {analysis&&<div><span className="role-tag warn">Cần giảng viên rà soát</span><p>{analysis.proposal.summary}</p>{analysis.proposal.priorities.map(item=><p key={item.group_id}>{item.rationale}</p>)}<ul>{analysis.proposal.next_steps.map(item=><li key={item}>{checks[item]??item}</li>)}</ul><p className="role-muted">{analysis.model.id} · {analysis.metrics.elapsed_seconds.toFixed(1)} giây · {analysis.evidence.issue_count.toLocaleString('vi-VN')} cặp được tổng hợp.</p></div>}
  </section>}
 </section>;
}

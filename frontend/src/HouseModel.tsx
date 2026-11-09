import {useEffect,useRef,useState,type KeyboardEvent} from "react";
import {Box,Layers3} from "lucide-react";
import {modelInfo,type ModelVariant} from "./models";
import {createResidenceStage} from "./residence-stage";
import "./Residences.css";

export default function HouseModel({variant,compact=false,autoRotate=true,paused=false}:{variant:ModelVariant;compact?:boolean;autoRotate?:boolean;paused?:boolean}) {
  const home=modelInfo(variant),mount=useRef<HTMLDivElement>(null),actions=useRef<ReturnType<typeof createResidenceStage>|null>(null);
  const [failed,setFailed]=useState(false),[ready,setReady]=useState(false),[exploded,setExploded]=useState(false),[wireframe,setWireframe]=useState(false);
  const [selected,setSelected]=useState<string|null>(null),[components,setComponents]=useState<string[]>([]),[view,setView]=useState("Phối cảnh");
  const [reduced,setReduced]=useState(()=>matchMedia("(prefers-reduced-motion: reduce)").matches);
  const [idlePaused,setIdlePaused]=useState(false),[manualPaused,setManualPaused]=useState(false),[dragging,setDragging]=useState(false);
  const holding=useRef(false);
  const idleTimer=useRef<ReturnType<typeof setTimeout>|null>(null);
  function clearIdle() {if(idleTimer.current!==null){clearTimeout(idleTimer.current);idleTimer.current=null;}}
  function interact(active?:boolean) {
    if(active!==undefined){holding.current=active;setDragging(active);}
    clearIdle();actions.current?.play(false);setIdlePaused(true);
    if(!holding.current)idleTimer.current=setTimeout(()=>{idleTimer.current=null;setIdlePaused(false);},5000);
  }
  useEffect(()=>{
    const media=matchMedia("(prefers-reduced-motion: reduce)");
    const change=()=>setReduced(media.matches);
    media.addEventListener("change",change);return()=>media.removeEventListener("change",change);
  },[]);
  useEffect(()=>{
    if(!mount.current)return;
    clearIdle();holding.current=false;setDragging(false);setIdlePaused(false);setManualPaused(false);
    setFailed(false);setReady(false);setExploded(false);setWireframe(false);setSelected(null);setView("Phối cảnh");
    try {
      const stage=createResidenceStage(mount.current,variant,setSelected,active=>{interact(active);setView("Tự do");},()=>{clearIdle();setFailed(true);setReady(false);});
      actions.current=stage;setComponents(stage.components);setReady(true);
      return()=>{clearIdle();actions.current=null;stage.dispose();};
    } catch {setFailed(true);}
  },[variant]);
  const moving=autoRotate&&!dragging&&!idlePaused&&!manualPaused&&!paused&&!reduced&&!failed;
  useEffect(()=>{actions.current?.play(moving);},[moving,ready,variant]);
  function key(event:KeyboardEvent) {
    if(!(event.target instanceof HTMLCanvasElement))return;
    const action=actions.current;if(!action)return;
    if(["ArrowLeft","ArrowRight","ArrowUp","ArrowDown","+","-","=","Home"," "].includes(event.key))event.preventDefault();
    else return;
    if(event.key===" "){if(!event.repeat){clearIdle();setIdlePaused(false);setManualPaused(value=>!value);}return;}
    interact();
    if(event.key==="ArrowLeft"||event.key==="ArrowRight"){action.rotate(event.key==="ArrowLeft"?-1:1);setView("Tự do");}
    else if(["ArrowUp","+","="].includes(event.key))action.zoom(1.13);
    else if(["ArrowDown","-"].includes(event.key))action.zoom(.88);
    else if(event.key==="Home"){action.reset();setView("Phối cảnh");}
  }
  return <div className={`residence ${compact?"is-compact":"is-full"}`} data-residence={variant} data-motion={moving?"playing":"paused"} data-render-mode={failed?"poster":"webgl"}>
    <figure className="residence-figure">
      <div className="residence-stage" ref={mount} hidden={failed} onKeyDown={key}/>
      {failed&&<div className="residence-fallback"><img src={home.image} alt={`Bản render ${home.name}`}/><p>Ảnh render tĩnh · 3D chưa khả dụng trên thiết bị này.</p></div>}
      <span className="residence-index" aria-hidden="true">BI / ARCHIVE</span>
      <figcaption className="residence-caption"><div><strong>{home.name}</strong><span>{home.location}</span></div><small>3D · BẢN DỰNG CẢM HỨNG</small></figcaption>
    </figure>
    {!compact&&<section className="residence-details" aria-label="Khám phá ngôi nhà">
      <div><span className="residence-eyebrow">{home.architect}</span><h3>{home.name}</h3><p>{home.description}</p><p className="residence-note">Mô hình nghệ thuật giản lược để khám phá hình khối. Bản vẽ mẫu trong thư viện là ví dụ độc lập.</p></div>
      <div className="residence-options"><fieldset disabled={failed}><legend>Góc quan sát</legend><div className="residence-views">{["Phối cảnh","Mặt đứng","Mặt bằng"].map(name=><button type="button" key={name} aria-pressed={view===name} onClick={()=>{interact();actions.current?.view(name);setView(name);}}>{name}</button>)}</div></fieldset>
        <div className="residence-switches"><button type="button" disabled={failed} aria-pressed={exploded} onClick={()=>{interact();actions.current?.explode(!exploded,reduced);setExploded(!exploded);}}><Layers3 size={17}/>{exploded?"Ghép mái":"Tách mái"}</button><button type="button" disabled={failed} aria-pressed={wireframe} onClick={()=>{interact();actions.current?.wireframe(!wireframe);setWireframe(!wireframe);}}><Box size={17}/>Khung dây</button></div>
        <label className="residence-component">Khám phá cấu kiện<select aria-label="Chọn cấu kiện" disabled={failed} value={selected??""} onChange={event=>{interact();actions.current?.select(event.target.value||null);}}><option value="">Chọn trên mô hình…</option>{components.map(name=><option key={name} value={name}>{name}</option>)}</select></label>
        <p role="status" className="residence-selection">{selected&&<>{selected}<br/></>}Kéo để xoay · Cuộn/chụm để zoom · Tự quay sau 5 giây<br/>Phím mũi tên / + / − / Home · Space để dừng hoặc tiếp tục quay</p>
      </div>
    </section>}
  </div>;
}

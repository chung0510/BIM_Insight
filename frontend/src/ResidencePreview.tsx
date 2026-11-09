import {lazy,Suspense} from "react";
import {modelInfo,type ModelVariant} from "./models";
import "./Residences.css";

const HouseModel=lazy(()=>import("./HouseModel"));
export default function ResidencePreview({variant,paused=false}:{variant:ModelVariant;paused?:boolean}) {
  const home=modelInfo(variant);
  return <div className="residence-slot"><Suspense fallback={<div className="residence-loading"><img src={home.image} alt={`Mô hình ${home.name}`}/><span>Đang mở {home.name}…</span></div>}><HouseModel key={variant} variant={variant} compact autoRotate paused={paused}/></Suspense></div>;
}

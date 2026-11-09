import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Maximize2, Minus, Plus } from "lucide-react";
import { processorFetch, type Connection, type Inspection, type LinkResult } from "./inspection-api";

type Drawing = {
  view_box: [number, number, number, number];
  source_to_svg?: [number, number, number, number, number, number];
  paths: { d: string; layer: string; fill: string; stroke: string; stroke_width: number; fill_opacity: number; stroke_opacity: number }[];
};

export default function CadViewer({ report, connection, marker }: { report: Inspection; connection: Connection; marker?: { point: [number, number, number]; link: LinkResult } }) {
  const [drawing, setDrawing] = useState<Drawing | null>(null);
  const [view, setView] = useState<[number, number, number, number] | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");
  const drag = useRef<{ x: number; y: number; view: [number, number, number, number] } | null>(null);
  useEffect(() => {
    const abort = new AbortController();
    setDrawing(null);
    setError("");
    setFilter("");
    setHidden(new Set(report.result?.layers?.filter(layer => !layer.visible).map(layer => layer.name)));
    processorFetch(connection, report.assets!.drawing!, { signal: abort.signal })
      .then(response => response.json())
      .then((data: Drawing) => {
        if (!abort.signal.aborted) { setDrawing(data); setView(data.view_box); }
      }).catch(error => { if (!abort.signal.aborted) setError(error.message); });
    return () => abort.abort();
  }, [report.id, connection.base_url, connection.token]);
  const paths = useMemo(() => drawing?.paths.filter(path => !hidden.has(path.layer)) ?? [], [drawing, hidden]);
  const layers = report.result?.layers ?? [];
  let pin: [number, number] | null = null;
  if (marker && drawing?.source_to_svg) {
    const { link, point } = marker;
    const angle = link.rotation_deg * Math.PI / 180, cosine = Math.cos(angle), sine = Math.sin(angle);
    const dx = point[0] - link.dx_m, dy = point[1] - link.dy_m;
    const x = (dx * cosine + dy * sine) / link.unit_scale_to_m, y = (-dx * sine + dy * cosine) / link.unit_scale_to_m;
    const [a, b, c, d, tx, ty] = drawing.source_to_svg;
    const position: [number, number] = [a * x + c * y + tx, b * x + d * y + ty];
    if (position.every(Number.isFinite)) pin = position;
  }
  function zoom(factor: number) {
    setView(current => {
      if (!current || !drawing) return current;
      const [x, y, w, h] = current;
      const width = Math.max(drawing.view_box[2] / 100, Math.min(drawing.view_box[2] * 10, w * factor));
      const ratio = width / w;
      return [x + w * (1 - ratio) / 2, y + h * (1 - ratio) / 2, width, h * ratio];
    });
  }
  function pan(x: number, y: number) { setView(v => v ? [v[0] + x * v[2], v[1] + y * v[3], v[2], v[3]] : v); }
  return <div className="cad-viewer">
    <div className="coord-toolbar">
      <span>DXF · Model space · {report.result?.unit_name}</span>
      <div>
        <button aria-label="Thu nhỏ bản vẽ" onClick={() => zoom(1.25)} disabled={!drawing}><Minus size={16} /></button>
        <button aria-label="Phóng to bản vẽ" onClick={() => zoom(0.8)} disabled={!drawing}><Plus size={16} /></button>
        <button aria-label="Vừa bản vẽ" onClick={() => drawing && setView(drawing.view_box)} disabled={!drawing}><Maximize2 size={16} /></button>
      </div>
    </div>
    <div className="cad-canvas">
      {error ? <p role="alert">{error}</p> : !drawing || !view ? <p role="status">Đang mở bản vẽ…</p> : <svg
        role="img" aria-label="Bản vẽ DXF của bạn" viewBox={view.join(" ")} tabIndex={0}
        onKeyDown={event => {
          if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "+", "-", "Home"].includes(event.key)) event.preventDefault();
          if (event.key === "ArrowLeft") pan(-0.1, 0);
          if (event.key === "ArrowRight") pan(0.1, 0);
          if (event.key === "ArrowUp") pan(0, -0.1);
          if (event.key === "ArrowDown") pan(0, 0.1);
          if (event.key === "+") zoom(0.8);
          if (event.key === "-") zoom(1.25);
          if (event.key === "Home") setView(drawing.view_box);
        }}
        onPointerDown={event => {
          drag.current = { x: event.clientX, y: event.clientY, view };
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={event => {
          const start = drag.current;
          if (!start) return;
          const bounds = event.currentTarget.getBoundingClientRect();
          const unitsPerPixel = Math.max(start.view[2] / bounds.width, start.view[3] / bounds.height);
          setView([start.view[0] - (event.clientX - start.x) * unitsPerPixel, start.view[1] - (event.clientY - start.y) * unitsPerPixel, start.view[2], start.view[3]]);
        }}
        onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}>
        <g strokeLinecap="round" strokeLinejoin="round" fillRule="evenodd">
          {paths.map((path, index) => <path key={index} data-layer={path.layer} d={path.d} fill={path.fill} stroke={path.stroke} strokeWidth={path.stroke_width} fillOpacity={path.fill_opacity} strokeOpacity={path.stroke_opacity} />)}
        </g>
        {pin && <g data-testid="cad-clash-marker" role="img" aria-label="Điểm chiếu XY của va chạm trên tầng đã liên kết"><circle cx={pin[0]} cy={pin[1]} r={view[2] * .012} fill="#ed965d" stroke="#fff6c9" strokeWidth={view[2] * .003} /><circle cx={pin[0]} cy={pin[1]} r={view[2] * .025} fill="none" stroke="#ed965d" strokeWidth={view[2] * .002} /></g>}
      </svg>}
      <div className="cad-pan-buttons" aria-label="Di chuyển bản vẽ">
        <button aria-label="Dịch bản vẽ sang trái" onClick={() => pan(-0.1, 0)}><ArrowLeft size={15} /></button>
        <button aria-label="Dịch bản vẽ lên" onClick={() => pan(0, -0.1)}><ArrowUp size={15} /></button>
        <button aria-label="Dịch bản vẽ xuống" onClick={() => pan(0, 0.1)}><ArrowDown size={15} /></button>
        <button aria-label="Dịch bản vẽ sang phải" onClick={() => pan(0.1, 0)}><ArrowRight size={15} /></button>
      </div>
    </div>
    {marker && !drawing?.source_to_svg && <p className="coord-level-note">Preview chưa có phép ánh xạ điểm. Nhập lại DXF để định vị kết quả.</p>}
    <details className="cad-layers" open>
      <summary>Layer bản vẽ <span>{layers.length}</span></summary>
      <input aria-label="Tìm layer" placeholder="Tìm layer…" value={filter} onChange={event => setFilter(event.target.value)} />
      <div className="cad-layer-list">
        {layers.filter(layer => layer.name.toLowerCase().includes(filter.toLowerCase())).map(layer => <label key={layer.name}>
          <input type="checkbox" aria-label={`Layer ${layer.name}`} checked={!hidden.has(layer.name)} onChange={() => setHidden(current => {
            const next = new Set(current); if (next.has(layer.name)) next.delete(layer.name); else next.add(layer.name); return next;
          })} /><span>{layer.name}</span>
        </label>)}
      </div>
    </details>
  </div>;
}

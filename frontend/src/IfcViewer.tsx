import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { Box, Maximize2, Minus, Plus, RotateCw, ScanLine } from "lucide-react";
import { processorFetch, type FocusedPair, type Connection, type Inspection } from "./inspection-api";

type Element = {
  guid: string; ifc_type: string; name: string | null; storey_guid?: string;
  bounds_m: { min: number[]; max: number[] };
};
type Pick = Element & { key: string; source: string; source_id: string };
type Actions = { reset: () => void; rotate: () => void; zoom: (factor: number) => void; top: () => void; wire: () => void; pick: (key: string) => void; focus: (issue: FocusedPair | null) => void; visibility: (hidden: Set<string>) => void };

export default function IfcViewer({ reports, connection, hiddenIds, focus, onClearFocus }: { reports: Inspection[]; connection: Connection; hiddenIds: Set<string>; focus: FocusedPair | null; onClearFocus: (value: null) => void }) {
  const mount = useRef<HTMLDivElement>(null);
  const actions = useRef<Actions | null>(null);
  const currentHidden = useRef(hiddenIds);
  currentHidden.current = hiddenIds;
  const currentFocus = useRef(focus); currentFocus.current = focus;
  const clearFocus = useRef(onClearFocus); clearFocus.current = onClearFocus;
  const [pairCount, setPairCount] = useState(0);
  const [status, setStatus] = useState("Đang mở mô hình IFC…");
  const [error, setError] = useState("");
  const [options, setOptions] = useState<Pick[]>([]);
  const [selected, setSelected] = useState<Pick | null>(null);
  const [search, setSearch] = useState("");
  const [wire, setWire] = useState(false);
  const key = reports.map(report => report.id).join(",");

  useEffect(() => {
    const container = mount.current;
    if (!container) return;
    const abort = new AbortController();
    let renderer: THREE.WebGLRenderer;
    try { renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }); }
    catch { setError("Thiết bị chưa mở được WebGL. Bạn vẫn có thể xem metadata và bản vẽ DXF."); return; }
    setError(""); setOptions([]); setSelected(null); setSearch(""); setWire(false); setPairCount(0);
    setStatus("Đang mở mô hình IFC…");
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor("#ebe5d7", 1);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.domElement.setAttribute("aria-label", "Mô hình IFC của bạn");
    renderer.domElement.tabIndex = 0;
    container.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    scene.add(new THREE.HemisphereLight(0xfff7e9, 0x777d70, 2.5));
    const sun = new THREE.DirectionalLight(0xfff7e5, 2.5);
    sun.position.set(10, -8, 20); scene.add(sun);
    const camera = new THREE.PerspectiveCamera(42, 1, 0.01, 10000);
    camera.up.set(0, 0, 1);
    camera.position.set(12, -16, 12);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = false;
    controls.listenToKeyEvents(renderer.domElement);
    const content = new THREE.Group();
    // IfcOpenShell writes glTF Y-up; restore IFC Z-up before centering all sources together.
    content.rotation.x = Math.PI / 2;
    scene.add(content);
    const groups = new Map<string, THREE.Group>();
    const meshes = new Map<string, THREE.Mesh[]>();
    const metadata = new Map<string, Pick>();
    const render = () => { if (!abort.signal.aborted) renderer.render(scene, camera); };
    controls.addEventListener("change", render);
    let radius = 10;
    let highlight: { mesh: THREE.Mesh; original: THREE.Material | THREE.Material[]; clones: THREE.Material[] }[] = [];
    let isWire = false;
    let activeFocus: FocusedPair | null = null;
    function clearHighlight() {
      for (const item of highlight) { item.mesh.material = item.original; item.clones.forEach(material => material.dispose()); }
      highlight = [];
    }
    function visible(mesh: THREE.Object3D) {
      let object: THREE.Object3D | null = mesh;
      while (object) { if (!object.visible) return false; object = object.parent; }
      return true;
    }
    function paint(id: string, color: string, ghost = false) {
        for (const mesh of meshes.get(id) ?? []) {
          const original = mesh.material;
          const copies = (Array.isArray(original) ? original : [original]).map(material => {
            const copy = material.clone() as THREE.MeshStandardMaterial;
            copy.color?.set(color); copy.emissive?.set(color).multiplyScalar(.15);
            if (ghost) { copy.transparent = true; copy.opacity = Math.min(copy.opacity, .25); copy.depthWrite = false; }
            return copy;
          });
          mesh.material = Array.isArray(original) ? copies : copies[0];
          highlight.push({ mesh, original, clones: copies });
        }
    }
    function applyFocus(issue: FocusedPair | null) {
      if (!issue && !activeFocus) return;
      activeFocus = issue; clearHighlight(); setSelected(null); setPairCount(0);
      const keys = issue ? [issue.a, issue.b].map(item => `${item.source_id}:${item.guid}`) : [];
      for (const [id, objects] of meshes) for (const mesh of objects) mesh.visible = !issue || keys.includes(id);
      if (issue) {
        const bounds = new THREE.Box3(); content.updateMatrixWorld(true);
        const volumes = keys.map(id => { const box = metadata.get(id)?.bounds_m; return box ? box.max.reduce((volume, n, index) => volume * Math.max(0, n - box.min[index]), 1) : 0; });
        // Ghost the larger envelope so a fully enclosed partner remains visible.
        const ghostIndex = volumes[0] >= volumes[1] ? 0 : 1;
        keys.forEach((id, index) => { paint(id, index === 0 ? "#c46a42" : "#298f9a", index === ghostIndex); for (const mesh of meshes.get(id) ?? []) bounds.union(new THREE.Box3().setFromObject(mesh)); });
        setPairCount(keys.filter(id => meshes.has(id)).length);
        if (!bounds.isEmpty()) {
          const center = bounds.getCenter(new THREE.Vector3());
          const size = Math.max(bounds.getSize(new THREE.Vector3()).length() / 2, .1);
          controls.minDistance = Math.min(radius * .05, size * .3);
          controls.target.copy(center); camera.position.copy(center).add(new THREE.Vector3(size * 1.8, -size * 2.4, size * 1.6)); controls.update();
        }
      }
      render();
    }
    function pick(id: string) {
      if (activeFocus) { applyFocus(null); clearFocus.current(null); }
      clearHighlight();
      const objects = meshes.get(id) ?? [];
      if (objects.some(visible)) {
        paint(id, "#c36a3e");
        setSelected(metadata.get(id) ?? null);
      } else setSelected(null);
      render();
    }
    function reset() {
      camera.position.set(radius * 1.15, -radius * 1.5, radius);
      controls.target.set(0, 0, 0); controls.update(); render();
    }
    actions.current = {
      reset() { applyFocus(null); clearFocus.current(null); reset(); },
      rotate() { camera.position.sub(controls.target).applyAxisAngle(new THREE.Vector3(0, 0, 1), Math.PI / 6).add(controls.target); controls.update(); render(); },
      zoom(factor) { camera.position.sub(controls.target).multiplyScalar(factor).add(controls.target); controls.update(); render(); },
      top() { const distance = camera.position.distanceTo(controls.target); camera.position.copy(controls.target).add(new THREE.Vector3(0, -.001, distance)); controls.update(); render(); },
      wire() {
        applyFocus(null); clearFocus.current(null); clearHighlight(); setSelected(null); isWire = !isWire; setWire(isWire);
        content.traverse(object => { if (object instanceof THREE.Mesh) (Array.isArray(object.material) ? object.material : [object.material]).forEach(material => { if ("wireframe" in material) material.wireframe = isWire; }); });
        render();
      },
      pick,
      focus: applyFocus,
      visibility(hidden) { for (const [id, group] of groups) group.visible = !hidden.has(id); if (highlight.some(item => !visible(item.mesh))) { clearHighlight(); setSelected(null); } render(); },
    };
    const resize = () => {
      const width = container.clientWidth || 400, height = container.clientHeight || 440;
      renderer.setSize(width, height); camera.aspect = width / height; camera.updateProjectionMatrix(); render();
    };
    const observer = new ResizeObserver(resize); observer.observe(container); resize();
    const pointer = new THREE.Vector2();
    const ray = new THREE.Raycaster();
    let down: [number, number] = [0, 0];
    const onDown = (event: PointerEvent) => { down = [event.clientX, event.clientY]; };
    const onPick = (event: PointerEvent) => {
      if (Math.hypot(event.clientX - down[0], event.clientY - down[1]) > 5) return;
      const bounds = renderer.domElement.getBoundingClientRect();
      pointer.set((event.clientX - bounds.left) / bounds.width * 2 - 1, -(event.clientY - bounds.top) / bounds.height * 2 + 1);
      ray.setFromCamera(pointer, camera);
      const targets = [...meshes.values()].flat().filter(visible);
      const hit = ray.intersectObjects(targets, false)[0];
      if (hit) pick(hit.object.userData.bimKey);
    };
    renderer.domElement.addEventListener("pointerdown", onDown);
    renderer.domElement.addEventListener("pointerup", onPick);
    const loader = new GLTFLoader();
    void (async () => {
      const failed: string[] = [];
      let loadedBytes = 0;
      for (const report of reports) {
        if (abort.signal.aborted) return;
        setStatus(`Đang mở mô hình ${groups.size + 1}/${reports.length}…`);
        try {
        const [response, mappingResponse] = await Promise.all([
          processorFetch(connection, report.assets!.model!, { signal: abort.signal }),
          processorFetch(connection, report.assets!.mapping!, { signal: abort.signal }),
        ]);
        const modelBytes = Number(response.headers.get("Content-Length")), mappingBytes = Number(mappingResponse.headers.get("Content-Length"));
        const bytes = modelBytes + mappingBytes;
        if (modelBytes <= 0 || mappingBytes <= 0 || !Number.isFinite(bytes) || loadedBytes + bytes > connection.processing_limits.viewer_bytes) {
          await Promise.allSettled([response.body?.cancel(), mappingResponse.body?.cancel()]);
          throw new Error("Tổng dữ liệu 3D và ánh xạ vượt ngân sách trình xem. Bỏ chọn bớt hồ sơ trong Dự án và lịch sử để xem các mô hình còn lại; kết quả kiểm tra và báo cáo vẫn được giữ.");
        }
        loadedBytes += bytes;
        const [binary, mapping] = await Promise.all([
          response.arrayBuffer(),
          mappingResponse.json() as Promise<{ elements: Element[] }>,
        ]);
        const gltf = await loader.parseAsync(binary, "");
        if (abort.signal.aborted) {
          gltf.scene.traverse(object => { if (object instanceof THREE.Mesh) { object.geometry.dispose(); (Array.isArray(object.material) ? object.material : [object.material]).forEach(material => material.dispose()); } });
          return;
        }
        const byGuid = new Map(mapping.elements.map(element => [element.guid, element]));
        const group = new THREE.Group(); group.add(gltf.scene); content.add(group); groups.set(report.id, group);
        gltf.scene.traverse(object => {
          if (!(object instanceof THREE.Mesh)) return;
          let parent: THREE.Object3D | null = object;
          let element: Element | undefined;
          while (parent && !element) { element = byGuid.get(parent.name); parent = parent.parent; }
          if (!element) return;
          const id = `${report.id}:${element.guid}`;
          metadata.set(id, { ...element, key: id, source: report.name, source_id: report.id });
          object.userData.bimKey = id;
          meshes.set(id, [...(meshes.get(id) ?? []), object]);
          (Array.isArray(object.material) ? object.material : [object.material]).forEach(material => { material.side = THREE.DoubleSide; });
        });
        } catch (error) {
          if (abort.signal.aborted) return;
          failed.push(error instanceof Error ? error.message : "Chưa mở được mô hình.");
        }
      }
      if (abort.signal.aborted) return;
      if (failed.length) setError(`${failed.length} mô hình chưa tải được. ${[...new Set(failed)].join(" ")}`);
      content.updateMatrixWorld(true);
      const bounds = new THREE.Box3().setFromObject(content);
      if (!bounds.isEmpty()) {
        const center = bounds.getCenter(new THREE.Vector3());
        content.position.sub(center);
        radius = Math.max(bounds.getSize(new THREE.Vector3()).length() / 2, 1);
        camera.far = Math.max(radius * 30, 100); camera.near = Math.max(radius / 10000, 0.001); camera.updateProjectionMatrix();
        controls.minDistance = radius * 0.05; controls.maxDistance = radius * 15;
        const grid = new THREE.GridHelper(radius * 3, 30, 0xb4ad9a, 0xd6d0c0); grid.rotation.x = Math.PI / 2; grid.position.z = bounds.min.z - center.z - 0.02; scene.add(grid);
      }
      setOptions([...metadata.values()]);
      setStatus(`Đã hiển thị ${groups.size}/${reports.length} mô hình`);
      actions.current?.visibility(currentHidden.current); reset(); applyFocus(currentFocus.current);
    })().catch(error => { if (!abort.signal.aborted) setError(error.message); });
    return () => {
      abort.abort(); observer.disconnect(); controls.dispose(); actions.current = null;
      renderer.domElement.removeEventListener("pointerdown", onDown); renderer.domElement.removeEventListener("pointerup", onPick);
      clearHighlight();
      const geometries = new Set<THREE.BufferGeometry>(), materials = new Set<THREE.Material>();
      scene.traverse(object => {
        if (object instanceof THREE.Mesh || object instanceof THREE.LineSegments) { geometries.add(object.geometry); (Array.isArray(object.material) ? object.material : [object.material]).forEach(material => materials.add(material)); }
      });
      geometries.forEach(geometry => geometry.dispose()); materials.forEach(material => material.dispose());
      renderer.dispose(); renderer.forceContextLoss(); renderer.domElement.remove();
    };
  }, [key, connection.base_url, connection.token]);
  useEffect(() => { actions.current?.visibility(hiddenIds); }, [hiddenIds]);
  useEffect(() => { actions.current?.focus(focus); }, [focus]);
  const matches = options.filter(option => !hiddenIds.has(option.source_id) && `${option.source} ${option.name ?? ""} ${option.ifc_type} ${option.guid}`.toLocaleLowerCase("vi").includes(search.toLocaleLowerCase("vi")));
  const shownOptions = matches.slice(0, 200);
  if (selected && !shownOptions.some(option => option.key === selected.key)) shownOptions.unshift(selected);

  return <div className="ifc-viewer">
    <div className="coord-toolbar"><span role="status">{status}</span><div>
      <button aria-label="Thu nhỏ mô hình" onClick={() => actions.current?.zoom(1.2)}><Minus size={16} /></button>
      <button aria-label="Phóng to mô hình" onClick={() => actions.current?.zoom(0.8)}><Plus size={16} /></button>
      <button aria-label="Xoay mô hình" onClick={() => actions.current?.rotate()}><RotateCw size={16} /></button>
      <button aria-label="Nhìn từ trên" onClick={() => actions.current?.top()}><ScanLine size={16} /></button>
      <button aria-label="Vừa mô hình" onClick={() => actions.current?.reset()}><Maximize2 size={16} /></button>
      <button aria-label="Khung dây IFC" aria-pressed={wire} onClick={() => actions.current?.wire()}><Box size={16} /></button>
    </div></div>
    {error && <p className="coord-error" role="alert">{error}</p>}
    <div className="ifc-canvas" ref={mount} />
    {focus && <div className="ifc-pair-selection" data-testid="clash-selection"><strong>{pairCount === 2 ? "Đang cô lập 2 cấu kiện" : "Chưa tải đủ cặp cấu kiện"}</strong><p>Màu đất nung: cấu kiện A · Xanh lam: cấu kiện B. Cấu kiện lớn hiển thị bán trong suốt để thấy phần bị che.</p>{[focus.a, focus.b].map((element, index) => <div className={`clash-element element-${index}`} key={`${element.source_id}:${element.guid}`}><strong>{element.name || element.ifc_type}</strong><small>{element.source_name}</small><code>{element.guid}</code></div>)}<button onClick={() => { actions.current?.focus(null); onClearFocus(null); }}>Bỏ cô lập cặp cấu kiện</button></div>}
    <div className="ifc-inspector">
      {options.length > 200 && <label>Tìm cấu kiện IFC<input aria-label="Tìm cấu kiện IFC" value={search} onChange={event => setSearch(event.target.value)} placeholder="Tên, loại cấu kiện hoặc GUID…" /><small>Hiện tối đa 200 kết quả phù hợp; có thể chọn trực tiếp trên mô hình.</small></label>}
      <label>Chọn cấu kiện IFC<select aria-label="Chọn cấu kiện IFC" value={selected?.key ?? ""} onChange={event => actions.current?.pick(event.target.value)}>
        <option value="">Chạm cấu kiện trên 3D hoặc chọn tại đây</option>
        {shownOptions.map(option => <option value={option.key} key={option.key}>{option.source} · {option.name || option.ifc_type}</option>)}
      </select></label>
      {selected && <div className="ifc-selection" data-testid="ifc-selection"><strong>{selected.name || selected.ifc_type}</strong><span>{selected.source} · {selected.ifc_type}</span><code>{selected.guid}</code><small>Min {selected.bounds_m.min.map(n => n.toFixed(3)).join(" · ")} m<br />Max {selected.bounds_m.max.map(n => n.toFixed(3)).join(" · ")} m</small></div>}
    </div>
  </div>;
}

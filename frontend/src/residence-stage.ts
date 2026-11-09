import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { createResidence } from "./residence-geometry";
import { modelInfo, type ModelVariant } from "./models";

export function createResidenceStage(container: HTMLElement, variant: ModelVariant, onSelect: (label: string | null) => void, onInteract: (active:boolean) => void, onLost: () => void) {
  const home = createResidence(variant);
  let renderer: THREE.WebGLRenderer;
  try { renderer = new THREE.WebGLRenderer({alpha:true, antialias:true, powerPreference:"low-power"}); }
  catch(error) { home.dispose(); throw error; }
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
  renderer.setClearColor(0x000000, 0); renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.0;
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFShadowMap;
  const canvas = renderer.domElement; canvas.setAttribute("role","img");
  canvas.setAttribute("aria-label", `Mô hình 3D ${modelInfo(variant).name}. Kéo để xoay; cuộn hoặc chụm để zoom. Tự quay sau 5 giây. Phím mũi tên, cộng, trừ, Home; Space để dừng hoặc tiếp tục quay.`);
  canvas.tabIndex = 0; container.appendChild(canvas);
  const scene = new THREE.Scene(); scene.add(home.root);
  const environment = new RoomEnvironment(), pmrem = new THREE.PMREMGenerator(renderer);
  const reflection = pmrem.fromScene(environment, .06); scene.environment = reflection.texture; scene.environmentIntensity = .45;
  environment.dispose(); pmrem.dispose();
  scene.add(new THREE.HemisphereLight(0xfff6e0, 0x567669, 1.7));
  const sun = new THREE.DirectionalLight(0xffe7bc, 2.5); sun.position.set(-6,12,8); sun.castShadow = true;
  sun.shadow.mapSize.set(1024,1024); Object.assign(sun.shadow.camera,{left:-10,right:10,top:10,bottom:-10,near:.1,far:40});
  sun.shadow.bias = -.00035; sun.shadow.normalBias = .025; sun.shadow.radius = 3; scene.add(sun);
  const fill = new THREE.DirectionalLight(0xc5e1d7, .85); fill.position.set(7,5,-5); scene.add(fill);
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(70,70), new THREE.ShadowMaterial({color:0x132a20,opacity:.22}));
  ground.rotation.x=-Math.PI/2;ground.position.y=-.61;ground.receiveShadow=true;scene.add(ground);
  const bounds = new THREE.Box3().setFromObject(home.root), target = bounds.getCenter(new THREE.Vector3());
  const camera = new THREE.OrthographicCamera(-10,10,8,-8,.1,100);
  camera.position.copy(target).add(new THREE.Vector3(13,10,16)); camera.lookAt(target);
  const controls = new OrbitControls(camera,canvas);controls.target.copy(target);controls.enablePan=false;
  controls.enableDamping=true;controls.dampingFactor=.12;controls.rotateSpeed=.65;controls.zoomSpeed=.65;
  controls.minPolarAngle=.04;controls.maxPolarAngle=Math.PI/2-.04;controls.minZoom=.65;controls.maxZoom=2.6;
  controls.update(); controls.saveState();
  let playing=false,visible=true,disposed=false,lost=false,raf=0,last=0,lastDraw=0,dirty=2,roofTarget=0,refitAfterLowering=false;
  let selection: THREE.BoxHelper | null = null;
  function draw() { home.root.updateMatrixWorld(true);selection?.update();renderer.render(scene,camera); }
  function schedule() { if(!disposed&&!lost&&visible&&!document.hidden&&!raf) raf=requestAnimationFrame(frame); }
  function invalidate() { dirty=Math.max(dirty,3);schedule(); }
  function frame(time:number) {
    raf=0;if(disposed||lost||!visible||document.hidden)return;
    if(lastDraw && time-lastDraw<1000/30){schedule();return;}
    lastDraw=time;
    const dt=Math.min((time-(last||time))/1000,.06);last=time;
    if(playing)home.root.rotation.y+=dt*.085;
    const lifting=Math.abs(home.roof.position.y-roofTarget)>.002;
    if(lifting)home.roof.position.y=THREE.MathUtils.damp(home.roof.position.y,roofTarget,10,dt||1/60);
    if(!lifting&&refitAfterLowering){refitAfterLowering=false;fitRoof(0);}
    controls.update();draw();dirty--;
    if(playing||lifting||dirty>0)schedule();
  }
  function resize() {
    if(disposed||lost||!container.clientWidth||!container.clientHeight)return;
    const aspect=container.clientWidth/container.clientHeight;
    camera.updateMatrixWorld(true);
    const projected = new THREE.Box3();
    for(const x of [bounds.min.x,bounds.max.x])for(const y of [bounds.min.y,bounds.max.y])for(const z of [bounds.min.z,bounds.max.z])projected.expandByPoint(new THREE.Vector3(x,y,z).applyMatrix4(camera.matrixWorldInverse));
    const span=projected.getSize(new THREE.Vector3());
    const half=Math.max(span.y/2,span.x/(2*aspect))*1.06;
    camera.left=-half*aspect;camera.right=half*aspect;camera.top=half;camera.bottom=-half;camera.updateProjectionMatrix();
    renderer.setSize(container.clientWidth,container.clientHeight);invalidate();
  }
  function fitRoof(offset:number) {
    const previous=home.roof.position.y;home.roof.position.y=offset;
    const nextBounds=new THREE.Box3().setFromObject(home.root);
    home.roof.position.y=previous;home.root.updateMatrixWorld(true);
    const center=nextBounds.getCenter(new THREE.Vector3());
    camera.position.add(center.clone().sub(controls.target));target.copy(center);controls.target.copy(center);bounds.copy(nextBounds);
    controls.update();resize();
  }
  function clearSelection() {if(selection){scene.remove(selection);selection.geometry.dispose();(selection.material as THREE.Material).dispose();selection=null;}}
  function select(label:string|null, picked?:THREE.Object3D) {
    clearSelection();const object=picked??(label?home.find(label):undefined);
    if(object){selection=new THREE.BoxHelper(object,0xb85334);selection.material.depthTest=false;selection.renderOrder=10;scene.add(selection);}
    onSelect(object?label:null);invalidate();
  }
  const start={x:0,y:0},raycaster=new THREE.Raycaster();
  const down=(event:PointerEvent)=>{start.x=event.clientX;start.y=event.clientY;};
  const pick=(event:PointerEvent)=>{
    if(event.button!==0||Math.hypot(event.clientX-start.x,event.clientY-start.y)>5)return;
    const rect=canvas.getBoundingClientRect();raycaster.setFromCamera(new THREE.Vector2((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1),camera);
    const hit=raycaster.intersectObject(home.root,true).find(hit=>hit.object.userData.label);
    select(hit?.object.userData.label??null,hit?.object);
  };
  const change=()=>invalidate(),interaction=()=>{playing=false;onInteract(true);invalidate();},endInteraction=()=>onInteract(false);
  const contextLost=(event:Event)=>{event.preventDefault();lost=true;cancelAnimationFrame(raf);raf=0;onLost();};
  const visibility=()=>{cancelAnimationFrame(raf);raf=0;last=0;if(!document.hidden)invalidate();};
  const resizeObserver=new ResizeObserver(resize);resizeObserver.observe(container);
  const intersection=new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;if(visible){last=0;invalidate();}else{cancelAnimationFrame(raf);raf=0;}});intersection.observe(container);
  controls.addEventListener("change",change);controls.addEventListener("start",interaction);controls.addEventListener("end",endInteraction);
  canvas.addEventListener("pointerdown",down);canvas.addEventListener("pointerup",pick);canvas.addEventListener("webglcontextlost",contextLost);
  document.addEventListener("visibilitychange",visibility);
  resize();
  return {
    components:home.components,canvas,
    play(value:boolean){playing=value;last=0;invalidate();},
    rotate(direction=1){home.root.rotation.y+=direction*Math.PI/8;invalidate();},
    zoom(factor:number){camera.zoom=THREE.MathUtils.clamp(camera.zoom*factor,.65,2.6);camera.updateProjectionMatrix();invalidate();},
    reset(){home.root.rotation.y=0;camera.zoom=1;controls.target.copy(target);camera.position.copy(target).add(new THREE.Vector3(13,10,16));controls.update();resize();},
    explode(value:boolean,immediate=false){
      roofTarget=value?2.2:0;refitAfterLowering=!value&&!immediate;
      if(value||immediate)fitRoof(roofTarget);
      if(immediate)home.roof.position.y=roofTarget;
      invalidate();
    },
    wireframe(value:boolean){for(const group of [home.architecture,home.structure,home.roof])group.traverse(object=>{if(object instanceof THREE.Mesh)(object.material as THREE.MeshStandardMaterial).wireframe=value;});invalidate();},
    view(name:string){home.root.rotation.y=0;camera.zoom=1;controls.target.copy(target);camera.position.copy(target).add(name==="Mặt bằng"?new THREE.Vector3(0,24,.001):name==="Mặt đứng"?new THREE.Vector3(0,.001,25):new THREE.Vector3(13,10,16));controls.update();resize();},
    select,
    capture(){draw();return canvas.toDataURL("image/webp",.9);},
    dispose(){
      disposed=true;cancelAnimationFrame(raf);resizeObserver.disconnect();intersection.disconnect();document.removeEventListener("visibilitychange",visibility);
      controls.removeEventListener("change",change);controls.removeEventListener("start",interaction);controls.removeEventListener("end",endInteraction);controls.dispose();
      canvas.removeEventListener("pointerdown",down);canvas.removeEventListener("pointerup",pick);canvas.removeEventListener("webglcontextlost",contextLost);
      clearSelection();home.dispose();ground.geometry.dispose();ground.material.dispose();sun.shadow.map?.dispose();reflection.dispose();renderer.dispose();renderer.forceContextLoss();canvas.remove();
    },
  };
}

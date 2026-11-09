import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import type { ModelVariant } from "./models.ts";

// Artistic massing studies; dimensions and hidden construction are not surveyed BIM data.
export function createResidence(variant: ModelVariant) {
  const root = new THREE.Group(), architecture = new THREE.Group(), structure = new THREE.Group();
  const landscape = new THREE.Group(), roof = new THREE.Group();
  root.add(landscape, structure, architecture, roof);
  const colors = { cream: 0xf0e7d4, white: 0xf2efe5, stone: 0xb0a08a, brick: 0x99523f, wood: 0x9b744d, dark: 0x293a32, steel: 0x393c36, green: 0x607653, sage: 0x8e9b72, soil: 0xc4b08d, glass: 0x8fbbb0, water: 0x549d9b, pink: 0xce6688, yellow: 0xe7ba4b, blue: 0x426b9a, red: 0xb44630, purple: 0x92789f, slate: 0x65574b };
  type MaterialName = keyof typeof colors;
  const materials = Object.fromEntries(Object.entries(colors).map(([name, color]) => [name, new THREE.MeshStandardMaterial({ name, color, roughness: name === "glass" || name === "water" ? .18 : .78, metalness: name === "steel" ? .45 : .02, transparent: name === "glass", opacity: name === "glass" ? .36 : 1, depthWrite: name !== "glass", side: THREE.DoubleSide })])) as Record<MaterialName, THREE.MeshStandardMaterial>;
  const cube = new THREE.BoxGeometry(1, 1, 1);
  function mesh(geometry: THREE.BufferGeometry, material: MaterialName, x: number, y: number, z: number, parent = architecture, label = "Chi tiết kiến trúc") {
    const object = new THREE.Mesh(geometry, materials[material]);
    object.position.set(x, y, z); object.castShadow = material !== "glass" && material !== "water"; object.receiveShadow = true;
    if (parent !== landscape) object.userData.label = label;
    parent.add(object); return object;
  }
  function box(w: number, h: number, d: number, x: number, y: number, z: number, mat: MaterialName = "white", parent = architecture, label = "Tường và mặt phẳng") {
    const object = mesh(cube, mat, x, y, z, parent, label); object.scale.set(w, h, d); return object;
  }
  function cylinder(radius: number, height: number, x: number, y: number, z: number, mat: MaterialName, parent = structure, label = "Cột và chi tiết tròn") {
    return mesh(new THREE.CylinderGeometry(radius, radius, height, 16), mat, x, y, z, parent, label);
  }
  function tree(x: number, z: number, height = 2.4, foliage: MaterialName = "green") {
    cylinder(.075, height * .75, x, height * .38, z, "wood", landscape);
    for (let i = 0; i < 4; i++) {
      const crown = mesh(new THREE.IcosahedronGeometry(.58, 2), foliage, x + Math.sin(i * 2.4) * .34, height * .64 + i * .18, z + Math.cos(i * 2.4) * .3, landscape);
      crown.scale.set(1, 1.15, .95);
    }
  }
  function glass(w: number, h: number, x: number, y: number, z: number, frame: MaterialName = "dark", count = 5) {
    box(w, h, .045, x, y, z, "glass", architecture, "Vách kính");
    for (let i = 0; i <= count; i++) box(.045, h + .06, .07, x - w / 2 + i * w / count, y, z + .025, frame, structure, "Khung cửa");
    for (const dy of [-h / 2, h / 2]) box(w, .045, .07, x, y + dy, z + .025, frame, structure, "Khung cửa");
  }
  function railing(w: number, x: number, y: number, z: number, mat: MaterialName = "white") {
    for (const dy of [0, .45]) box(w, .035, .035, x, y + dy, z, mat, structure, "Lan can");
    for (let i = 0; i <= 8; i++) box(.025, .48, .025, x - w / 2 + w * i / 8, y + .22, z, mat, structure, "Lan can");
  }
  function furniture(x: number, y: number, z: number) {
    box(1.5, .3, .62, x, y + .2, z, "cream", architecture, "Ghế và nội thất");
    box(1.5, .4, .16, x, y + .5, z - .25, "wood", architecture, "Ghế và nội thất");
    for (const dx of [-.65, .65]) box(.08, .22, .42, x + dx, y + .08, z, "dark", architecture, "Ghế và nội thất");
    box(.85, .06, .5, x + .12, y + .25, z + .9, "wood", architecture, "Bàn");
    cylinder(.14, .22, x + .12, y + .12, z + .9, "dark", architecture, "Bàn");
  }
  function pavilion(x: number, z: number, w: number, d: number, base: number, height: number, frame: MaterialName = "dark") {
    box(w + .3, .22, d + .3, x, base, z, "cream", structure, "Sàn nhà");
    glass(w, height, x, base + height / 2 + .1, z + d / 2, frame, Math.round(w));
    glass(w, height, x, base + height / 2 + .1, z - d / 2, frame, Math.round(w));
    for (const dx of [-w / 2, w / 2]) {
      box(.045, height, d, x + dx, base + height / 2 + .1, z, "glass", architecture, "Vách kính");
      for (const dz of [-d / 2, d / 2]) box(.1, height + .2, .1, x + dx, base + height / 2, z + dz, frame, structure, "Cột thép");
    }
    box(w + .5, .19, d + .5, x, base + height + .22, z, frame === "white" ? "white" : "cream", roof, "Mặt phẳng mái");
    box(w + .52, .045, d + .52, x, base + height + .12, z, frame, roof, "Diềm mái");
    furniture(x, base + .13, z - .5);
  }
  function pool(w: number, d: number, x: number, z: number) {
    box(w + .36, .1, d + .36, x, .035, z, "cream", landscape);
    box(w, .06, d, x, .1, z, "water", landscape);
    for (let i = 1; i < 8; i++) box(w * .8, .006, .018, x, .134, z - d / 2 + i * d / 8, "glass", landscape);
  }
  function steps(x: number, z: number, w: number, count: number, rise = .17, depth = .28, mat: MaterialName = "cream") {
    for (let i = 0; i < count; i++) box(w, (i + 1) * rise, depth, x, (i + 1) * rise / 2, z - i * depth, mat, structure, "Cầu thang");
  }
  function gable(w: number, d: number, x: number, y: number, z: number, rise: number, mat: MaterialName = "slate") {
    const positions = new Float32Array([-w/2,0,-d/2,w/2,0,-d/2,0,rise,-d/2,-w/2,0,d/2,0,rise,d/2,w/2,0,d/2,-w/2,0,-d/2,0,rise,-d/2,0,rise,d/2,-w/2,0,-d/2,0,rise,d/2,-w/2,0,d/2,w/2,0,-d/2,w/2,0,d/2,0,rise,d/2,w/2,0,-d/2,0,rise,d/2,0,rise,-d/2]);
    const geometry = new THREE.BufferGeometry(); geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3)); geometry.computeVertexNormals();
    return mesh(geometry, mat, x, y, z, roof, "Mái dốc");
  }
  mesh(new RoundedBoxGeometry(12, .48, 9, 2, .16), "cream", 0, -.35, 0, landscape);
  box(11.65, .08, 8.65, 0, -.08, 0, variant === "malaparte" ? "water" : "sage", landscape);
  box(9.4, .04, 7.2, 0, -.015, 0, "soil", landscape);

  if (variant === "fallingwater") {
    pool(11.2, 2.3, 0, 2.9);
    for (const [x,y,z,s] of [[-3,.35,1,1.6],[3,.4,1.8,1.5],[-1,.2,3.5,1.1],[4,.1,3.5,.7]]) {
      const rock = mesh(new THREE.IcosahedronGeometry(1, 0), "stone", x,y,z,landscape); rock.scale.set(s,.5,s*.75);
    }
    box(2.1, 5.2, 2.2, -.8, 2.65, -.75, "stone", structure, "Lõi đá tự nhiên");
    for (let i = 0; i < 28; i++) box(2.13, .035, 2.23, -.8, .2 + i*.18, -.75, i%3 ? "stone" : "cream", structure, "Các lớp đá");
    box(8.6, .24, 5, .2, 1.23, .1, "cream", structure, "Bản sàn vươn");
    glass(5.9, 1.62, 1, 2.2, 1.15, "red", 7);
    box(6.2, .16, 3.2, .8, 3.15, -.15, "cream", structure, "Bản sàn vươn");
    box(6.4, .52, .19, .9, 1.6, 2.55, "cream", architecture, "Lan can đặc");
    box(.2, .52, 3.2, 4.3, 1.6, .96, "cream", architecture, "Lan can đặc");
    glass(3.4, 1.25, .5, 3.9, -.2, "red", 4);
    box(5.8, .17, 3.3, .7, 4.68, -.5, "cream", roof, "Mái tầng trên");
    box(4.8, .38, .17, 1.4, 3.42, 1.48, "cream", architecture, "Hiên tầng trên");
    box(1.9, .15, 2, -1, 5, -.9, "cream", roof, "Mái trên lõi đá");
    for (let i = 0; i < 9; i++) box(.17, .35 + (i%3)*.12, .1, 1.8+i*.21, -.15, 4.08, "glass", landscape);
    furniture(1.2, 1.4, -.1); tree(-4.8,-2.5,3.6); tree(4.6,-2.6,3.2);
  } else if (variant === "savoye") {
    box(7.2, .22, 5, 0, 2.15, 0, "white", structure, "Sàn trên pilotis");
    for (const x of [-3,0,3]) for (const z of [-1.85,1.85]) cylinder(.105,2.15,x,1.05,z,"white",structure,"Hệ cột pilotis");
    box(2.9, 1.7, 2.8, -.8, .85, -.5, "sage", architecture, "Khối tầng trệt");
    for (const z of [-2.4,2.4]) {
      box(7.1, .65, .14, 0, 2.65, z, "white"); glass(6.8,.73,0,3.34,z+.015,"dark",9); box(7.1,.4,.14,0,3.91,z,"white");
    }
    for (const x of [-3.5,3.5]) box(.15,1.8,4.7,x,3.12,0,"white");
    box(7.2,.18,5,0,4.15,0,"white",roof,"Toit-terrasse");
    const curve = mesh(new THREE.CylinderGeometry(1.35,1.35,.9,32,1,true,0,Math.PI*1.5),"white",.3,4.68,-.6,roof,"Tường cong trên sân mái"); curve.rotation.y=.6;
    box(2,.85,.15,-2,4.65,-1.6,"white",roof,"Sân mái");
    const ramp=box(1,.13,4.8,.4,1.12,.4,"cream",structure,"Đường dốc"); ramp.rotation.x=-.39;
    tree(-4.8,-2.8,2.7); tree(4.8,2.5,2.2); steps(2.4,3,1.6,3,.09);
  } else if (variant === "farnsworth" || variant === "glass") {
    const white = variant === "farnsworth";
    pavilion(0,-.4,7.5,3.7,white?1.1:.3,2.6,white?"white":"dark");
    if (white) {
      box(6,.18,2.25,-.65,.5,2.4,"white",structure,"Sân hiên nổi"); steps(-1.8,3.8,2,4,.14,.35);
      for (const x of [-3.5,-1.2,1.2,3.5]) for (const z of [-2.25,1.45]) box(.11,3.95,.11,x,1.9,z,"white",structure,"Cột thép chữ I");
      box(2.1,2.2,.7,.4,2.3,-.8,"wood",architecture,"Lõi nội thất gỗ");
    } else {
      cylinder(.72,3.7,1.5,2,-1,"brick",architecture,"Lõi gạch tròn");
      for (let i=0;i<8;i++) box(.7,.035,.4,-3+i*.85,.05,2.8,"cream",landscape);
    }
    tree(-4.9,-2.6,3.7); tree(4.7,2.4,3); tree(4.4,-3.2,2.6);
  } else if (variant === "tugendhat") {
    box(9,.14,6.1,0,.15,0,"cream",structure,"Nền sân vườn");
    pavilion(0,.5,8,3.7,.45,2.6,"steel");
    box(3.5,1.65,2.9,-1.9,4,-1.3,"white"); box(2.7,1.65,2.9,2.2,4,-1.3,"white");
    glass(7.2,.7,0,4.2,.18,"dark",9);
    box(8.5,.16,3.6,0,4.95,-1.2,"white",roof,"Mái biệt thự");
    box(8.8,.2,6,0,3.28,0,"white",structure,"Sân thượng"); railing(8,0,3.5,2.8,"steel");
    steps(-3.6,3.85,1.5,10,.28,.3); box(1.7,2,.12,.1,1.6,-.2,"yellow",architecture,"Vách nội thất");
    tree(4.9,-2.3,3); tree(-4.8,-3,3.3);
  } else if (variant === "eames") {
    const panels: MaterialName[]=["white","yellow","glass","blue","glass","red","white","glass","dark","glass","white","glass"];
    for (const x of [-2.2,2.2]) {
      box(3.3,.2,4.4,x,.16,0,"cream",structure,"Sàn khung mô-đun");
      box(3.3,.14,4.4,x,2.35,0,"dark",structure,"Sàn gác");
      for (let c=0;c<3;c++) for(let r=0;r<4;r++) box(1.02,1.02,.06,x-1.1+c*1.1,.8+r*1.06,2.18,panels[r*3+c],architecture,"Mảng màu và kính");
      for (let c=0;c<=3;c++) box(.065,4.5,.12,x-1.65+c*1.1,2.35,2.22,"dark",structure,"Lưới thép mô-đun");
      for(let r=0;r<=4;r++) box(3.35,.07,.12,x,.28+r*1.06,2.22,"dark",structure,"Lưới thép mô-đun");
      for(const dx of [-1.65,1.65]) box(.1,4.5,4.4,x+dx,2.35,0,"dark",structure,"Khung thép biên");
      box(3.5,.17,4.65,x,4.65,0,"dark",roof,"Mái hai khối nhà"); furniture(x,.3,-.4);
    }
    box(1.2,.08,5.4,0,.08,.1,"wood",landscape); tree(-4.8,-2.9,4.2);tree(.1,-3.2,4.7);tree(4.9,-2.6,4);
  } else if (variant === "stahl") {
    pavilion(.2,-1.8,8,2.6,.25,2.45,"dark"); pavilion(-2.65,1.15,2.4,3.3,.25,2.45,"dark");
    pool(4.3,3.4,1.45,1.5); box(2,.06,.8,3.4,.25,3.6,"wood",architecture,"Ghế ngoài hiên");
    for(const x of [-4.4,4.5]) {tree(x,-3,2.2);box(.25,.65,.25,x,.3,3,"cream",landscape);}
  } else if (variant === "robie") {
    box(8.5,1.5,4,0,.9,0,"brick");box(8.1,1.65,3.3,.5,2.65,-.2,"brick");
    for(const y of [.28,1.6,3.35])box(8.7,.08,4.15,.1,y,0,"cream",structure,"Băng đá ngang");
    for(let i=0;i<12;i++)glass(.49,1.05,-3.4+i*.65,2.7,1.48,"wood",1);
    for(const x of [-3,3]) box(1.2,.7,1.3,x,1.95,2.3,"brick",architecture,"Ban công gạch");
    gable(10,4.7,.45,3.58,-.2,.48);gable(9.6,5.1,0,1.8,0,.3);
    box(1.3,4.5,1.15,-1.4,2.25,-.6,"brick",architecture,"Ống khói gạch"); box(1.45,.14,1.3,-1.4,4.55,-.6,"cream",architecture,"Nắp ống khói");
    for(let i=0;i<10;i++)box(8.55,.018,.025,0,.32+i*.12,2.02,"stone",architecture,"Mạch gạch ngang");
    tree(-5,-2.8,2.8);tree(4.7,2.8,2.3);steps(.5,3.8,2.6,5,.19,.27);
  } else if (variant === "schroder") {
    box(5.9,2.05,3.9,0,1.1,-.3,"cream");box(5.9,.2,4.5,.2,2.2,.1,"white",structure,"Mặt phẳng sàn");
    glass(5.3,1.7,.2,3.2,1.95,"dark",6);box(.15,1.8,3.8,-2.7,3.2,.1,"white");
    box(6.6,.18,4.7,.2,4.22,-.1,"white",roof,"Mái De Stijl"); box(2.8,.16,2.1,1.6,2.2,2,"white",structure,"Sàn ban công");
    box(.15,4.2,.16,2.75,2.15,2.8,"red",structure,"Thanh màu cơ bản");box(4.6,.12,.18,.9,2.8,2.8,"dark",structure,"Thanh ngang đen");
    box(.16,2.1,.16,-2.2,3.2,2.65,"blue",structure,"Thanh màu cơ bản");box(2,.18,.18,-2.1,4.27,1.4,"yellow",roof,"Thanh màu cơ bản");
    box(1.65,1.2,.15,1.85,3.5,-1.9,"white"); furniture(0,2.35,-.3);tree(-4.6,-2.9,3.2); tree(4.7,-2.7,2.8);
  } else if (variant === "malaparte") {
    const rock=mesh(new THREE.IcosahedronGeometry(1,1),"stone",0,.2,-.1,landscape);rock.scale.set(4.3,.7,4);
    box(4.2,2.7,5.7,0,2,-.55,"red");box(4.35,.16,5.9,0,3.42,-.55,"red",roof,"Sân mái đỏ");
    for(let i=0;i<17;i++)box(2.3+i*.095,(i+1)*.2,.22,0,(i+1)*.1+.1,3.9-i*.19,"red",structure,"Thang lớn lên sân mái");
    for(const x of [-2.11,2.11])for(const z of [-2,-.4,1.05])box(.03,.65,.52,x,2.1,z,"dark",architecture,"Ô cửa trên vách đỏ");
    const screen=mesh(new THREE.CylinderGeometry(1,1,1.1,24,1,true,0,Math.PI),"white",.1,4.05,-2.3,roof,"Tường chắn gió cong"); screen.rotation.y=Math.PI;
    for(let i=0;i<12;i++)box(.11,.03,.85,-5+i*.9,.02,-3.7,"glass",landscape);
  } else if (variant === "carre") {
    pavilion(0,0,7.9,4.1,.4,2.5,"wood");box(2.5,2.5,4,-2.8,1.8,0,"white");
    box(1.7,3.3,1.2,.4,1.95,-1.1,"white",architecture,"Lõi gạch trắng");
    const slope=box(8.5,.19,4.8,.2,3.2,0,"slate",roof,"Mái dốc Aalto");slope.rotation.z=-.12;
    box(2.6,.12,4.65,-3.1,3.7,0,"slate",roof,"Mái khối cao");steps(1.2,3.9,4.5,4,.12,.35);
    for(let i=0;i<12;i++)box(.1,2,.07,-1.7+i*.32,1.7,2.12,"wood",architecture,"Nhịp gỗ mặt đứng");
    tree(-4.9,-2.7,3.4);tree(4.7,-2.8,3.1);tree(4.8,2.9,2);
  } else if (variant === "barragan") {
    box(4.9,3.65,3.8,-.8,1.85,-.6,"stone");box(2.7,2.65,3.8,2.9,1.35,-.6,"pink");
    box(5.05,.18,3.95,-.8,3.75,-.6,"cream",roof,"Sân mái");box(2.85,.18,3.95,2.9,2.78,-.6,"cream",roof,"Mái khối vườn");
    box(5.1,1.1,.15,-.8,4.35,-2.5,"pink",architecture,"Mặt phẳng màu trên mái");box(.15,1.6,3.9,-3.3,4.1,-.6,"yellow",architecture,"Tường đón nắng");
    box(.95,1.9,.045,-1.7,1,1.32,"dark",architecture,"Cửa vào");box(1.4,1.6,.05,.5,2.15,1.33,"glass",architecture,"Ô cửa vườn");
    steps(-3.8,3.5,.95,12,.25,.23,"cream");box(5.5,1.25,.15,1.15,.65,3.4,"pink",architecture,"Tường sân vườn");
    tree(2.5,2.2,2.7);tree(-4.8,-2.9,3.4); furniture(2.5,.2,2.2);
  } else if (variant === "gilardi") {
    box(3.1,4.3,4.4,-2.5,2.2,-.2,"pink");box(3.5,2.8,2.3,1.5,1.45,-1.25,"cream");
    box(3.35,.17,4.65,-2.5,4.45,-.2,"white",roof,"Mái nhà màu hồng");box(3.7,.17,2.5,1.5,2.96,-1.25,"pink",roof,"Mái khối sân trong");
    box(.14,2.8,4.8,-.85,1.45,.3,"yellow",architecture,"Hành lang vàng");pool(3.3,3.3,1.6,1.4);
    box(.22,2.6,2.5,2.3,1.5,1.2,"red",architecture,"Mảng đỏ bên mặt nước");box(3.4,2.7,.15,1.5,1.45,3.15,"blue",architecture,"Vách xanh");
    for (let i=0;i<7;i++)box(.08,1.9,.08,-.72,1.3,-1.7+i*.62,"cream",structure,"Nhịp hành lang");
    glass(2.2,1.3,-2.5,2.7,2.02,"dark",3);tree(3.9,-2.6,3.8,"purple");tree(-4.9,2.9,2.3);
  } else if (variant === "red-house") {
    box(5.6,3.15,3.2,.6,1.65,-.6,"brick");box(2.9,3.15,5.8,-2.4,1.65,.6,"brick");
    gable(6.15,3.8,.6,3.22,-.6,1.65);const cross=gable(3.5,6.35,-2.4,3.22,.6,1.5);cross.rotation.y=0;
    for(const y of [1,2.4])for(const x of [-2.7,-1,1,2.7])glass(.55,.8,x,y,x<-2?3.53:1.03,"cream",2);
    for(const x of [-1.8,1.6]){box(.6,2.4,.6,x,4.15,-.6,"brick",architecture,"Ống khói gạch");box(.75,.12,.75,x,5.4,-.6,"cream",architecture,"Nắp ống khói");}
    cylinder(.55,.75,2.5,.5,3.1,"brick",architecture,"Giếng sân vườn");mesh(new THREE.ConeGeometry(.88,.9,6),"slate",2.5,1.9,3.1,roof,"Mái giếng");
    for (const x of [2.08,2.92])box(.07,1.05,.07,x,1.15,3.1,"wood",structure,"Cột giếng");
    tree(-4.9,-2.8,3.3);tree(4.6,-2.8,3.5);tree(4.8,3,2.2);
  }
  if (variant !== "malaparte") for (let i=0;i<6;i++) box(.58,.035,.33,-2.1+i*.84,.025,4,"cream",landscape);
  const components = new Map<string, THREE.Object3D>();
  for (const group of [architecture, structure, roof]) group.traverse(object => { if (object.userData.label && !components.has(object.userData.label)) components.set(object.userData.label, object); });
  function dispose() {
    const geometries=new Set<THREE.BufferGeometry>(), ownedMaterials=new Set<THREE.Material>();
    root.traverse(object=>{if(object instanceof THREE.Mesh){geometries.add(object.geometry);for(const material of Array.isArray(object.material)?object.material:[object.material])ownedMaterials.add(material);}});
    for(const geometry of geometries)geometry.dispose();for(const material of Object.values(materials))ownedMaterials.add(material);for(const material of ownedMaterials)material.dispose();
  }
  return {root,roof,architecture,structure,components:[...components.keys()],find:(label:string)=>components.get(label),dispose};
}

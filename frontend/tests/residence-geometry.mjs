import assert from 'node:assert/strict';
import {models,screenModels} from '../src/models.ts';

assert.equal(models.length,14,'Replace the four generic models with the residence collection.');
assert.equal(new Set(models.map(m=>m.id)).size,14);
assert.equal(new Set(Object.values(screenModels)).size,14,'Each screen needs its own residence.');
for(const id of Object.values(screenModels)) assert.ok(models.some(m=>m.id===id));
const {createResidence}=await import('../src/residence-geometry.ts');
const THREE=await import('three');
const signatures=[];
for(const model of models) {
  const home=createResidence(model.id);
  const bounds=new THREE.Box3().setFromObject(home.root);
  const size=bounds.getSize(new THREE.Vector3());
  assert.ok(size.x>3 && size.x<20 && size.y>1 && size.y<12 && size.z>3 && size.z<20,model.id);
  assert.ok(home.roof.children.length>0,`Roof separation: ${model.id}`);
  let meshes=0,triangles=0;
  const geometry=[];
  home.root.traverse(object=>{
    if(!object.isMesh) return;
    meshes++;
    const positions=object.geometry.getAttribute('position');
    assert.ok(Array.from(positions.array).every(Number.isFinite),model.id);
    triangles+=(object.geometry.index?.count ?? positions.count)/3;
    geometry.push([object.geometry.type,...object.position.toArray(),...object.scale.toArray()]);
  });
  assert.ok(meshes>35 && meshes<700,`${model.id}: ${meshes} meshes`);
  assert.ok(triangles<100000,`${model.id}: ${triangles} triangles`);
  assert.ok(home.components.length>3,model.id);
  signatures.push(JSON.stringify(geometry));
  home.dispose();
}
assert.equal(new Set(signatures).size,14,'All homes must have distinct geometry.');
console.log('PASS: 14 distinct residences, 14 screen assignments, finite bounded geometry, roof groups, component labels and laptop mesh budget.');

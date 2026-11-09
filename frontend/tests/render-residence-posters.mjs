import {chromium} from '@playwright/test';
import {mkdir,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import assert from 'node:assert/strict';

const output=resolve('frontend/public/images/residences');
await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
const page=await browser.newPage({viewport:{width:1100,height:850},reducedMotion:'reduce'});
try {
  await page.goto('http://127.0.0.1:1420/');
  const ids=await page.evaluate(async()=>{
    const {models}=await import('/src/models.ts');return models.map(home=>home.id);
  });
  for(const id of ids) {
    const data=await page.evaluate(async id=>{
      const {createResidenceStage}=await import('/src/residence-stage.ts');
      const mount=document.createElement('div');mount.style.cssText='position:fixed;inset:0;width:960px;height:660px;z-index:9999;background:#eee7d8';document.body.appendChild(mount);
      const scene=createResidenceStage(mount,id,()=>{},()=>{},()=>{});
      try {await new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done)));return scene.capture();}
      finally {scene.dispose();mount.remove();}
    },id);
    assert.ok(data.startsWith('data:image/webp;base64,'));
    const bytes=Buffer.from(data.split(',')[1],'base64');assert.ok(bytes.length>1000,id);
    await writeFile(resolve(output,`${id}.webp`),bytes);
  }
  console.log(`Rendered ${ids.length} original WebP posters from the same Three.js geometry used by the app.`);
}finally{await browser.close();}

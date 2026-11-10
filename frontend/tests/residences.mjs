import {chromium,expect} from '@playwright/test';
import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {signIn} from './account-helper.mjs';
import {models,screenModels} from '../src/models.ts';

assert.equal(process.env.BIM_UI_TEST,'1');
const output=resolve(`data/artifacts/residences-090/browser-${Date.now()}`);await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const errors=[];page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
await page.addInitScript(()=>{
  window.__residenceDraws=0;
  for(const type of [window.WebGLRenderingContext,window.WebGL2RenderingContext]) {
    if(!type)continue;
    for(const name of ['drawElements','drawArrays']) {
      const original=type.prototype[name];
      type.prototype[name]=function(...args){window.__residenceDraws++;return original.apply(this,args);};
    }
  }
});
const tick=ms=>page.waitForTimeout(ms);
const drawCount=()=>page.evaluate(()=>window.__residenceDraws);
try {
  await page.goto('http://127.0.0.1:1420/');
  const scene=page.locator('.account-residence .residence');
  await expect(scene).toHaveAttribute('data-residence','fallingwater');
  await expect(scene).toHaveAttribute('data-render-mode','webgl');await expect(scene.locator('canvas')).toBeVisible();
  await expect(page.locator('.residence-tools')).toHaveCount(0);
  await scene.locator('canvas').focus();await page.keyboard.press('Space');await tick(350);
  const still=await scene.locator('canvas').screenshot();await tick(350);
  assert.equal(still.equals(await scene.locator('canvas').screenshot()),true,'Paused geometry stays still.');
  await page.keyboard.press('Space');
  const moving=await scene.locator('canvas').screenshot();await tick(600);
  assert.equal(moving.equals(await scene.locator('canvas').screenshot()),false,'Autoplay rotates actual rendered geometry.');
  await page.getByLabel('Tên đăng nhập',{exact:true}).fill('uiadmin');
  await expect(scene).toHaveAttribute('data-motion','paused');await tick(350);
  const focusedDraws=await drawCount();await tick(350);assert.equal(await drawCount(),focusedDraws,'Typing does not keep a render loop alive.');
  await page.locator('.account-story h1').click();
  await expect(scene).toHaveAttribute('data-motion','playing');
  await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));});
  await tick(200);const hiddenDraws=await drawCount();await tick(350);assert.equal(await drawCount(),hiddenDraws,'Hidden document signal stops GPU drawing.');
  await page.evaluate(()=>{delete document.hidden;document.dispatchEvent(new Event('visibilitychange'));});await tick(250);
  assert.ok(await drawCount()>hiddenDraws,'Visible document resumes drawing.');
  await page.emulateMedia({reducedMotion:'reduce'});await expect(scene).toHaveAttribute('data-motion','paused');
  await scene.locator('canvas').focus();await page.keyboard.press('ArrowRight');await expect(scene).toHaveAttribute('data-motion','paused');
  await page.screenshot({path:resolve(output,'login-desktop.png'),fullPage:true});
  await page.getByRole('button',{name:'Chuyển sang đăng ký',exact:true}).click();
  await expect(scene).toHaveAttribute('data-residence','savoye');
  await expect(page.getByLabel('Tên hiển thị',{exact:true})).toBeVisible();
  await page.screenshot({path:resolve(output,'register-desktop.png'),fullPage:true});
  await page.setViewportSize({width:375,height:812});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.screenshot({path:resolve(output,'register-375.png'),fullPage:true});
  await page.evaluate(()=>window.scrollTo(0,0));await tick(350);const offscreenDraws=await drawCount();await tick(350);assert.equal(await drawCount(),offscreenDraws);
  await page.setViewportSize({width:1440,height:1000});
  await page.getByRole('button',{name:'Về đăng nhập',exact:true}).click();
  await page.emulateMedia({reducedMotion:'no-preference'});
  await signIn(page);
  await expect(page.locator('.work-page-residence .residence')).toHaveAttribute('data-residence','glass');
  await page.locator('.work-personal-nav>summary').click();
  const surfaces=[['Kiểm tra hồ sơ','inspection'],['Thư viện bản vẽ','drawings'],['Mô hình minh họa','models'],['Sổ tay dự án','notes'],['Tài khoản và phân quyền','accounts'],['Tài khoản của tôi','account']];
  for(const [label,id] of surfaces) {
    await page.getByRole('button',{name:label,exact:true}).click();
    await expect(page.locator('.work-page-residence .residence')).toHaveAttribute('data-residence',screenModels[id]);
    if(id==='models') {
      await expect(page.locator('.work-model-grid>button')).toHaveCount(14);
      for(const home of models)assert.equal(await page.locator(`.work-model-grid img[src="${home.image}"]`).count(),1);
      await page.locator('.work-model-grid>button').filter({has:page.getByRole('heading',{name:'Farnsworth House',exact:true})}).click();
      const dialog=page.getByRole('dialog');await expect(dialog.locator('.residence')).toHaveAttribute('data-render-mode','webgl');
      await dialog.getByRole('button',{name:'Mặt đứng',exact:true}).click();
      await dialog.getByRole('button',{name:'Tách mái',exact:true}).click();await tick(700);
      await dialog.screenshot({path:resolve(output,'farnsworth-roof-elevation.png')});
      await expect(dialog.getByRole('button',{name:'Ghép mái',exact:true})).toHaveAttribute('aria-pressed','true');
      await dialog.locator('canvas').focus();await page.keyboard.press('Home');
      await expect(dialog.getByRole('button',{name:'Phối cảnh',exact:true})).toHaveAttribute('aria-pressed','true');
      await dialog.getByRole('button',{name:'Ghép mái',exact:true}).click();await tick(650);
      await dialog.getByRole('button',{name:'Khung dây',exact:true}).click();await expect(dialog.getByRole('button',{name:'Khung dây',exact:true})).toHaveAttribute('aria-pressed','true');
      await dialog.getByLabel('Chọn cấu kiện').selectOption({index:1});await expect(dialog.locator('.residence-selection')).not.toBeEmpty();
      await page.keyboard.press('Escape');
    }
  }
  for(const [username,variant] of [['uiteacher','tugendhat'],['uistudent','eames'],['uiuser','stahl']]) {
    await page.getByRole('button',{name:'Đăng xuất',exact:true}).click();await signIn(page,username);
    await expect(page.locator(username==='uiuser'?'.work-hero .residence':'.work-page-residence .residence')).toHaveAttribute('data-residence',variant);
    if(username==='uiteacher') {await page.locator('.work-personal-nav>summary').click();await page.getByRole('button',{name:'Hồ sơ được chia sẻ',exact:true}).click();await expect(page.locator('.work-page-residence .residence')).toHaveAttribute('data-residence','schroder');await page.getByRole('button',{name:'Tổng quan giảng dạy',exact:true}).click();}
    await page.screenshot({path:resolve(output,`${username}-desktop.png`),fullPage:true});
  }
  for(const width of [375,561,640,768,801,850,870,900]) {
    await page.setViewportSize({width,height:900});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`No overflow at ${width}`);
    await expect(page.locator('.residence-tools')).toHaveCount(0);
  }
  await page.setViewportSize({width:1440,height:1000});
  const hero=page.locator('.work-hero .residence');
  await hero.locator('canvas').evaluate(canvas=>canvas.getContext('webgl2').getExtension('WEBGL_lose_context').loseContext());
  await expect(hero).toHaveAttribute('data-render-mode','poster');
  await expect(hero.locator('.residence-fallback img')).toBeVisible();assert.equal(await hero.locator('.residence-fallback img').evaluate(img=>img.complete&&img.naturalWidth>0),true);
  await page.screenshot({path:resolve(output,'webgl-fallback.png')});
  assert.deepEqual(errors,[]);
  const result={status:'passed',output,homes:14,checks:['auth screen changes residence','real 3D animation and keyboard pause','typing stops rendering','simulated visibilitychange stops/resumes GPU','reduced motion','375px auth','6 page residences and teacher sharing','4 dashboard residences','14 gallery posters','roof elevation and keyboard Home','wireframe/component selection','375/561/640/768/801/850/870/900 no overflow or floating toolbar','real WebGL context-loss poster fallback','no runtime/console errors']};
  await writeFile(resolve(output,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}catch(error){await page.screenshot({path:resolve(output,'failure.png'),fullPage:true}).catch(()=>{});throw error;}finally{await browser.close();}

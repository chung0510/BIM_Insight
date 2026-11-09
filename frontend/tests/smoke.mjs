import { chromium, expect } from '@playwright/test';
import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { signIn } from './account-helper.mjs';

const output = resolve(`data/artifacts/rbac-080/workspace-${Date.now()}`);
await mkdir(output, {recursive:true});
const browser = await chromium.launch({headless:true, executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
const page = await browser.newPage({viewport:{width:1440,height:1000}});
const errors=[];
page.on('pageerror', e=>errors.push(e.message));
page.on('console', m=>{if(m.type()==='error') errors.push(m.text());});
try {
  await page.goto('http://127.0.0.1:1420/');
  await signIn(page);
  await expect(page.getByRole('heading',{name:'Không gian quản trị BIM',exact:true})).toBeVisible();
  await page.screenshot({path:resolve(output,'desktop.png'),fullPage:true});
  await page.getByRole('button',{name:'Thư viện bản vẽ',exact:true}).click();
  await expect(page.locator('.drawing-card')).toHaveCount(8);
  for(const category of ['Kiến trúc','Kết cấu','Cơ điện','Phối cảnh 3D']) {
    await page.getByRole('button',{name:category,exact:true}).click();
    await expect(page.locator('.drawing-card')).toHaveCount(2);
  }
  await page.getByRole('button',{name:'Kiến trúc',exact:true}).click();
  await page.getByRole('button',{name:'Xem bản vẽ: Mặt bằng tầng 1',exact:true}).click();
  const sheet=page.locator('.drawing-viewport svg');
  const width=await sheet.evaluate(e=>e.getBoundingClientRect().width);
  await page.getByRole('button',{name:'Phóng to bản vẽ',exact:true}).click();
  assert.ok(await sheet.evaluate(e=>e.getBoundingClientRect().width)>width);
  const download=page.waitForEvent('download');
  await page.getByRole('button',{name:'Tải bản vẽ SVG',exact:true}).click();
  const file=await download;
  assert.equal(file.suggestedFilename(),'KT-01.svg');
  assert.ok((await readFile(await file.path(),'utf8')).includes('MẶT BẰNG TẦNG 1'));
  await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'Mô hình minh họa',exact:true}).click();
  await page.locator('.work-model-grid>button').first().click();
  const viewer=page.getByRole('dialog');
  await viewer.locator('canvas').waitFor();
  const before=await viewer.locator('canvas').screenshot();
  await viewer.locator('canvas').focus();await page.keyboard.press('ArrowRight');
  assert.equal(before.equals(await viewer.locator('canvas').screenshot()),false);
  await viewer.getByRole('button',{name:'Tách mái',exact:true}).click();
  await expect(viewer.getByRole('button',{name:'Ghép mái',exact:true})).toHaveAttribute('aria-pressed','true');
  await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'Sổ tay dự án',exact:true}).click();
  await page.getByLabel('Nội dung ghi chú').fill('Kiểm tra nguồn IFC và cao độ tầng.');
  await page.getByRole('button',{name:'Lưu sổ tay',exact:true}).click();
  await page.reload(); await signIn(page);
  await expect(page.getByLabel('Nội dung ghi chú')).toHaveValue('Kiểm tra nguồn IFC và cao độ tầng.');
  for(const viewport of [{width:375,height:812},{width:768,height:1024},{width:812,height:375}]) {
    await page.setViewportSize(viewport);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  }
  await page.setViewportSize({width:375,height:812});
  await expect(page.getByRole('navigation')).not.toBeVisible();
  await page.getByRole('button',{name:'Mở menu',exact:true}).click();
  await page.getByRole('button',{name:'Tổng quan',exact:true}).click();
  await page.screenshot({path:resolve(output,'mobile.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  await writeFile(resolve(output,'result.json'),JSON.stringify({status:'passed',checks:['dashboard','drawing categories and SVG export','3D rotate and roof','account-scoped notebook reload','375/768/812 layout','hidden mobile navigation','console'],output},null,2));
  console.log(JSON.stringify({status:'passed',output}));
} finally {await browser.close();}

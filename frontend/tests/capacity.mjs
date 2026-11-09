import { chromium, expect } from '@playwright/test';
import assert from 'node:assert/strict';
import {execFile, spawn} from 'node:child_process';
import {promisify} from 'node:util';
import {mkdir, readFile, realpath, rm} from 'node:fs/promises';
import {resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {createServer} from 'vite';
import {signIn, openTestProject, cleanLocalTestDatabase, downloadClashReport} from './account-helper.mjs';

// Browser plugin not available; regular Playwright verifies the local app.
const database = `bim_insight_test_capacity_${Date.now()}`;
const directory = resolve(`.local/${database}`);
await mkdir(directory, {recursive:true});
const env = {...process.env, BIM_UI_TEST:'1', BIM_MONGODB_URI:'mongodb://127.0.0.1:27017', BIM_DATABASE:database, BIM_DATA_DIR:resolve(directory,'data'), PYTHONPATH:resolve('backend')};
process.env.BIM_UI_TEST = '1';
const backend = spawn(resolve('.venv/Scripts/python.exe'), ['-m','app','--desktop','--parent-pid',String(process.pid)], {windowsHide:true, env, stdio:['ignore','pipe','pipe']});
let browser, server;
backend.stderr.on('data', ()=>{});
try {
  const connection = await new Promise((done, reject) => {
    const lines=createInterface({input:backend.stdout});
    const timeout=setTimeout(()=>reject(new Error('Local capacity backend startup timed out')),30000);
    lines.once('line',line=>{clearTimeout(timeout);try{done(JSON.parse(line));}catch{reject(new Error('Invalid local test connection'));}});
    lines.once('close',()=>{clearTimeout(timeout);reject(new Error('Local test backend stopped'));});
  });
  assert.match(connection.base_url,/^http:\/\/127\.0\.0\.1:\d+$/);
  assert.ok(connection.token.length>=32);
  server=await createServer({root:resolve('frontend'),cacheDir:resolve(directory,'vite-cache'),configFile:resolve('frontend/vite.config.ts'),server:{host:'127.0.0.1',port:0,proxy:{'/api':{target:connection.base_url,changeOrigin:true,headers:{Authorization:`Bearer ${connection.token}`,Origin:'http://127.0.0.1:1420'}}}}});
  await server.listen();
  const base=`http://127.0.0.1:${server.httpServer.address().port}`;
  await promisify(execFile)(resolve('.venv/Scripts/python.exe'), ['backend/tests/capacity_fixtures.py', resolve(directory,'inputs')], {env, windowsHide:true});
  browser = await chromium.launch({headless:true, executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
  const page = await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[];
  page.on('pageerror', error=>errors.push(error.message));
  await page.goto(`${base}/#inspection`);
  const session=await signIn(page);
  await openTestProject(page, 'Capacity regression only');
  const health = await page.request.get(`${base}/api/health`).then(response=>response.json());
  assert.equal(health.processing_limits.queue_files,200);
  assert.equal(health.file_limits.ifc,2*1024**3);
  await expect(page.locator('.inspection-dropzone')).toContainText('200 tệp');
  const inputs = [...Array.from({length:6},(_,i)=>`CAPACITY_${String(i+1).padStart(2,'0')}.ifc`), ...Array.from({length:7},(_,i)=>`DRAWING_${String(i+1).padStart(2,'0')}.pdf`)];
  await page.getByLabel('Chọn tệp IFC, PDF, DXF hoặc DWG').setInputFiles(inputs.map(name=>resolve(directory,'inputs',name)));
  await expect(page.locator('.inspection-file')).toHaveCount(13);
  await expect(page.locator('.inspection-file select')).toHaveCount(0);
  await page.getByRole('button',{name:'Bắt đầu kiểm tra',exact:true}).click();
  await expect(page.getByText('Đã xử lý 13/13 tệp',{exact:true})).toBeVisible({timeout:180000});
  console.log('Verified: 13 files imported and saved.');
  await expect(page.getByRole('checkbox',{name:/^Mở hồ sơ /})).toHaveCount(13);
  for (const checkbox of await page.getByRole('checkbox',{name:/^Mở hồ sơ /}).all()) await expect(checkbox).toBeChecked();
  await expect(page.getByRole('checkbox',{name:/^Kiểm tra va chạm /})).toHaveCount(6);
  await page.getByRole('checkbox',{name:'Tôi đã kiểm tra các IFC cùng công trình và hệ tọa độ'}).check();
  const clashButton = page.getByRole('button',{name:'Chạy kiểm tra va chạm',exact:true});
  await expect(clashButton).toBeEnabled();
  const responsePromise=page.waitForResponse(response=>response.url().endsWith('/api/inspections/clashes')&&response.request().method()==='POST',{timeout:180000});
  await clashButton.click();
  const clashResponse=await responsePromise;
  assert.equal(clashResponse.ok(),true);
  const clash=await downloadClashReport(page);
  assert.equal(clash.coverage.tested_elements,2204);
  assert.equal(clash.issues.length,1100);
  assert.equal(clash.verdict,'findings');
  console.log('Verified: 2204 elements and 1100 measured intersections across 6 IFC.');
  await expect(page.getByTestId('clash-row')).toHaveCount(1);
  const evidence=page.locator('.review-evidence-list');
  await expect(evidence.getByRole('button',{name:/^Bằng chứng \d+$/})).toHaveCount(0);
  await evidence.locator('summary').click();
  await expect(evidence.getByRole('button',{name:/^Bằng chứng \d+$/})).toHaveCount(100);
  await evidence.getByRole('button',{name:'100 bằng chứng tiếp',exact:true}).click();
  await expect(evidence.getByRole('button',{name:'Bằng chứng 101',exact:true})).toBeVisible();
  await expect(evidence.getByRole('button',{name:/^Bằng chứng \d+$/})).toHaveCount(100);
  await page.getByRole('checkbox',{name:'Gộp theo cặp nguồn/cấu kiện chính và loại đo'}).uncheck();
  await expect(page.getByTestId('clash-row')).toHaveCount(100);
  await page.getByRole('button',{name:'Xem thêm 100 cặp',exact:true}).click();
  await expect(page.getByTestId('clash-row')).toHaveCount(100);
  await expect(page.getByRole('navigation',{name:'Phân trang kết quả va chạm'})).toContainText('Trang 2/11');
  await page.getByRole('button',{name:'Xem kết quả CAPACITY_01.ifc',exact:true}).click();
  const detailsPromise=page.waitForEvent('download');
  await page.getByRole('button',{name:'Tải báo cáo JSON',exact:true}).click();
  const details=JSON.parse(await readFile(await (await detailsPromise).path(),'utf8'));
  assert.equal(details.result.elements.length,1100);
  assert.equal(details.result.elements_truncated,false);
  await expect(page.getByLabel('Tìm cấu kiện IFC',{exact:true})).toBeVisible();
  await expect(page.getByLabel('Chọn cấu kiện IFC',{exact:true}).locator('option')).toHaveCount(201);
  const guid=details.result.elements.at(-1).guid;
  await page.getByLabel('Tìm cấu kiện IFC',{exact:true}).fill(guid);
  await expect(page.getByLabel('Chọn cấu kiện IFC',{exact:true}).locator('option')).toHaveCount(2);
  await page.getByLabel('Chọn cấu kiện IFC',{exact:true}).selectOption(`${details.id}:${guid}`);
  await expect(page.getByTestId('ifc-selection')).toContainText(guid);
  console.log('Verified: bounded grouped and ungrouped pagination, complete downloads and IFC search.');
  for(let offset=1000;offset<1100;offset+=10){
    const updated=await Promise.all(clash.issues.slice(offset,offset+10).map(issue=>page.request.post(`${base}/api/projects/${clash.project_id}/runs/${clash.id}/issues/${issue.id}/review`,{headers:{'X-BIM-Session':session.session_token},data:{state:'needs_fix',reviewer:'Capacity regression',note:'Test only',expected_revision:0}})));
    for(const response of updated) assert.equal(response.ok(),true,await response.text());
  }
  const reloadReviews=page.waitForResponse(response=>response.url().endsWith('/reviews')&&response.request().method()==='GET');
  await page.getByRole('button',{name:'Tải lại nhãn',exact:true}).click();
  await reloadReviews;
  await page.getByRole('checkbox',{name:'Gộp theo cặp nguồn/cấu kiện chính và loại đo'}).check();
  await evidence.locator('summary').click();
  for(let index=0;index<10;index++) await evidence.getByRole('button',{name:'100 bằng chứng tiếp',exact:true}).click();
  await expect(evidence.getByRole('navigation',{name:'Phân trang bằng chứng trong nhóm'})).toContainText('Trang 11/11');
  await page.getByLabel('Lọc trạng thái rà soát',{exact:true}).selectOption('unreviewed');
  await expect(evidence.getByRole('navigation',{name:'Phân trang bằng chứng trong nhóm'})).toContainText('Trang 10/10');
  await expect(evidence.getByRole('button',{name:/^Bằng chứng \d+$/})).toHaveCount(100);
  await page.reload();
  await signIn(page);
  await expect(page.getByRole('checkbox',{name:/^Mở hồ sơ /})).toHaveCount(13);
  await expect(page.getByRole('checkbox',{name:/^Kiểm tra va chạm /})).toHaveCount(6);
  // Validation-only File sizes avoid allocating multi-gigabyte browser buffers.
  await page.evaluate(limit=>{
    const transfer=new DataTransfer();
    for(const [name,size] of [['large-accepted.ifc',limit],['large-rejected.ifc',limit+1]]){
      const file=new File(['ISO-10303-21;'],name);
      Object.defineProperty(file,'size',{value:size});
      transfer.items.add(file);
    }
    document.querySelector('.inspection-dropzone').dispatchEvent(new DragEvent('drop',{bubbles:true,dataTransfer:transfer}));
  },health.file_limits.ifc);
  await expect(page.locator('.inspection-file')).toHaveCount(1);
  await expect(page.getByRole('alert').filter({hasText:'large-rejected.ifc'})).toBeVisible();
  await page.getByRole('button',{name:'Bỏ large-accepted.ifc',exact:true}).click();
  const queue=Array.from({length:201},(_,i)=>({name:`QUEUE_${i}.pdf`,mimeType:'application/pdf',buffer:Buffer.from('%PDF-validation-only')}));
  await page.getByLabel('Chọn tệp IFC, PDF, DXF hoặc DWG').setInputFiles(queue);
  await expect(page.locator('.inspection-file')).toHaveCount(200);
  assert.equal(await page.locator('.inspection-queue').evaluate(element=>element.clientHeight<element.scrollHeight&&element.clientHeight<=720),true);
  await expect(page.getByRole('alert').filter({hasText:'Hàng đợi nhận tối đa 200 tệp'})).toBeVisible();
  await page.getByRole('checkbox',{name:'Tôi đã kiểm tra các IFC cùng công trình và hệ tọa độ'}).uncheck();
  await page.locator('.inspection-dropzone').scrollIntoViewIfNeeded();
  await page.screenshot({path:resolve('.local/capacity-desktop.png')});
  await page.setViewportSize({width:390,height:844});
  await page.locator('.inspection-dropzone').scrollIntoViewIfNeeded();
  await page.screenshot({path:resolve('.local/capacity-mobile.png')});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
  assert.deepEqual(errors,[]);
  console.log('PASS: 13 inputs, 6 IFC, 2204 elements, 1100 actual geometric findings, complete exports, restart, 200-file queue, paginated results and mobile layout.');
} finally {
  await browser?.close();
  if (backend.exitCode===null) {
    await promisify(execFile)(resolve('.venv/Scripts/python.exe'), ['-c',
      'import psutil,sys\nroot=psutil.Process(int(sys.argv[1])); assert root.name().lower()=="node.exe" and any(a.replace(chr(92),"/").endswith("frontend/tests/capacity.mjs") for a in root.cmdline())\nfor p in reversed(root.children(recursive=True)):\n try:\n  c=p.cmdline()\n  if "--desktop" in c and "--parent-pid" in c and str(root.pid) in c:\n   for child in p.children(recursive=True): child.kill()\n   p.kill()\n except psutil.NoSuchProcess: pass\n', String(process.pid)], {windowsHide:true,timeout:15000});
    await new Promise(done=>{if(backend.exitCode!==null)done();else backend.once('exit',done);});
  }
  await server?.close();
  await cleanLocalTestDatabase(database);
  const workspace=await realpath('.');
  const target=await realpath(directory);
  assert.equal(target,resolve(await realpath(resolve(workspace,'.local')),database));
  await rm(target,{recursive:true,force:true,maxRetries:3});
}

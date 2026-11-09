import {chromium, expect} from '@playwright/test';
import assert from 'node:assert/strict';
import {spawn, execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {mkdir, readFile, realpath, rm, writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {createServer as httpServer, request as httpRequest} from 'node:http';
import {preview} from 'vite';
import {tmpdir} from 'node:os';
import {signIn, openTestProject, uploadSyntheticFixture, cleanLocalTestDatabase, downloadClashReport} from './account-helper.mjs';

// Browser plugin unavailable. Test only an isolated localhost database, never the saved Atlas/R2 connection.
const database = `bim_insight_test_inspectionram_${Date.now()}`;
const coverage = process.argv.includes('--coverage');
const permissions = process.argv.includes('--cache-permissions');
const conclusions = process.argv.includes('--conclusions');
const directory = resolve('.local', database), output = conclusions ? resolve(tmpdir(),'bim-insight-run-conclusions-20261109') : permissions ? resolve(tmpdir(),'bim-insight-cache-permission-20261109') : coverage ? resolve(tmpdir(),'bim-insight-ifc-coverage-20261109') : process.argv.includes('--lifecycle') ? resolve(tmpdir(),'bim-insight-project-lifecycle-20261109') : resolve('.local/snowdon-20261108');
await mkdir(directory, {recursive:true}); await mkdir(output, {recursive:true});
process.env.BIM_UI_TEST = '1';
const backend = spawn(resolve('.venv/Scripts/python.exe'), ['-m','app','--desktop','--parent-pid',String(process.pid)], {
  windowsHide:true, stdio:['ignore','pipe','pipe'], env:{...process.env, BIM_MONGODB_URI:'mongodb://127.0.0.1:27017',
    BIM_DATABASE:database, BIM_DATA_DIR:resolve(directory,'data'), PYTHONPATH:resolve('backend')},
});
backend.stderr.on('data', () => {});
let server, gateway, browser, page, finish, fixtureBundle, scenario = 'actual';
const errors = [], missingProjects = [];
const result = {status:'running', production_atlas_r2_used:false};
try {
  const connection = await new Promise((done,reject) => {
    const lines=createInterface({input:backend.stdout}); const timer=setTimeout(()=>reject(new Error('Backend startup timeout')),30000);
    lines.once('line',line=>{clearTimeout(timer);try{done(JSON.parse(line));}catch{reject(new Error('Invalid startup response'));}});
  });
  assert.match(connection.base_url,/^http:\/\/127\.0\.0\.1:\d+$/);
  gateway=httpServer((request,response)=>{
    if(request.url==='/api/inspections' && request.method==='POST' && scenario==='memory'){
      request.resume(); request.on('end',()=>{
        response.writeHead(200,{'Content-Type':'application/x-ndjson','Cache-Control':'no-store'});
        const stats={memory_bytes:512*1024**2,peak_memory_bytes:768*1024**2,memory_limit_bytes:1024**3,system_available_bytes:2*1024**3,elapsed_seconds:4.4};
        response.write(JSON.stringify({type:'progress',phase:'building_geometry',done:3,total:10,...stats})+'\n');
        finish=()=>response.end(JSON.stringify({type:'result',report:{id:'e'.repeat(32),name:'RAM-probe.ifc',kind:'ifc',size_bytes:100,sha256:'f'.repeat(64),discipline:'ARCH',status:'failed',error_code:'processing_memory_limit',elapsed_seconds:4.4,report_url:'/api/inspections/'+ 'e'.repeat(32)+'/report',result:null,assets:{},processing:stats}})+'\n');
      });return;
    }
    const upstream=httpRequest(new URL(request.url,connection.base_url),{method:request.method,headers:request.headers},value=>{response.writeHead(value.statusCode,value.headers);value.pipe(response);});
    upstream.on('error',()=>{if(!response.headersSent)response.writeHead(502,{'Content-Type':'application/json'});response.end(JSON.stringify({detail:'processing_failed'}));});
    response.on('close',()=>upstream.destroy()); request.pipe(upstream);
  });
  await new Promise(done=>gateway.listen(0,'127.0.0.1',done));
  server=await preview({root:resolve('frontend'),configFile:resolve('frontend/vite.config.ts'),preview:{host:'127.0.0.1',port:0,
    proxy:{'/api':{target:`http://127.0.0.1:${gateway.address().port}`,changeOrigin:true,headers:{Authorization:`Bearer ${connection.token}`,Origin:'http://127.0.0.1:1420'}}}}});
  browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
  page=await browser.newPage({viewport:{width:1440,height:1000}}); page.setDefaultTimeout(30000);
  page.on('pageerror',error=>errors.push(error.message));
  page.on('response',response=>{if(response.status()===404 && /\/api\/projects\//.test(response.url()))missingProjects.push(response.url());});
  await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/#inspection`); await signIn(page);
  const id=await openTestProject(page,'RAM and recovery regression');
  await page.evaluate(()=>{const key=Object.keys(localStorage).find(value=>/^bim-insight\.workspace\.v1\./.test(value));if(!key)throw new Error('Workspace preference missing');localStorage.setItem(key,JSON.stringify({project_id:'11111111-1111-4111-8111-111111111111',revision:'R01'}));});
  await page.reload(); await signIn(page);
  await expect(page.getByLabel('Dự án đang mở',{exact:true})).toHaveValue(id,{timeout:5000});
  assert.deepEqual(missingProjects,[]);
  await expect(page.getByRole('textbox',{name:'Revision cần mở',exact:true})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Mở revision',exact:true})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Xóa dự án',exact:true})).toBeVisible();
  if(!process.argv.includes('--stale-only')){
    const bundle=await uploadSyntheticFixture(page);
    fixtureBundle=bundle;
    await page.getByRole('button',{name:'Bắt đầu kiểm tra',exact:true}).click();
    await expect(page.getByText(`Đã xử lý ${bundle.files.length}/${bundle.files.length} tệp`,{exact:true})).toBeVisible({timeout:120000});
    await expect(page.locator('.ifc-viewer .coord-toolbar [role="status"]')).toContainText('3/3',{timeout:60000});
    scenario='memory';
    await page.getByLabel('Chọn tệp IFC, PDF, DXF hoặc DWG').setInputFiles({name:'RAM-probe.ifc',mimeType:'application/octet-stream',buffer:Buffer.from('ISO-10303-21;')});
    await page.getByRole('button',{name:'Bắt đầu kiểm tra',exact:true}).click();
    await expect(page.getByTestId('inspection-progress')).toContainText('3/10');
    await expect(page.getByTestId('inspection-progress')).toContainText('0.50 GiB');
    await expect(page.locator('.ifc-viewer')).toHaveCount(0);
    await expect(page.getByText('Đang dành RAM cho bộ xử lý. Mô hình 3D sẽ mở lại khi tác vụ kết thúc.',{exact:true})).toBeVisible();
    await page.getByTestId('inspection-progress').scrollIntoViewIfNeeded();
    await page.screenshot({path:resolve(output,'memory-progress-desktop.png')});
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
    await page.getByTestId('inspection-progress').scrollIntoViewIfNeeded();
    await page.screenshot({path:resolve(output,'memory-progress-mobile.png')});
    finish();
    await expect(page.getByText(`Đã xử lý ${bundle.files.length+1}/${bundle.files.length+1} tệp`,{exact:true})).toBeVisible();
    await page.getByRole('button',{name:'Xem kết quả RAM-probe.ifc',exact:true}).click();
    await expect(page.locator('.inspection-detail-content .processing-memory')).toContainText('0.75 GiB');
    await expect(page.locator('.ifc-viewer .coord-toolbar [role="status"]')).toContainText('3/3',{timeout:60000});
    Object.assign(result,{live_ram:true,failed_import_ram_visible:true,viewer_released_during_processing:true,desktop_and_mobile:true,memory_failure_uses_transport_fixture:true});
  }
  if(conclusions){
    scenario='actual';
    const {checkRunConclusions}=await import('./run-conclusion-checks.mjs');
    Object.assign(result,await checkRunConclusions(page,output));
  }
  if(permissions){
    scenario='actual';
    await page.setViewportSize({width:1440,height:1000});
    await openTestProject(page,'IFC only and cache permissions');
    const files=fixtureBundle.files.filter(file=>file.name.endsWith('.ifc'));
    assert.equal(files.length,3);
    await page.getByLabel('Chọn tệp IFC, PDF, DXF hoặc DWG').setInputFiles(files.map(file=>({name:file.name,mimeType:'application/octet-stream',buffer:Buffer.from(file.content)})));
    await page.getByRole('button',{name:'Bắt đầu kiểm tra',exact:true}).click();
    await expect(page.getByText('Đã xử lý 3/3 tệp',{exact:true})).toBeVisible({timeout:120000});
    await expect(page.getByText('Kiểm tra trực tiếp IFC · DXF không bắt buộc',{exact:true})).toBeVisible();
    await page.getByLabel('Tôi đã kiểm tra các IFC cùng công trình và hệ tọa độ',{exact:true}).check();
    await expect(page.getByRole('button',{name:'Chạy kiểm tra va chạm',exact:true})).toBeEnabled();
    await page.route('**/api/inspections/clashes',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({
      id:'c'.repeat(32),status:'failed',verdict:'unavailable',project_id:null,issues:[],evaluation:null,coverage:null,
      diagnostics:[{code:'clash_cache_permission_denied'}],report_url:'/api/inspections/clashes/'+ 'c'.repeat(32),parameters:route.request().postDataJSON(),sources:[],
    })}));
    await page.getByRole('button',{name:'Chạy kiểm tra va chạm',exact:true}).click();
    await expect(page.locator('.clash-diagnostics')).toContainText('App không có quyền đọc hoặc ghi cache hình học trên máy.');
    await expect(page.locator('.clash-verdict')).toContainText('Chưa có kết luận va chạm.');
    await page.locator('.clash-diagnostics').scrollIntoViewIfNeeded();
    await page.screenshot({path:resolve(output,'cache-permission-desktop.png')});
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
    await page.locator('.clash-diagnostics').scrollIntoViewIfNeeded();
    await page.screenshot({path:resolve(output,'cache-permission-mobile.png')});
    await page.unroute('**/api/inspections/clashes');
    await page.getByRole('button',{name:'Chạy kiểm tra va chạm',exact:true}).click();
    const clash=await downloadClashReport(page);
    assert.equal(clash.status,'completed');assert.equal(clash.issues.length,2);assert.equal(clash.drawing_link,null);
    await page.locator('.clash-verdict').scrollIntoViewIfNeeded();
    await page.screenshot({path:resolve(output,'ifc-only-success-mobile.png')});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
    await expect(page.locator('vite-error-overlay')).toHaveCount(0);
    Object.assign(result,{ifc_only_without_dxf_succeeds:true,cache_permission_message:true,permission_error_uses_transport_fixture:true});
  }
  if(process.env.BIM_SNOWDON_TEST_DIR){
    scenario='actual';
    await page.setViewportSize({width:1440,height:1000});
    await openTestProject(page,'Snowdon actual IFC memory verification');
    const manifest=JSON.parse(await readFile(resolve(output,'source-manifest.json'),'utf8'));
    const files=manifest.map(file=>resolve(process.env.BIM_SNOWDON_TEST_DIR,file.path.split('\\').at(-1)));
    const reports=[];
    const collect=response=>{
      if(response.request().method()==='POST' && new URL(response.url()).pathname==='/api/inspections'){
        reports.push(response.text().then(body=>{
          const events=body.trim().split('\n').map(line=>JSON.parse(line));
          const report=events.find(event=>event.type==='result')?.report;
          assert.ok(report,body); return report;
        }));
      }
    };
    page.on('response',collect);
    await page.getByLabel('Chọn tệp IFC, PDF, DXF hoặc DWG').setInputFiles(files);
    await page.getByRole('button',{name:'Bắt đầu kiểm tra',exact:true}).click();
    await expect(page.getByTestId('inspection-progress').getByRole('meter',{name:'RAM bộ xử lý'})).toBeVisible({timeout:30000});
    await page.getByTestId('inspection-progress').scrollIntoViewIfNeeded();
    await page.screenshot({path:resolve(output,'snowdon-real-progress.png')});
    await expect(page.getByText('Đã xử lý 5/5 tệp',{exact:true})).toBeVisible({timeout:600000});
    const actual=await Promise.all(reports); page.off('response',collect);
    assert.equal(actual.length,5);
    for(const report of actual){
      assert.notEqual(report.status,'failed',JSON.stringify(report));
      assert.ok(report.processing.peak_memory_bytes<=report.processing.memory_limit_bytes);
      assert.equal(report.sha256,manifest.find(file=>file.path.endsWith(report.name)).sha256);
    }
    await expect(page.locator('.ifc-viewer .coord-toolbar [role="status"]')).toContainText('5/5',{timeout:120000});
    const architecture=actual.find(report=>report.name.includes('Architectural'));
    await page.getByRole('button',{name:`Xem kết quả ${architecture.name}`,exact:true}).click();
    if(coverage){
      assert.equal(architecture.status,'completed');assert.equal(architecture.result.reference_count,64);assert.equal(architecture.result.excluded_count,0);
      await expect(page.locator('.inspection-detail-content')).toContainText('64 đối tượng đường/điểm tham chiếu');
      await expect(page.locator('.inspection-diagnostics')).toHaveCount(0);
      await page.getByText('Đối tượng tham chiếu · 64 (20 mẫu đầu)',{exact:true}).click();
      await expect(page.locator('.inspection-detail-content')).toContainText('Chỉ có đường/điểm, không có bề mặt hoặc khối để kiểm tra va chạm.');
    }
    const download=page.waitForEvent('download');
    await page.getByRole('button',{name:'Tải báo cáo JSON',exact:true}).click();
    const full=JSON.parse(await readFile(await (await download).path(),'utf8'));
    assert.equal(full.result.elements.length,architecture.result.element_count);
    assert.equal(full.processing.peak_memory_bytes,architecture.processing.peak_memory_bytes);
    if(coverage){
      assert.equal(full.result.inventory.length,full.result.total_element_count);
      assert.equal(full.result.reference_elements.length,64);
      assert.equal(full.result.inventory.filter(item=>item.geometry_status==='unassessed').length,0);
    }
    await writeFile(resolve(output,'snowdon-real-reports.json'),JSON.stringify(actual,null,2));
    await page.locator('.inspection-detail-content .processing-memory').scrollIntoViewIfNeeded();
    await page.screenshot({path:resolve(output,'snowdon-real-result.png')});
    Object.assign(result,{real_snowdon_files:5,real_viewer_models:5,full_architecture_export:full.result.elements.length});
    if(coverage){
      for(const report of actual){
        const selected=/Electrical|HVAC/.test(report.name);
        await page.getByLabel(`Kiểm tra va chạm ${report.name}`,{exact:true}).setChecked(selected);
      }
      await page.getByLabel('Tôi đã kiểm tra các IFC cùng công trình và hệ tọa độ',{exact:true}).check();
      await page.getByRole('button',{name:'Chạy kiểm tra va chạm',exact:true}).click();
      await expect(page.locator('.clash-verdict')).toBeVisible({timeout:180000});
      const clash=await downloadClashReport(page);
      assert.notEqual(clash.status,'failed',JSON.stringify(clash.diagnostics));
      assert.equal(clash.coverage.missing_geometry,0);assert.equal(clash.coverage.tested_elements,4734);
      assert.equal(clash.source_inventories.length,2);
      if(clash.issues.length){
        await page.getByRole('button',{name:'Xem va chạm 1 trong 3D',exact:true}).click();
        await expect(page.getByTestId('clash-selection')).toBeVisible();
      }
      await page.locator('.clash-verdict').scrollIntoViewIfNeeded();
      await page.screenshot({path:resolve(output,'clash-desktop.png')});
      await page.setViewportSize({width:390,height:844});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
      await page.locator('.clash-verdict').scrollIntoViewIfNeeded();
      await page.screenshot({path:resolve(output,'clash-mobile.png')});
      Object.assign(result,{reference_curves_separate:true,full_inventory_export:true,actual_ifc_clash_tested:4734,clash_issue_3d:clash.issues.length>0,mobile_no_overflow:true});
    }
  }
  if(process.argv.includes('--lifecycle')){
    scenario='actual';
    await page.setViewportSize({width:1440,height:1000});
    await expect(page.getByLabel('Revision hồ sơ',{exact:true})).toHaveCount(0);
    await page.getByRole('button',{name:'So trục XY',exact:true}).click();
    await expect(page.getByText('Khớp 2/2 trục XY',{exact:true})).toBeVisible();
    await page.getByLabel('Tôi xác nhận bản vẽ và mô hình cùng công trình và đúng tầng',{exact:true}).check();
    await page.getByRole('button',{name:'Xác nhận và lưu liên kết',exact:true}).click();
    await expect(page.getByText('Đã lưu liên kết tầng',{exact:true})).toBeVisible();
    await page.getByLabel('Tôi đã kiểm tra các IFC cùng công trình và hệ tọa độ',{exact:true}).check();
    await page.getByRole('button',{name:'Chạy kiểm tra va chạm',exact:true}).click();
    const run=await downloadClashReport(page);assert.equal(run.issues.length,2);
    const keep=await openTestProject(page,'Keep shared source files');
    const bundle=await uploadSyntheticFixture(page);
    await page.getByRole('button',{name:'Bắt đầu kiểm tra',exact:true}).click();
    await expect(page.getByText('Đã xử lý 4/4 tệp',{exact:true})).toBeVisible({timeout:120000});
    await page.getByLabel('Dự án đang mở',{exact:true}).selectOption(id);
    await expect(page.getByLabel('Chọn tệp IFC, PDF, DXF hoặc DWG')).toBeEnabled();
    await expect(page.locator('.project-file-detail')).toHaveCount(4);
    const original=bundle.files[0];
    await page.getByLabel('Chọn tệp IFC, PDF, DXF hoặc DWG').setInputFiles({name:original.name,mimeType:'application/octet-stream',buffer:Buffer.from(original.content.replace('SYNTHETIC GEOMETRY LAB','Updated export'))});
    const [updatedResponse]=await Promise.all([page.waitForResponse(response=>response.request().method()==='POST' && new URL(response.url()).pathname==='/api/inspections'),page.getByRole('button',{name:'Bắt đầu kiểm tra',exact:true}).click()]);
    const updatedEvents=(await updatedResponse.text()).trim().split('\n').map(line=>JSON.parse(line));
    const updated=updatedEvents.find(event=>event.type==='result')?.report;assert.ok(updated);
    await expect(page.getByText('Đã xử lý 1/1 tệp',{exact:true})).toBeVisible({timeout:120000});
    await expect(page.locator('.project-file-detail')).toHaveCount(4);
    await page.getByRole('button',{name:`Mở lượt kiểm tra ${run.id}`,exact:true}).click();
    await expect(page.getByRole('button',{name:'Về hồ sơ hiện tại',exact:true})).toBeVisible();
    await page.getByLabel(`Mở hồ sơ ${original.name}`,{exact:true}).check();
    await expect(page.locator('.ifc-viewer .coord-toolbar [role="status"]')).toContainText('3/3',{timeout:10000});
    await page.getByRole('button',{name:`Mở lượt kiểm tra ${run.id}`,exact:true}).click();
    await page.getByRole('button',{name:'Về hồ sơ hiện tại',exact:true}).click();
    await page.getByRole('button',{name:'Xóa dự án',exact:true}).click();
    const dialog=page.getByRole('dialog',{name:'Xóa dự án',exact:true});
    await expect(dialog).toContainText('RAM and recovery regression');
    await page.screenshot({path:resolve(output,'delete-desktop.png')});
    await page.keyboard.press('Escape');await expect(dialog).toHaveCount(0);
    await expect(page.getByLabel('Dự án đang mở',{exact:true})).toHaveValue(id);
    await page.setViewportSize({width:390,height:844});
    await page.getByRole('button',{name:'Xóa dự án',exact:true}).click();
    await expect(dialog).toBeVisible();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
    await page.screenshot({path:resolve(output,'delete-mobile.png')});
    await dialog.getByRole('button',{name:'Giữ dự án',exact:true}).click();
    await expect(page.getByLabel('Dự án đang mở',{exact:true})).toHaveValue(id);
    await page.getByRole('button',{name:'Xóa dự án',exact:true}).click();
    await dialog.getByRole('button',{name:'Xóa toàn bộ dự án',exact:true}).click();
    await expect(page.getByText('Đã xóa dự án RAM and recovery regression và dữ liệu liên quan.',{exact:true})).toBeVisible({timeout:60000});
    await expect(page.getByLabel('Dự án đang mở',{exact:true})).toHaveValue(keep);
    await expect(page.locator('.project-file-detail')).toHaveCount(4);
    await page.reload();await signIn(page);
    await expect(page.getByLabel('Dự án đang mở',{exact:true})).toHaveValue(keep);
    await promisify(execFile)(resolve('.venv/Scripts/python.exe'),['-c',
      'import sys; from pathlib import Path; from pymongo import MongoClient\nname,pid,root=sys.argv[1:]; assert name.startswith("bim_insight_test_inspectionram_")\nc=MongoClient("mongodb://127.0.0.1:27017"); db=c[name]\nassert db.projects.find_one({"_id":pid}) is None\nfor key in ["project_inspections","project_runs","project_links","project_issues","project_cases","project_advice","project_conclusions","auth_artifacts","storage_refs"]: assert db[key].count_documents({"project_id":pid})==0,key\nassert len(list((Path(root)/"cache/models").glob("*.ifc")))==3\nassert len(list((Path(root)/"reports").glob("*.json")))==4\nassert not list((Path(root)/"clashes").glob("*.json"))\nassert not list((Path(root)/"links").glob("*.json"))\nassert db.auth_users.count_documents({})==1\nc.close()',database,id,resolve(directory,'data')],{windowsHide:true});
    Object.assign(result,{revision_controls_removed:true,automatic_source_update:true,old_run_restores_after_update:true,latest_source_replaces_historical_model:true,alignment_and_clash_without_revision:true,delete_cancel_keyboard_and_mobile:true,project_cascade_deleted:true,other_project_shared_sources_preserved:true,accounts_preserved:true});
  }
  assert.deepEqual(errors,[]);
  Object.assign(result,{status:'passed',stale_project_recovers_without_404:true,console_errors:errors});
  console.log(JSON.stringify(result));
}catch(error){
  Object.assign(result,{status:'failed',error:error.message,console_errors:errors});
  await page?.screenshot({path:resolve(output,'ui-failure.png'),timeout:10000}).catch(()=>{}); throw error;
}finally{
  await writeFile(resolve(output,'ui-result.json'),JSON.stringify(result,null,2));
  await browser?.close();
  if(server)await new Promise(done=>server.httpServer.close(done));
  if(gateway)await new Promise(done=>{gateway.close(done);gateway.closeAllConnections();});
  if(backend.exitCode===null){
    await promisify(execFile)(resolve('.venv/Scripts/python.exe'),['-c','import psutil,sys\np=psutil.Process(int(sys.argv[1])); assert "--desktop" in p.cmdline() and "--parent-pid" in p.cmdline() and sys.argv[2] in p.cmdline()\nfor c in reversed(p.children(recursive=True)):\n try: c.kill()\n except psutil.NoSuchProcess: pass\np.kill()\n',String(backend.pid),String(process.pid)],{windowsHide:true,timeout:15000});
    await new Promise(done=>{if(backend.exitCode!==null)done();else backend.once('exit',done);});
  }
  await cleanLocalTestDatabase(database);
  const target=await realpath(directory);assert.equal(target,resolve(await realpath('.local'),database));await rm(target,{recursive:true,force:true,maxRetries:3});
}

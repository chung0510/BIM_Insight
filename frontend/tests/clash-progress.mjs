import {chromium,expect} from '@playwright/test';
import assert from 'node:assert/strict';
import {spawn,execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {mkdir,realpath,rm,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {createServer as httpServer,request as httpRequest} from 'node:http';
import {preview} from 'vite';
import {signIn,openTestProject,uploadSyntheticFixture,cleanLocalTestDatabase} from './account-helper.mjs';

// Browser plugin unavailable; Playwright exercises the built app and an isolated local API.
const database=`bim_insight_test_clashprogress_${Date.now()}`;
const directory=resolve('.local',database);
const output=resolve('.local/clash-memory-20261108');
await mkdir(directory,{recursive:true});await mkdir(output,{recursive:true});
process.env.BIM_UI_TEST='1';
const backend=spawn(resolve('.venv/Scripts/python.exe'),['-m','app','--desktop','--parent-pid',String(process.pid)],{windowsHide:true,stdio:['ignore','pipe','pipe'],env:{...process.env,BIM_MONGODB_URI:'mongodb://127.0.0.1:27017',BIM_DATABASE:database,BIM_DATA_DIR:resolve(directory,'data'),PYTHONPATH:resolve('backend')}});
backend.stderr.on('data',()=>{});
let server,gateway,browser,scenario='actual',complete,cancelled=false;
const errors=[];
const partial={id:'a'.repeat(32),status:'partial',verdict:'incomplete',dataset:null,issues:[],diagnostics:[{code:'clash_missing_geometry'}],coverage:{tested_elements:10,candidate_pairs:0,missing_geometry:1,nonmanifold:0,routing_elements:0,shared_reference_pairs:0},evaluation:null,report_url:'/api/inspections/clashes/'+ 'a'.repeat(32)};
const memory={...partial,status:'failed',verdict:'unavailable',coverage:null,diagnostics:[{code:'processing_memory_limit',peak_memory_bytes:4*1024**3,memory_limit_bytes:3*1024**3,elapsed_seconds:906.5}]};
try{
  const connection=await new Promise((done,reject)=>{
    const lines=createInterface({input:backend.stdout});const timer=setTimeout(()=>reject(new Error('Backend startup timeout')),30000);
    lines.once('line',line=>{clearTimeout(timer);try{done(JSON.parse(line));}catch{reject(new Error('Invalid backend connection'));}});
  });
  assert.match(connection.base_url,/^http:\/\/127\.0\.0\.1:\d+$/);assert.ok(connection.token.length>=32);
  gateway=httpServer((request,response)=>{
    if(request.url==='/api/inspections/clashes'&&request.method==='POST'&&scenario!=='actual'){
      request.resume();response.writeHead(200,{'Content-Type':'application/x-ndjson','Cache-Control':'no-store'});
      response.write(JSON.stringify({type:'progress',phase:'building_geometry',source_name:'Timber kiểm thử truyền tiến độ',source_index:2,source_count:4,done:12,total:100,elapsed_seconds:37})+'\n');
      response.on('close',()=>{cancelled=true;});
      if(scenario==='disconnect')setTimeout(()=>response.destroy(),300);
      else complete=()=>response.end(JSON.stringify({type:'result',report:scenario==='memory'?memory:partial})+'\n');
      return;
    }
    const upstream=httpRequest(new URL(request.url,connection.base_url),{method:request.method,headers:request.headers},result=>{response.writeHead(result.statusCode,result.headers);result.pipe(response);});
    upstream.on('error',()=>{if(!response.headersSent)response.writeHead(502,{'Content-Type':'application/json'});response.end(JSON.stringify({detail:'clash_connection_lost'}));});
    response.on('close',()=>upstream.destroy());request.pipe(upstream);
  });
  await new Promise(done=>gateway.listen(0,'127.0.0.1',done));
  server=await preview({root:resolve('frontend'),configFile:resolve('frontend/vite.config.ts'),preview:{host:'127.0.0.1',port:0,proxy:{'/api':{target:`http://127.0.0.1:${gateway.address().port}`,changeOrigin:true,headers:{Authorization:`Bearer ${connection.token}`,Origin:'http://127.0.0.1:1420'}}}}});
  browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
  const page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',error=>errors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/#inspection`);
  await signIn(page);await openTestProject(page,'Clash stream regression');const bundle=await uploadSyntheticFixture(page);
  await page.getByRole('button',{name:'Bắt đầu kiểm tra',exact:true}).click();
  await expect(page.getByText(`Đã xử lý ${bundle.files.length}/${bundle.files.length} tệp`,{exact:true})).toBeVisible({timeout:120000});
  await page.getByRole('checkbox',{name:'Tôi đã kiểm tra các IFC cùng công trình và hệ tọa độ'}).check();
  const run=page.getByRole('button',{name:'Chạy kiểm tra va chạm',exact:true});
  await run.click();await expect(page.locator('.clash-verdict')).toContainText('Hoàn tất trong phạm vi đã chọn',{timeout:60000});
  scenario='hold';await run.click();
  await expect(page.getByTestId('clash-progress')).toContainText('Timber kiểm thử truyền tiến độ');
  await expect(page.getByTestId('clash-progress')).toContainText('12/100');
  await expect(page.getByTestId('clash-progress')).toContainText('37 giây');
  await page.getByTestId('clash-progress').scrollIntoViewIfNeeded();await page.screenshot({path:resolve(output,'clash-progress-desktop.png')});
  await page.setViewportSize({width:390,height:844});await page.getByTestId('clash-progress').scrollIntoViewIfNeeded();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
  await page.screenshot({path:resolve(output,'clash-progress-mobile.png')});
  await page.getByRole('button',{name:'Hủy kiểm tra va chạm',exact:true}).click();
  await expect(page.getByRole('alert').filter({hasText:'Đã hủy kiểm tra'})).toBeVisible();await expect(run).toBeEnabled();
  await expect.poll(()=>cancelled).toBe(true);
  scenario='disconnect';await run.click();await expect(page.getByRole('alert').filter({hasText:'Mất kết nối với bộ xử lý va chạm'})).toBeVisible({timeout:45000});await expect(run).toBeEnabled();
  scenario='hold';await run.click();await expect(page.getByTestId('clash-progress')).toContainText('12/100');complete();
  await expect(page.locator('.clash-verdict')).toContainText('Đã kiểm tra một phần');await expect(run).toBeEnabled();
  scenario='memory';await run.click();await expect(page.getByTestId('clash-progress')).toContainText('12/100');complete();
  await expect(page.locator('.clash-verdict')).toContainText('Kiểm tra chưa hoàn tất');
  await expect(page.getByText('RAM tiến trình cao nhất:',{exact:false})).toContainText('4.00 GiB · Ngân sách: 3.00 GiB · Dừng sau 906 giây');
  await expect(run).toBeEnabled();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
  await page.getByText('RAM tiến trình cao nhất:',{exact:false}).scrollIntoViewIfNeeded();
  await page.screenshot({path:resolve(output,'clash-memory-mobile.png')});
  assert.deepEqual(errors,[]);
  await writeFile(resolve(output,'progress-ui-result.json'),JSON.stringify({status:'passed',actual_small_geometry_run:true,live_progress_before_result:true,cancel_releases_request:true,mid_stream_connection_reset_handled:true,complete_partial_report:true,memory_measurements_displayed:true,desktop_and_mobile:true,console_errors:errors,production_database_used:false},null,2));
  console.log('PASS: real clash stream, live phase/count/elapsed, cancel, ECONNRESET feedback, partial result and mobile layout.');
}finally{
  await browser?.close();
  if(server)await new Promise(done=>server.httpServer.close(done));
  if(gateway)await new Promise(done=>{gateway.close(done);gateway.closeAllConnections();});
  if(backend.exitCode===null){
    await promisify(execFile)(resolve('.venv/Scripts/python.exe'),['-c','import psutil,sys\nroot=psutil.Process(int(sys.argv[1])); assert root.name().lower()=="node.exe" and any(a.replace(chr(92),"/").endswith("frontend/tests/clash-progress.mjs") for a in root.cmdline())\nfor p in reversed(root.children(recursive=True)):\n try:\n  c=p.cmdline()\n  if "--desktop" in c and "--parent-pid" in c and str(root.pid) in c:\n   for child in p.children(recursive=True): child.kill()\n   p.kill()\n except psutil.NoSuchProcess: pass\n',String(process.pid)],{windowsHide:true,timeout:15000});
    await new Promise(done=>{if(backend.exitCode!==null)done();else backend.once('exit',done);});
  }
  await cleanLocalTestDatabase(database);
  const target=await realpath(directory);assert.equal(target,resolve(await realpath('.local'),database));await rm(target,{recursive:true,force:true,maxRetries:3});
}

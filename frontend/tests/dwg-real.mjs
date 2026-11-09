import {chromium, expect} from '@playwright/test';
import assert from 'node:assert/strict';
import {readFile, writeFile, mkdir, rename} from 'node:fs/promises';
import {resolve, basename, relative} from 'node:path';
import {createHash} from 'node:crypto';
import {downloadClashReport} from './account-helper.mjs';

// Explicit acceptance run: persistent user project, real Atlas and private R2; no generated inputs.
assert.equal(process.env.BIM_REAL_TEST, '1');
assert.ok(process.env.BIM_REAL_USERNAME && process.env.BIM_REAL_PASSWORD);
const origin = 'http://127.0.0.1:1420';
const output = resolve('data/artifacts/dwg-0120');
const dataDirectory = resolve(process.env.BIM_REAL_DATA_DIR || 'data/inspections');
const manifest = JSON.parse(await readFile(resolve(output, 'real-inputs.json'), 'utf8'));
const coordinates = JSON.parse(await readFile(resolve(output, 'coordinate-check.json'), 'utf8'));
assert.equal(coordinates.same_reference_frames, true);
for (const file of manifest.files) assert.ok(!relative(resolve('data/inputs/Nha02'), resolve(file.path)).startsWith('..'));
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const hashes = new Map(await Promise.all(manifest.files.map(async file => [basename(file.path), hash(await readFile(file.path))])));
const browser = await chromium.launch({headless:true, executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
const page = await browser.newPage({viewport:{width:1536,height:1000}});
const errors = [];
page.on('pageerror', error => errors.push(error.message));
let restoreSource, restoreBackup;
try {
  await page.goto(origin + '/#inspection');
  await page.getByLabel('Tên đăng nhập', {exact:true}).fill(process.env.BIM_REAL_USERNAME);
  await page.getByLabel('Mật khẩu', {exact:true}).fill(process.env.BIM_REAL_PASSWORD);
  const login = page.waitForResponse(r => r.url().endsWith('/api/auth/login') && r.request().method() === 'POST');
  await page.getByRole('button', {name:'Đăng nhập',exact:true}).click();
  const authenticated = await login;
  assert.equal(authenticated.ok(), true, 'Real account login failed');
  const session = await authenticated.json();
  const headers = {'X-BIM-Session':session.session_token};
  async function get(path) {
    const response = await page.request.get(origin + path, {headers});
    assert.equal(response.ok(), true, `GET ${path}: ${response.status()}`);
    return response;
  }
  const ready = await get('/api/ready').then(r => r.json());
  assert.equal(ready.storage.database, 'bim_insight');
  assert.ok(ready.storage.host.endsWith('.mongodb.net'));
  const converter = await get('/api/inspections/dwg-converter').then(r => r.json());
  assert.equal(converter.available, true);
  const cloud = await get('/api/projects/storage').then(r => r.json());
  assert.equal(cloud.configured, true);
  assert.equal(cloud.bucket, 'bim-insight');
  await expect(page.getByRole('button', {name:'Dùng bộ mẫu tổng hợp',exact:true})).toHaveCount(0);
  await expect(page.getByRole('button', {name:'Mở phiên tạm',exact:true})).toHaveCount(0);
  const projects = page.getByRole('region', {name:'Quản lý dự án và lịch sử'});
  const projectName = 'Nha02 · Phối hợp hồ sơ';
  const listing = await get('/api/projects?limit=100').then(r => r.json());
  const existing = listing.items.find(project => project.name === projectName && project.permissions.edit);
  if (existing) await projects.getByLabel('Dự án đang mở').selectOption(existing.id);
  else {
    await projects.getByLabel('Dự án mới').fill(projectName);
    await projects.getByRole('button', {name:'Tạo dự án',exact:true}).click();
  }
  await expect(projects.locator('.project-current')).toContainText(`Dự án: ${projectName}`);
  const projectId = await projects.getByLabel('Dự án đang mở').inputValue();
  await expect(projects.locator('.project-current')).toHaveText(`Dự án: ${projectName}`);
  await page.getByLabel('Chọn tệp IFC, PDF, DXF hoặc DWG').setInputFiles(manifest.files.map(file => file.path));
  await page.getByRole('button', {name:'Bắt đầu kiểm tra',exact:true}).click();
  await page.getByText('Đã xử lý 6/6 tệp', {exact:true}).waitFor({timeout:180000});
  const reports = await get(`/api/projects/${projectId}/inspections?limit=100`).then(r => r.json());
  assert.equal(reports.total, 6);
  for (const report of reports.items) {
    assert.ok(['completed','partial'].includes(report.status), `${report.name}: ${report.status}`);
    assert.equal(report.sha256, hashes.get(report.name));
    assert.equal(report.dataset, null);
    assert.equal(report.project_id, projectId);
  }
  const dwgs = reports.items.filter(report => report.kind === 'dwg');
  assert.equal(dwgs.length, 2);
  for (const drawing of dwgs) {
    assert.ok(drawing.assets.drawing && drawing.assets.converted_dxf);
    const converted = await get(drawing.assets.converted_dxf);
    assert.equal(hash(await converted.body()), drawing.result.conversion.output_sha256);
    const preview = await get(drawing.assets.drawing).then(r => r.json());
    assert.ok(preview.paths.length > 0);
  }
  const coordination = page.getByRole('region', {name:'Phối hợp bản vẽ và mô hình'});
  await coordination.getByRole('img', {name:'Bản vẽ DXF của bạn'}).locator('path').first().waitFor({state:'attached', timeout:30000});
  await coordination.getByText('Đã hiển thị 3/3 mô hình', {exact:true}).waitFor({timeout:60000});
  await page.getByRole('button', {name:`Xem kết quả ${dwgs[0].name}`,exact:true}).click();
  const downloadEvent = page.waitForEvent('download');
  await page.getByRole('button', {name:'Tải DXF đã chuyển',exact:true}).click();
  const download = await downloadEvent;
  assert.equal(hash(await readFile(await download.path())), dwgs[0].result.conversion.output_sha256);
  const clashes = page.getByRole('region', {name:'Kiểm tra va chạm 3D'});
  await clashes.getByLabel('Tôi đã kiểm tra các IFC cùng công trình và hệ tọa độ').check();
  // Shared GUIDs stay unconfirmed; ambiguous references must remain visible in coverage.
  const clashResponse = page.waitForResponse(r => r.url().endsWith('/api/inspections/clashes') && r.request().method() === 'POST', {timeout:150000});
  await clashes.getByRole('button', {name:'Chạy kiểm tra va chạm',exact:true}).click();
  const clashResult = await clashResponse;
  assert.equal(clashResult.ok(), true);
  const run = await downloadClashReport(page);
  assert.ok(['completed','partial'].includes(run.status));
  assert.equal(run.project_id, projectId);
  assert.equal(run.dataset, null);
  assert.equal(run.coverage.routing_elements, 0);
  await writeFile(resolve(output, 'real-clash.json'), JSON.stringify(run,null,2));
  await projects.scrollIntoViewIfNeeded();
  const syncResponse = page.waitForResponse(r => r.url().endsWith(`/api/projects/${projectId}/storage/sync`), {timeout:180000});
  await page.getByRole('button', {name:'Đồng bộ dự án lên R2',exact:true}).click();
  const synced = await syncResponse;
  assert.equal(synced.ok(), true);
  const sync = await synced.json();
  assert.equal(sync.status, 'verified', `R2: ${sync.error || sync.status}`);
  assert.equal(sync.verified_files, sync.total_files);
  const drawing = dwgs[0];
  restoreSource = resolve(dataDirectory, 'assets', drawing.id, 'converted.dxf');
  assert.ok(!relative(dataDirectory, restoreSource).startsWith('..'));
  restoreBackup = resolve(output, `restore-${drawing.id}.dxf`);
  await rename(restoreSource, restoreBackup);
  const restored = await get(drawing.assets.converted_dxf);
  assert.equal(hash(await restored.body()), drawing.result.conversion.output_sha256);
  assert.equal(hash(await readFile(restoreSource)), drawing.result.conversion.output_sha256);
  await page.screenshot({path:resolve(output,'real-project.png')});
  await coordination.locator('.coord-panes').screenshot({path:resolve(output,'real-coordination.png')});
  await page.reload();
  await page.getByLabel('Tên đăng nhập', {exact:true}).fill(process.env.BIM_REAL_USERNAME);
  await page.getByLabel('Mật khẩu', {exact:true}).fill(process.env.BIM_REAL_PASSWORD);
  await page.getByRole('button', {name:'Đăng nhập',exact:true}).click();
  await expect(page.getByLabel('Dự án đang mở')).toHaveValue(projectId, {timeout:30000});
  await expect(projects.locator('.project-current')).toHaveText(`Dự án: ${projectName}`);
  await expect(page.getByRole('button', {name:`Mở lượt kiểm tra ${run.id}`,exact:true})).toBeVisible();
  await page.getByRole('button', {name:`Mở lượt kiểm tra ${run.id}`,exact:true}).click();
  await coordination.getByText('Đã hiển thị 3/3 mô hình', {exact:true}).waitFor({timeout:60000});
  assert.deepEqual(errors, []);
  for (const file of manifest.files) assert.equal(hash(await readFile(file.path)), hashes.get(basename(file.path)));
  const result = {status:'passed', project_id:projectId, project_name:projectName, run_id:run.id,
    converter, atlas_database:ready.storage.database, r2_bucket:cloud.bucket, r2_sync:sync, restored_dxf:true,
    sources:reports.items.map(report=>({id:report.id,name:report.name,kind:report.kind,sha256:report.sha256,status:report.status,conversion:report.result?.conversion,diagnostics:report.result?.diagnostics})),
    clash:{status:run.status,verdict:run.verdict,issue_count:run.issues.length,coverage:run.coverage},
    original_inputs_unchanged:true, browser_errors:errors};
  await writeFile(resolve(output,'real-result.json'), JSON.stringify(result,null,2));
  console.log(JSON.stringify({status:result.status,project_id:projectId,files:reports.total,r2_files:sync.total_files,restored_dxf:true,clash_status:run.status,routing_elements:run.coverage.routing_elements}));
} catch (error) {
  await page.screenshot({path:resolve(output,'real-failure.png')}).catch(()=>{});
  throw error;
} finally {
  if (restoreSource && restoreBackup) {
    try { await readFile(restoreSource); } catch { await rename(restoreBackup,restoreSource).catch(()=>{}); }
  }
  await browser.close();
}

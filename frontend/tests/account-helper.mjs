import { expect } from "@playwright/test";
import assert from "node:assert/strict";
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {resolve} from 'node:path';
import {readFile} from 'node:fs/promises';

export const TEST_PASSWORD = 'UI-only-account-password-123!';
export async function downloadClashReport(page) {
  await expect(page.getByRole('button',{name:'Chạy kiểm tra va chạm',exact:true})).toBeEnabled({timeout:180000});
  await expect(page.locator('.clash-verdict')).toBeVisible();
  const pending = page.waitForEvent('download');
  await page.getByRole('button',{name:'Tải kết quả va chạm JSON',exact:true}).click();
  return JSON.parse(await readFile(await (await pending).path(),'utf8'));
}
export async function signIn(page, username = 'uiadmin') {
  assert.equal(process.env.BIM_UI_TEST, '1', 'Set BIM_UI_TEST=1 and use the isolated localhost test database described in README.');
  await expect(page.getByLabel('Tên đăng nhập', {exact: true})).toBeVisible({timeout:30000});
  const bootstrap = await page.getByRole('heading', {name:'Tạo tài khoản quản trị đầu tiên',exact:true}).isVisible();
  if (bootstrap) {
    await page.getByLabel('Tên hiển thị',{exact:true}).fill('Quản trị thử nghiệm');
    await page.getByLabel('Xác nhận mật khẩu',{exact:true}).fill(TEST_PASSWORD);
  }
  await page.getByLabel('Tên đăng nhập',{exact:true}).fill(username);
  await page.getByLabel('Mật khẩu',{exact:true}).fill(TEST_PASSWORD);
  const response = page.waitForResponse(r => /\/api\/auth\/(login|bootstrap)$/.test(r.url()) && r.request().method()==='POST');
  await page.getByRole('button',{name:bootstrap?'Tạo tài khoản quản trị':'Đăng nhập',exact:true}).click();
  const result = await response;
  assert.equal(result.ok(),true,await result.text());
  const session = await result.json();
  await expect(page.getByRole('button',{name:'Đăng xuất',exact:true})).toBeVisible();
  return session;
}

export async function workspacePreference(page) {
  return page.evaluate(() => {
    const key = Object.keys(localStorage).find(key => /^bim-insight\.workspace\.v1\./.test(key));
    return key ? JSON.parse(localStorage.getItem(key)) : null;
  });
}

export async function openTestProject(page, name = `UI verification ${Date.now()}`) {
  const projects = page.getByRole('region', {name:'Quản lý dự án và lịch sử'});
  await projects.getByLabel('Dự án mới', {exact:true}).fill(name);
  await projects.getByRole('button', {name:'Tạo dự án', exact:true}).click();
  await expect(projects.getByText(`Dự án: ${name}`, {exact:true})).toBeVisible();
  await expect(page.getByLabel('Chọn tệp IFC, PDF, DXF hoặc DWG')).toBeEnabled();
  return projects.getByLabel('Dự án đang mở').inputValue();
}

export async function uploadSyntheticFixture(page, variant = 'demo') {
  assert.equal(process.env.BIM_UI_TEST, '1');
  assert.ok(['demo', 'pilot'].includes(variant));
  const {stdout} = await promisify(execFile)(resolve('.venv/Scripts/python.exe'), ['-c',
    'import json,sys; from app.demo import DATASET,PILOT_DATASET,dataset_bundle; print(json.dumps(dataset_bundle(PILOT_DATASET if sys.argv[1]=="pilot" else DATASET)))', variant],
    {windowsHide:true, env:{...process.env, PYTHONPATH:resolve('backend')}, maxBuffer:8*1024*1024});
  const bundle = JSON.parse(stdout);
  await page.getByLabel('Chọn tệp IFC, PDF, DXF hoặc DWG').setInputFiles(bundle.files.map(file => ({name:file.name,mimeType:'application/octet-stream',buffer:Buffer.from(file.content)})));
  return bundle;
}

export async function cleanLocalTestDatabase(database) {
  assert.match(database, /^bim_insight_test_[a-z0-9_]+$/);
  await promisify(execFile)(resolve('.venv/Scripts/python.exe'), ['-c', 'import sys; from pymongo import MongoClient; name=sys.argv[1]; assert name.startswith("bim_insight_test_"); client=MongoClient("mongodb://127.0.0.1:27017",serverSelectionTimeoutMS=2000); client.drop_database(name); assert name not in client.list_database_names(); client.close()', database], {windowsHide:true});
}

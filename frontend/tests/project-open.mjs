import {chromium, expect} from '@playwright/test';
import {signIn, openTestProject, TEST_PASSWORD} from './account-helper.mjs';

const browser = await chromium.launch({headless:true, executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
const page = await browser.newPage();
try {
  await page.goto('http://127.0.0.1:1420/#inspection');
  const admin = await signIn(page);
  const firstName = `Overview target ${Date.now()}`;
  const firstId = await openTestProject(page, firstName);
  await openTestProject(page, `Overview recent ${Date.now()}`);
  await page.getByRole('button', {name:'Tổng quan',exact:true}).click();
  await page.locator('.work-project-cards > button').filter({has:page.getByRole('heading', {name:firstName,exact:true})}).click();
  await expect(page.getByLabel('Dự án đang mở')).toHaveValue(firstId);
  const teacherName = `teacher${Date.now()}`;
  const teacher = await page.request.post('http://127.0.0.1:1420/api/auth/register', {data:{username:teacherName, display_name:'Project navigation teacher', password:TEST_PASSWORD}}).then(r=>r.json());
  const assigned = await page.request.post(`http://127.0.0.1:1420/api/admin/users/${teacher.user.id}/role`, {headers:{'X-BIM-Session':admin.session_token},data:{role:'teacher',expected_revision:teacher.user.revision}});
  expect(assigned.ok()).toBe(true);
  await page.getByRole('button', {name:'Đăng xuất',exact:true}).click();
  await signIn(page,teacherName);
  await page.getByRole('button', {name:'Kiểm tra hồ sơ',exact:true}).click();
  const targetName = `Teacher target ${Date.now()}`;
  await openTestProject(page,targetName);
  const currentId = await openTestProject(page,`Teacher current ${Date.now()}`);
  await page.getByRole('button', {name:'Tổng quan',exact:true}).click();
  await page.locator('.work-project-cards > button').filter({has:page.getByRole('heading', {name:targetName,exact:true})}).click();
  await page.getByLabel('Dự án đang mở').selectOption(currentId);
  await expect(page.getByLabel('Dự án đang mở')).toHaveValue(currentId);
  await page.getByRole('button', {name:'Hồ sơ được chia sẻ',exact:true}).click();
  await page.getByRole('button', {name:'Kiểm tra hồ sơ',exact:true}).click();
  await expect(page.getByLabel('Dự án đang mở')).toHaveValue(currentId);
  console.log('PASS: overview opens exact project; returning from shared files preserves current owned project.');
} finally { await browser.close(); }

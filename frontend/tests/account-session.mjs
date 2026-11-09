import { chromium, expect } from '@playwright/test';
import assert from 'node:assert/strict';
import { signIn, TEST_PASSWORD } from './account-helper.mjs';

const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
const page=await browser.newPage();
let release;
const gate=new Promise(done=>{release=done;});
try {
  await page.goto('http://127.0.0.1:1420/');
  const session=await signIn(page,'uiuser');
  let started;
  const pending=new Promise(done=>{started=done;});
  await page.route('**/api/auth/password',async route=>{
    started(); await gate;
    await route.fulfill({json:session}).catch(()=>{});
  });
  await page.getByRole('button',{name:'Tài khoản của tôi',exact:true}).click();
  await page.getByLabel('Mật khẩu hiện tại',{exact:true}).fill(TEST_PASSWORD);
  await page.getByLabel('Mật khẩu mới',{exact:true}).fill('Changed-only-in-mock-123!');
  await page.getByLabel('Xác nhận mật khẩu mới',{exact:true}).fill('Changed-only-in-mock-123!');
  await page.getByRole('button',{name:'Đổi mật khẩu',exact:true}).click(); await pending;
  await page.getByRole('button',{name:'Đăng xuất',exact:true}).click();
  await signIn(page,'uistudent');
  release();
  await page.evaluate(()=>new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done))));
  await expect(page.getByRole('heading',{name:'Không gian thực hành BIM',exact:true})).toBeVisible();
  await expect(page.getByText('Người dùng thử nghiệm',{exact:true})).toHaveCount(0);
  assert.equal(await page.locator('.work-role-badge').first().textContent(),'Sinh viên');
  console.log('PASS: delayed password response after logout cannot replace the next account session.');
} finally {release();await browser.close();}

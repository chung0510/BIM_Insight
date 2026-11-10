import { chromium, expect } from '@playwright/test';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { mkdir, writeFile } from 'node:fs/promises';

const root=resolve(`${process.env.BIM_UI_ARTIFACTS || "data/artifacts/rbac-080"}/ui-${Date.now()}`);
assert.equal(process.env.BIM_UI_TEST,'1','Use only the isolated local test server described in README.');
await mkdir(root,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || resolve(process.env.LOCALAPPDATA,'ms-playwright/chromium-1234/chrome-win64/chrome.exe')});
const context=await browser.newContext({viewport:{width:1440,height:1000}});
const page=await context.newPage();
const errors=[];
page.on('pageerror',e=>errors.push(e.message));
page.on('console',m=>{if(m.type()==='error') errors.push(m.text());});
try {
  await page.goto('http://127.0.0.1:1420/',{waitUntil:'networkidle'});
  await expect(page.getByRole('heading',{name:'Tạo tài khoản quản trị đầu tiên',exact:true})).toBeVisible({timeout:10000});
  await page.screenshot({path:resolve(root,'bootstrap.png')});
  if(process.env.BIM_AUTH_RED==='1') { console.log('Bootstrap screen exists'); process.exitCode=0; }
  else {
    const password='UI-only-account-password-123!';
    const fillIdentity=async(name,username)=>{
      await page.getByLabel('Tên hiển thị',{exact:true}).fill(name);
      await page.getByLabel('Tên đăng nhập',{exact:true}).fill(username);
      await page.getByLabel('Mật khẩu',{exact:true}).fill(password);
      await page.getByLabel('Xác nhận mật khẩu',{exact:true}).fill(password);
    };
    await fillIdentity('Quản trị thử nghiệm','uiadmin');
    await page.getByRole('button',{name:'Tạo tài khoản quản trị',exact:true}).click();
    await expect(page.getByRole('button',{name:'Đăng xuất',exact:true})).toBeVisible();
    await expect(page.getByRole('navigation').getByRole('button',{name:'Tài khoản và phân quyền',exact:true})).toBeVisible();
    await expect(page.getByText('Khóa học',{exact:true})).toHaveCount(0);
    await page.screenshot({path:resolve(root,'admin-home.png')});
    await page.getByRole('button',{name:'Đăng xuất',exact:true}).click();
    await page.getByRole('button',{name:'Tạo tài khoản',exact:true}).click();
    await fillIdentity('Người dùng thử nghiệm','uiuser');
    await page.getByRole('button',{name:'Đăng ký tài khoản',exact:true}).click();
    await expect(page.getByRole('navigation').getByRole('button',{name:'Tài khoản và phân quyền',exact:true})).toHaveCount(0);
    await page.getByRole('button',{name:'Kiểm tra hồ sơ',exact:true}).click();
    const projects=page.getByRole('region',{name:'Quản lý dự án và lịch sử'});
    if(!await projects.isVisible()) await page.getByText('Dự án và lịch sử',{exact:true}).click();
    await projects.getByLabel('Dự án mới',{exact:true}).fill('Dự án riêng của uiuser');
    await projects.getByRole('button',{name:'Tạo dự án',exact:true}).click();
    await expect(projects.getByText(/Dự án: Dự án riêng/)).toBeVisible();
    await page.screenshot({path:resolve(root,'user-project.png')});
    await page.getByRole('button',{name:'Đăng xuất',exact:true}).click();
    for(const username of ['uiteacher','uistudent']) {
      await page.getByRole('button',{name:'Tạo tài khoản',exact:true}).click();
      await fillIdentity(username,username);
      await page.getByRole('button',{name:'Đăng ký tài khoản',exact:true}).click();
      await expect(page.getByRole('button',{name:'Đăng xuất',exact:true})).toBeVisible();
      await page.getByRole('button',{name:'Đăng xuất',exact:true}).click();
    }
    const login=async(username)=>{
      await page.getByLabel('Tên đăng nhập',{exact:true}).fill(username);
      await page.getByLabel('Mật khẩu',{exact:true}).fill(password);
      await page.getByRole('button',{name:'Đăng nhập',exact:true}).click();
      await expect(page.getByRole('button',{name:'Đăng xuất',exact:true})).toBeVisible();
    };
    await login('uiadmin');
    await page.getByRole('navigation').getByRole('button',{name:'Tài khoản và phân quyền',exact:true}).click();
    for(const [username,role] of [['uiteacher','teacher'],['uistudent','student']]) {
      await page.getByLabel(`Vai trò của ${username}`,{exact:true}).selectOption(role);
      await page.getByRole('button',{name:`Lưu vai trò của ${username}`,exact:true}).click();
      await expect(page.getByText('Đã cập nhật vai trò.',{exact:true})).toBeVisible();
    }
    await page.screenshot({path:resolve(root,'admin-users.png')});
    await page.getByRole('button',{name:'Đăng xuất',exact:true}).click();
    await login('uiteacher');
    await page.locator('.work-personal-nav>summary').click();
    await expect(page.getByRole('button',{name:'Hồ sơ được chia sẻ',exact:true})).toBeVisible();
    await page.getByRole('button',{name:'Kiểm tra hồ sơ',exact:true}).click();
    await expect(page.getByRole('option',{name:'Dự án riêng của uiuser',exact:true})).toHaveCount(0);
    await page.screenshot({path:resolve(root,'teacher.png')});
    await page.getByRole('button',{name:'Đăng xuất',exact:true}).click();
    await login('uistudent');
    await expect(page.getByRole('heading',{name:/Không gian thực hành/})).toBeVisible();
    await page.setViewportSize({width:375,height:812});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.screenshot({path:resolve(root,'student-375.png'),fullPage:true});
    assert.deepEqual(errors,[]);
    const local=await page.evaluate(()=>Object.entries(localStorage));
    assert.equal(local.some(([key,value])=>/session_token|X-BIM-Session|Bearer /.test(key+value)),false);
    await writeFile(resolve(root,'result.json'),JSON.stringify({status:'passed',roles:['admin','user','teacher','student'],checks:['bootstrap','registration defaults to User','admin changes roles','project isolation','logout clears UI','375px layout','no credentials in localStorage','no runtime errors'],root},null,2));
    console.log(JSON.stringify({status:'passed',root}));
  }
} finally {await browser.close();}

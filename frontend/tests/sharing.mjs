import {chromium,expect} from '@playwright/test';
import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {signIn} from './account-helper.mjs';

const output=resolve(`data/artifacts/rbac-080/shared-${Date.now()}`);
await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
const owner=await browser.newPage({viewport:{width:1440,height:1000}});
const teacher=await browser.newPage({viewport:{width:1440,height:1000}});
const student=await browser.newPage({viewport:{width:1440,height:1000}});
const errors=[];
for(const page of [owner,teacher,student]) page.on('pageerror',e=>errors.push(e.message));
try {
  await owner.goto('http://127.0.0.1:1420/#inspection'); await signIn(owner);
  const panel=owner.getByRole('region',{name:'Quản lý dự án và lịch sử'});
  await expect(panel.getByRole('option',{name:'Pilot workspace test',exact:true}).first()).toBeAttached();
  const project=await panel.getByRole('option',{name:'Pilot workspace test',exact:true}).first().getAttribute('value');
  await panel.getByLabel('Dự án đang mở',{exact:true}).selectOption(project);
  const share=panel.locator('.project-sharing');
  await share.locator('summary').click();
  for(const [username,access] of [['uiteacher','review'],['uistudent','view']]) {
    await share.getByLabel('Tên đăng nhập nhận chia sẻ').fill(username);
    await share.getByLabel('Quyền truy cập chia sẻ').selectOption(access);
    await share.getByRole('button',{name:'Chia sẻ dự án',exact:true}).click();
    await expect(share.getByRole('button',{name:`Thu hồi quyền của ${username}`,exact:true})).toBeVisible();
  }
  async function openShared(page,username) {
    await page.goto('http://127.0.0.1:1420/'); await signIn(page,username);
    await page.getByRole('button',{name:username==='uiteacher'?'Hồ sơ được chia sẻ':'Kiểm tra hồ sơ',exact:true}).click();
    const projects=page.getByRole('region',{name:'Quản lý dự án và lịch sử'});
    await projects.getByLabel('Dự án đang mở',{exact:true}).selectOption(project);
    await projects.locator('.project-run-list>button').first().click();
    const clashes=page.getByRole('region',{name:'Kiểm tra va chạm 3D'});
    await clashes.getByText('Đã kiểm tra một phần — cần xem lại',{exact:true}).waitFor();
    await expect(page.getByRole('button',{name:'Chọn tệp từ máy',exact:true})).toBeDisabled();
    await expect(clashes.getByRole('button',{name:'Chạy kiểm tra va chạm',exact:true})).toBeDisabled();
    await expect(page.getByLabel('Bản vẽ DXF phối hợp')).toBeEnabled();
    await clashes.getByLabel('Lọc loại va chạm').selectOption('intersection');
    await clashes.getByRole('button',{name:'Rà soát cặp 1',exact:true}).click();
    return page.getByRole('region',{name:'Rà soát xung đột',exact:true});
  }
  const review=await openShared(teacher,'uiteacher');
  await expect(review.getByLabel('Người rà soát')).toHaveValue('uiteacher');
  await review.getByLabel('Trạng thái rà soát').selectOption('needs_fix');
  await review.getByLabel('Nhận xét',{exact:true}).fill('Nhận xét giảng viên trên hồ sơ được chia sẻ.');
  await review.getByRole('button',{name:'Lưu rà soát',exact:true}).click();
  await expect(review.getByText('Đã lưu rà soát.',{exact:true})).toBeVisible();
  await teacher.screenshot({path:resolve(output,'teacher-review.png'),fullPage:true});
  const studentReview=await openShared(student,'uistudent');
  await expect(studentReview.getByLabel('Nhận xét',{exact:true})).toHaveValue('Nhận xét giảng viên trên hồ sơ được chia sẻ.');
  await expect(studentReview.getByRole('button',{name:'Lưu rà soát',exact:true})).toBeDisabled();
  await student.screenshot({path:resolve(output,'student-read-only.png'),fullPage:true});
  await share.getByRole('button',{name:'Thu hồi quyền của uiteacher',exact:true}).click();
  const teacherPanel=teacher.getByRole('region',{name:'Quản lý dự án và lịch sử'});
  await teacherPanel.getByRole('button',{name:'Tải lại',exact:true}).click();
  await expect(teacherPanel.getByRole('alert')).toBeVisible();
  await expect(teacher.locator('.ifc-canvas')).toHaveCount(0);
  assert.deepEqual(errors,[]);
  await writeFile(resolve(output,'result.json'),JSON.stringify({status:'passed',checks:['share by username','teacher review','viewer reads feedback but cannot edit/upload/run','DXF browsing allowed','revocation clears loaded workspace'],output},null,2));
  console.log(JSON.stringify({status:'passed',output}));
} finally {await browser.close();}

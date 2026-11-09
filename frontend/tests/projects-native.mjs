import { signIn, workspacePreference, cleanLocalTestDatabase, uploadSyntheticFixture } from "./account-helper.mjs";
import { chromium, expect } from "@playwright/test";
import assert from "node:assert/strict";
import { execFile, spawn } from "node:child_process";
import { copyFile, mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { promisify } from "node:util";
import { createHash } from "node:crypto";

assert.equal(process.platform, "win32", "This check requires Windows/WebView2.");
const run = promisify(execFile);
const stamp = Date.now();
const root = resolve(`data/artifacts/projects/native-${stamp}`);
const database = `bim_insight_test_native_${stamp}`;
process.env.BIM_UI_TEST="1";
const version = JSON.parse(await readFile(resolve("package.json"), "utf8")).version;
const executable = resolve("src-tauri/target/release/bim_insight.exe");
const executableHash = createHash("sha256").update(await readFile(executable)).digest("hex");
const endpoint = "http://127.0.0.1:9327";
const delay = ms => new Promise(done => setTimeout(done, ms));
const online = url => fetch(url).then(() => true, () => false);
const errors = [];
const configuration = process.env.BIM_TEST_DATABASE_CONFIG;
const integrations = process.env.BIM_TEST_INTEGRATIONS === "1";
let dataDirectory = resolve(root, "data");
let integrationEvidence = null;
const environment = { ...process.env };
delete environment.BIM_MONGODB_URI;
let expectedHost = "127.0.0.1";
let current;
await mkdir(root, { recursive: true });
if (configuration) {
  await mkdir(resolve(root, "data"), { recursive: true });
  await copyFile(configuration, resolve(root, "data/database.dpapi"));
  const { stdout } = await run(resolve(".venv/Scripts/python.exe"), ["-c", "from app.db import database_settings; from urllib.parse import urlsplit; import sys; print(urlsplit(database_settings(sys.argv[1])[0]).hostname)", dirname(configuration)], { windowsHide: true, env: environment });
  expectedHost = stdout.trim();
}
if (integrations) {
  assert.ok(configuration && process.env.BIM_TEST_R2_CONFIG && process.env.BIM_TEST_AI_CONFIG, "Live integrations need explicitly selected private settings files.");
  for (const [source, target] of [[process.env.BIM_TEST_R2_CONFIG, "r2.dpapi"], [process.env.BIM_TEST_AI_CONFIG, "ai.dpapi"]]) await copyFile(source, resolve(dataDirectory, target));
}
assert.equal(await online(endpoint + "/json/version"), false, "Native test port is already in use.");
assert.equal(await online("http://127.0.0.1:1420"), false, "Stop the dev server before verifying the packaged app.");

async function start() {
  const state = { closed: false, browser: null, page: null, health: null, spawnError: null };
  state.app = spawn(executable, [], {
    cwd: root, windowsHide: true, stdio: "ignore",
    env: { ...environment, BIM_DATABASE: database, BIM_DATA_DIR: dataDirectory, WEBVIEW2_USER_DATA_FOLDER: resolve(root, "webview"), WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: "--remote-debugging-port=9327 --remote-debugging-address=127.0.0.1" },
  });
  current = state;
  state.app.once("exit", () => { state.closed = true; });
  state.app.once("error", error => { state.spawnError = error; });
  for (let attempt = 0; attempt < 100; attempt++) {
    if (state.spawnError) throw state.spawnError;
    assert.equal(state.closed, false, "The Windows app exited before startup.");
    if (await online(endpoint + "/json/version")) break;
    await delay(200);
  }
  state.browser = await chromium.connectOverCDP(endpoint);
  const context = state.browser.contexts()[0];
  state.page = context.pages()[0] || await context.waitForEvent("page");
  state.page.on("pageerror", error => errors.push(error.message));
  state.page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  state.page.on("request", request => { if (/^http:\/\/127\.0\.0\.1:\d+\/api\/health$/.test(request.url())) state.health = request.url(); });
  await state.page.waitForURL(/tauri\.localhost/); await state.page.reload();
  await signIn(state.page);
  await state.page.getByRole("button", { name: "Kiểm tra hồ sơ", exact: true }).click();
  await state.page.getByText("Sẵn sàng kiểm tra", { exact: true }).waitFor({ timeout: 30000 });
  assert.match(state.page.url(), /^https?:\/\/tauri\.localhost\//);
  assert.ok(state.health);
  assert.equal((await fetch(state.health).then(response => response.json())).version, version);
  return state.page;
}

async function close() {
  const { stdout } = await run("powershell.exe", ["-NoProfile", "-Command", `(Get-Process -Id ${current.app.pid}).CloseMainWindow()`], { windowsHide: true });
  assert.match(stdout, /True/i, "Windows must accept a normal close.");
  for (let attempt = 0; attempt < 100 && !current.closed; attempt++) await delay(100);
  assert.equal(current.closed, true, "App shutdown did not finish.");
  assert.ok(current.health, "The app must contact its local processor.");
  assert.equal(await online(current.health), false, "Processor must stop with the app.");
  assert.equal((await readdir(resolve(dataDirectory, "tmp"), { recursive: true }).catch(() => [])).some(name => /source\.(ifc|pdf|dxf|dwg)$/.test(name)), false);
  await current.browser?.close().catch(() => {});
  for (let attempt = 0; attempt < 50 && await online(endpoint + "/json/version"); attempt++) await delay(100);
  assert.equal(await online(endpoint + "/json/version"), false);
}

try {
  let page = await start();
  let projects = page.getByRole("region", { name: "Quản lý dự án và lịch sử" });
  await projects.getByLabel("Dự án mới").fill("Windows restart pilot");
  await projects.getByRole("button", { name: "Tạo dự án", exact: true }).click();
  await projects.getByText("Dự án: Windows restart pilot", { exact: true }).waitFor();
  await expect(projects.locator(".project-intro")).toContainText("lưu theo dự án");
  const projectId = await projects.getByLabel("Dự án đang mở").inputValue();
  await uploadSyntheticFixture(page, "pilot");
  await page.getByText("Danh sách hiện có 4 tệp.", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Bắt đầu kiểm tra", exact: true }).click();
  await page.getByText("Đã xử lý 4/4 tệp", { exact: true }).waitFor({ timeout: 90000 });
  let coordination = page.getByRole("region", { name: "Phối hợp bản vẽ và mô hình" });
  await coordination.getByText("Đã hiển thị 3/3 mô hình", { exact: true }).waitFor({ timeout: 30000 });
  await coordination.getByLabel("Tên dự án phối hợp").fill("Windows restart pilot");
  await coordination.getByRole("button", { name: "So trục XY", exact: true }).click();
  await coordination.getByText("Khớp 2/2 trục XY", { exact: true }).waitFor();
  await coordination.getByLabel("Tôi xác nhận bản vẽ và mô hình cùng công trình và đúng tầng").check();
  await coordination.getByRole("button", { name: "Xác nhận và lưu liên kết", exact: true }).click();
  await coordination.getByText("Đã lưu liên kết tầng", { exact: true }).waitFor();
  let clashes = page.getByRole("region", { name: "Kiểm tra va chạm 3D" });
  await clashes.getByLabel("Tôi đã kiểm tra các IFC cùng công trình và hệ tọa độ").check();
  await clashes.getByRole("button", { name: "Chạy kiểm tra va chạm", exact: true }).click();
  await clashes.getByText("Đã kiểm tra một phần — cần xem lại", { exact: true }).waitFor({ timeout: 60000 });
  await clashes.getByLabel("Lọc loại va chạm").selectOption("intersection");
  assert.equal(await clashes.getByTestId("clash-row").count(), 20);
  await clashes.getByRole("button", { name: "Rà soát cặp 1", exact: true }).click();
  const review = clashes.getByRole("region", { name: "Rà soát xung đột" });
  await expect(review.getByLabel("Người rà soát")).toHaveAttribute("readonly", "");
  await review.getByLabel("Trạng thái rà soát").selectOption("needs_fix");
  await review.getByLabel("Nhận xét").fill("Native review persists after process restart");
  await review.getByRole("button", { name: "Lưu rà soát", exact: true }).click();
  await review.getByText("Đã lưu rà soát.", { exact: true }).waitFor();
  if (integrations) {
    const ai = clashes.getByRole("region", { name: "Đề xuất Qwen cho xung đột" });
    await expect(ai.getByRole("button", { name: "Tạo đề xuất bằng Qwen", exact: true })).toBeEnabled();
    const generated = page.waitForResponse(response => response.request().method() === "POST" && /\/advice$/.test(new URL(response.url()).pathname), { timeout: 190000 });
    await ai.getByRole("button", { name: "Tạo đề xuất bằng Qwen", exact: true }).click();
    const generatedResponse = await generated;
    const advice = await generatedResponse.json();
    assert.equal(generatedResponse.status(), 200, JSON.stringify(advice));
    assert.equal(advice.metrics.weights_verified, true);
    assert.equal(advice.model.fine_tuned, false);
    await ai.getByTestId("ai-result").waitFor();
  await expect(ai.getByLabel("Người phản hồi đề xuất")).toHaveAttribute("readonly", "");
    await ai.getByLabel("Nhận xét đề xuất").fill("Native Qwen response retained for human design review.");
    await ai.getByRole("button", { name: "Lưu phản hồi đề xuất", exact: true }).click();
    await ai.getByText("Đã lưu phản hồi về đề xuất. Nhãn xung đột giữ theo kết quả rà soát riêng.", { exact: true }).waitFor();
    await ai.screenshot({ path: resolve(root, "qwen-native.png") });
    const cloud = projects.getByRole("region", { name: "Lưu tệp R2" });
    const synchronized = page.waitForResponse(response => response.request().method() === "POST" && /\/storage\/sync$/.test(new URL(response.url()).pathname), { timeout: 150000 });
    await cloud.getByRole("button", { name: "Đồng bộ dự án lên R2", exact: true }).click();
    const syncResponse = await synchronized;
    const sync = await syncResponse.json();
    assert.equal(syncResponse.status(), 200, JSON.stringify(sync));
    assert.equal(sync.status, "verified", JSON.stringify(sync));
    await cloud.getByText(`Đã xác minh ${sync.verified_files}/${sync.total_files} tệp.`, { exact: true }).waitFor();
    await expect(cloud.getByRole("button", { name: "Đồng bộ dự án lên R2", exact: true })).toBeEnabled({ timeout: 15000 });
    await cloud.screenshot({ path: resolve(root, "r2-native.png") });
    integrationEvidence = { advice_id: advice.id, ai_metrics: advice.metrics, synchronized: sync, cache_restored: false };
  }
  let cases = clashes.getByRole("region", { name: "Bộ ca gán nhãn" });
  await cases.getByLabel("Lọc nhãn phân tích").selectOption("no_clash");
  await cases.getByTestId("pilot-case-row").first().getByRole("button", { name: "Rà soát ca", exact: true }).click();
  const caseReview = cases.getByRole("region", { name: "Rà soát ca dữ liệu" });
  await expect(caseReview.getByLabel("Người rà soát")).toHaveAttribute("readonly", "");
  await caseReview.getByLabel("Nhãn sau rà soát").selectOption("no_clash");
  await caseReview.getByLabel("Nhận xét").fill("Native negative case review persists");
  await caseReview.getByRole("button", { name: "Lưu nhãn ca", exact: true }).click();
  await caseReview.getByText("Đã lưu nhãn ca.", { exact: true }).waitFor();
  const preference = await workspacePreference(page);
  assert.equal(preference.project_id, projectId);
  assert.match(preference.run_id, /^[a-f0-9]{32}$/);
  await page.getByRole("button", {name:"Tài khoản của tôi",exact:true}).click();
  const profile=page.getByRole("form", {name:"Chỉnh sửa hồ sơ"});
  await profile.getByLabel("Tên hiển thị", {exact:true}).fill("Native profile reviewer");
  await profile.getByLabel("Email liên hệ", {exact:true}).fill("native-profile@example.org");
  await profile.getByRole("button", {name:"Lưu hồ sơ",exact:true}).click();
  await expect(profile.getByRole("status")).toHaveText("Đã lưu hồ sơ cá nhân.");
  await expect(page.locator(".work-topbar-user")).toContainText("Native profile reviewer");
  await expect(page.locator(".residence-tools")).toHaveCount(0);
  await page.screenshot({path:resolve(root,"profile-native.png"),fullPage:true});
  await page.setViewportSize({width:375,height:812});
  await page.locator("h1").click();await page.evaluate(()=>window.scrollTo(0,0));await delay(400);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.screenshot({path:resolve(root,"profile-native-375.png"),fullPage:true});
  await page.setViewportSize({width:1440,height:1000});
  await close();

  if (integrations) {
    dataDirectory = resolve(root, "fresh-cache");
    await mkdir(dataDirectory);
    for (const component of ["database", "r2", "ai"]) await copyFile(resolve(root, "data", `${component}.dpapi`), resolve(dataDirectory, `${component}.dpapi`));
    assert.deepEqual((await readdir(dataDirectory)).sort(), ["ai.dpapi", "database.dpapi", "r2.dpapi"]);
  }

  page = await start();
  await page.getByRole("button", {name:"Tài khoản của tôi",exact:true}).click();
  const restoredProfile=page.getByRole("form", {name:"Chỉnh sửa hồ sơ"});
  await expect(restoredProfile.getByLabel("Tên hiển thị", {exact:true})).toHaveValue("Native profile reviewer");
  await expect(restoredProfile.getByLabel("Email liên hệ", {exact:true})).toHaveValue("native-profile@example.org");
  await page.getByRole("button", {name:"Kiểm tra hồ sơ",exact:true}).click();
  projects = page.getByRole("region", { name: "Quản lý dự án và lịch sử" });
  await projects.getByText("Dự án: Windows restart pilot", { exact: true }).waitFor({ timeout: 30000 });
  coordination = page.getByRole("region", { name: "Phối hợp bản vẽ và mô hình" });
  await coordination.getByText("Đã hiển thị 3/3 mô hình", { exact: true }).waitFor({ timeout: 30000 });
  await coordination.getByText("Đã lưu liên kết tầng", { exact: true }).waitFor();
  clashes = page.getByRole("region", { name: "Kiểm tra va chạm 3D" });
  await clashes.getByText("Đã kiểm tra một phần — cần xem lại", { exact: true }).waitFor();
  assert.equal(await clashes.getByLabel("Tôi đã kiểm tra các IFC cùng công trình và hệ tọa độ").isChecked(), false);
  await clashes.getByLabel("Lọc trạng thái rà soát").selectOption("needs_fix");
  assert.equal(await clashes.getByTestId("clash-row").count(), 1);
  await clashes.getByRole("button", { name: "Rà soát cặp 1", exact: true }).click();
  await expect(clashes.getByRole("region", { name: "Rà soát xung đột" }).getByLabel("Nhận xét")).toHaveValue("Native review persists after process restart");
  if (integrations) {
    const ai = clashes.getByRole("region", { name: "Đề xuất Qwen cho xung đột" });
    await ai.getByTestId("ai-result").waitFor();
    await expect(ai.getByLabel("Nhận xét đề xuất")).toHaveValue("Native Qwen response retained for human design review.");
    assert.equal(await ai.getByLabel("Đề xuất đã lưu").inputValue(), integrationEvidence.advice_id);
    assert.ok((await readdir(resolve(dataDirectory, "assets"), { recursive: true })).some(name => name.endsWith("model.glb")));
    await ai.screenshot({ path: resolve(root, "qwen-restored-native.png") });
    await page.setViewportSize({ width: 375, height: 812 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await ai.screenshot({ path: resolve(root, "qwen-native-375.png") });
    await page.setViewportSize({ width: 1440, height: 1000 });
    integrationEvidence.cache_restored = true;
  }
  cases = clashes.getByRole("region", { name: "Bộ ca gán nhãn" });
  await cases.getByLabel("Lọc trạng thái nhãn", { exact: true }).selectOption("reviewed");
  assert.equal(await cases.getByTestId("pilot-case-row").count(), 1);
  await cases.getByTestId("pilot-case-row").first().getByRole("button", { name: "Rà soát ca", exact: true }).click();
  await expect(cases.getByRole("region", { name: "Rà soát ca dữ liệu" }).getByLabel("Nhận xét")).toHaveValue("Native negative case review persists");
  await clashes.getByRole("button", { name: "Xem va chạm 1 trong 3D", exact: true }).click();
  await coordination.getByTestId("cad-clash-marker").waitFor();
  await expect(coordination.locator(".ifc-canvas")).toBeInViewport({ ratio: .5 });
  await page.screenshot({ path: resolve(root, "restored-native.png") });
  assert.deepEqual(await workspacePreference(page), preference);
  assert.deepEqual(errors, []);
  await page.getByRole("button", { name: "Mô hình minh họa", exact: true }).click();
  await expect(page.locator(".work-model-grid>button")).toHaveCount(14);
  for (const image of await page.locator(".work-model-grid img").all()) {
    await image.scrollIntoViewIfNeeded();
    await expect.poll(() => image.evaluate(element => element.complete && element.naturalWidth > 0)).toBeTruthy();
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: resolve(root, "gallery-native.png"), fullPage: true });
  await page.locator(".work-model-grid>button").first().click();
  const house=page.getByRole("dialog").locator(".residence");
  await expect(house.locator("canvas")).toBeVisible();
  await expect(page.locator(".residence-tools")).toHaveCount(0);
  await page.emulateMedia({reducedMotion:"no-preference"});
  await house.locator("canvas").focus();await page.keyboard.press("ArrowRight");
  await expect(house).toHaveAttribute("data-motion","paused");
  await expect(house).toHaveAttribute("data-motion","playing",{timeout:6000});
  await page.screenshot({path:resolve(root,"model-native-no-toolbar.png"),fullPage:true});
  await page.keyboard.press("Escape");
  await page.getByRole("navigation").getByRole("button",{name:"Tài khoản",exact:true}).click();
  await page.getByRole("button",{name:"Cấp tài khoản",exact:true}).click();
  const provision=page.getByRole("region",{name:"Cấp tài khoản giảng viên và sinh viên"});
  const studentCode=`00${stamp}`,studentEmail=`native-student-${stamp}@example.org`,studentPassword="Native-student-changed-password-123!";
  await provision.getByLabel(/Loại tài khoản/).selectOption("student");
  await provision.getByLabel("Họ và tên",{exact:true}).fill("Native Student");
  await provision.getByLabel("Mã giảng viên hoặc sinh viên",{exact:true}).fill(studentCode);
  await provision.getByLabel("Email tài khoản",{exact:true}).fill(studentEmail);
  const accountDownload=page.waitForEvent("download");
  await provision.getByRole("button",{name:"Cấp tài khoản và tải Excel",exact:true}).click();
  const accountFile=resolve(root,"native-accounts.xlsx");await(await accountDownload).saveAs(accountFile);
  const passwordResult=await run(resolve(".venv/Scripts/python.exe"),["-c","import sys;from openpyxl import load_workbook;b=load_workbook(sys.argv[1]);r=list(b.active.values);print(r[1][r[0].index(sys.argv[2])]);b.close()",accountFile,"Mật khẩu tạm"],{windowsHide:true});
  const temporaryPassword=passwordResult.stdout.trim();assert.ok(temporaryPassword.length>=12);
  await provision.getByRole("button",{name:"Import Excel",exact:true}).click();
  const excelFixture=resolve(root,"native-teachers-input.xlsx");
  await run(resolve(".venv/Scripts/python.exe"),["-c","import sys,json;from openpyxl import Workbook;b=Workbook();s=b.active\nfor r in json.loads(sys.argv[1]):s.append(r)\nb.save(sys.argv[2]);b.close()",JSON.stringify([["Họ và tên","Mã giảng viên","email"],["Native Teacher",`001${stamp}`,`native-teacher-${stamp}@example.org`]]),excelFixture],{windowsHide:true});
  await provision.getByLabel("File Excel cấp tài khoản",{exact:true}).setInputFiles(excelFixture);
  const bulkButton=provision.getByRole("button",{name:"Cấp 1 tài khoản và tải Excel",exact:true});await expect(bulkButton).toBeEnabled();
  const bulkDownload=page.waitForEvent("download");await bulkButton.click();await(await bulkDownload).saveAs(resolve(root,"native-teachers-export.xlsx"));
  await page.locator("h1").click();await page.evaluate(()=>window.scrollTo(0,0));await delay(300);
  await page.screenshot({path:resolve(root,"accounts-admin-native.png"),fullPage:true});
  await page.getByRole("button",{name:"Đăng xuất",exact:true}).click();
  async function studentLogin(identifier,password){
    await page.getByLabel("Tên đăng nhập",{exact:true}).fill(identifier);await page.getByLabel("Mật khẩu",{exact:true}).fill(password);
    await page.getByRole("button",{name:"Đăng nhập",exact:true}).click();
  }
  await studentLogin(studentCode,temporaryPassword);
  const forced=page.getByRole("form",{name:"Đổi mật khẩu lần đầu"});await expect(forced).toBeVisible();
  assert.equal(await page.getByRole("navigation").count(),0);
  await forced.getByLabel("Mật khẩu mới",{exact:true}).fill(studentPassword);await forced.getByLabel("Xác nhận mật khẩu mới",{exact:true}).fill(studentPassword);
  await forced.getByRole("button",{name:"Đổi mật khẩu và tiếp tục",exact:true}).click();
  await expect(page.getByRole("heading",{name:"Không gian thực hành BIM",exact:true})).toBeVisible();
  await page.getByRole("button",{name:"Đăng xuất",exact:true}).click();await studentLogin(studentEmail,studentPassword);
  await expect(page.getByRole("heading",{name:"Không gian thực hành BIM",exact:true})).toBeVisible();
  await page.setViewportSize({width:375,height:600});await page.getByRole("button",{name:"Mở menu",exact:true}).click();
  assert.equal(await page.locator(".work-sidebar").evaluate(sidebar=>sidebar.scrollHeight<=sidebar.clientHeight+1),true);
  await expect(page.getByRole("button",{name:"Tài khoản của tôi",exact:true})).toBeInViewport();
  await page.screenshot({path:resolve(root,"sidebar-student-native-375x600.png")});
  assert.deepEqual(errors, []);
  await close();
  assert.equal(createHash("sha256").update(await readFile(executable)).digest("hex"), executableHash, "The tested binary must not change during verification.");
  const result = { status: "passed", executable, binary_sha256: executableHash, root, database, mongodb_host: expectedHost, private_configuration_loaded: !!configuration, project_id: projectId, run_id: preference.run_id, integrations: integrationEvidence, checks: ["native individual and Excel provisioning with credential export", "student first password change and code/email login", "375x600 sidebar without scrolling", "own profile save and persistence across native restart", "decorative toolbar absent", "production CSP and bundled processor", "MongoDB source revisions, history and 60-case pilot", "issue and negative-case reviews", "normal close and processor shutdown twice", "restart with same isolated profile restores exact sources, run, drawing link and reviews", "new-run coordinate confirmation stays unchecked", "3D pair highlight and CAD pin", "no console/runtime errors"], installed: false, expert_accepted: false };
  await writeFile(resolve(root, "result.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
} catch (error) {
  await current?.page?.screenshot({ path: resolve(root, "failure.png"), fullPage: true }).catch(() => {});
  throw error;
} finally {
  if (current?.app.pid && !current.closed) await run("taskkill", ["/PID", String(current.app.pid), "/T", "/F"], { windowsHide: true }).catch(() => {});
  await current?.browser?.close().catch(() => {});
  if (!configuration) await cleanLocalTestDatabase(database);
}

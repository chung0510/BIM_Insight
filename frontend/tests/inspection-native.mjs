import { signIn, cleanLocalTestDatabase, openTestProject, uploadSyntheticFixture } from "./account-helper.mjs";
import { chromium, expect } from "@playwright/test";
import assert from "node:assert/strict";
import { execFile, spawn } from "node:child_process";
import { mkdir, readdir, writeFile } from "node:fs/promises";
import { resolve, basename } from "node:path";
import { promisify } from "node:util";

assert.equal(
  process.platform,
  "win32",
  "This check requires Windows/WebView2.",
);
const run = promisify(execFile);
const stamp=Date.now();
const database=`bim_insight_test_native_upload_${stamp}`;
process.env.BIM_UI_TEST="1";
const root = resolve(`data/artifacts/inspection/native-${stamp}`);
const executable = resolve("src-tauri/target/release/bim_insight.exe");
const fixtures = resolve(root, "fixtures");
const endpoint = "http://127.0.0.1:9326";
const delay = (ms) => new Promise((done) => setTimeout(done, ms));
await mkdir(root, { recursive: true });
await run(
  resolve(".venv/Scripts/python.exe"),
  ["frontend/tests/make_inspection_fixtures.py", fixtures],
  { windowsHide: true },
);
assert.equal(
  await fetch(`${endpoint}/json/version`).then(
    () => true,
    () => false,
  ),
  false,
  "The native test debugging port is already in use.",
);
assert.equal(
  await fetch("http://127.0.0.1:1420").then(
    () => true,
    () => false,
  ),
  false,
  "Stop the dev server before verifying the packaged Windows app.",
);
const app = spawn(executable, [], {
  cwd: root,
  windowsHide: true,
  stdio: "ignore",
  env: {
    ...process.env,
    BIM_DATA_DIR: resolve(root, "data"),
    BIM_MONGODB_URI:"mongodb://127.0.0.1:27017", BIM_DATABASE:database,
    WEBVIEW2_USER_DATA_FOLDER: resolve(root, "webview"),
    WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:
      "--remote-debugging-port=9326 --remote-debugging-address=127.0.0.1",
  },
});
let closed = false;
let spawnError;
app.once("exit", () => {
  closed = true;
});
app.once("error", (error) => {
  spawnError = error;
});
let browser;
let page;
try {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (spawnError) throw spawnError;
    assert.equal(closed, false, "The Windows app exited before startup.");
    if (
      await fetch(`${endpoint}/json/version`).then(
        () => true,
        () => false,
      )
    )
      break;
    await delay(200);
  }
  browser = await chromium.connectOverCDP(endpoint);
  const context = browser.contexts()[0];
  page = context.pages()[0] || (await context.waitForEvent("page"));
  const errors = [];
  let processorHealth;
  page.on("request", (request) => {
    if (/^http:\/\/127\.0\.0\.1:\d+\/api\/health$/.test(request.url()))
      processorHealth = request.url();
  });
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.waitForURL(/tauri\.localhost/); await page.reload();
  await signIn(page);
  await page
    .getByRole("button", { name: "Kiểm tra hồ sơ", exact: true })
    .click();
  await page
    .getByText("Sẵn sàng kiểm tra", { exact: true })
    .waitFor({ timeout: 30000 });
  assert.match(page.url(), /^https?:\/\/tauri\.localhost\//);
  await openTestProject(page, "Native file inspection");
  await page
    .getByLabel("Chọn tệp IFC, PDF, DXF hoặc DWG")
    .setInputFiles([
      resolve(fixtures, "ARCH.ifc"),
      resolve(fixtures, "drawing.pdf"),
      resolve(fixtures, "floor.dxf"),
    ]);
  assert.equal(await page.getByLabel("Bộ môn của ARCH.ifc").count(), 0);
  await page
    .getByRole("button", { name: "Bắt đầu kiểm tra", exact: true })
    .click();
  await page
    .getByText("Đã xử lý 3/3 tệp", { exact: true })
    .waitFor({ timeout: 60000 });
  assert.equal(
    await page
      .locator(".inspection-file")
      .getByText("Đọc được", { exact: true })
      .count(),
    3,
  );
  await page
    .getByRole("button", { name: "Xem kết quả drawing.pdf", exact: true })
    .click();
  await page.getByText("ARCH Level 1 - grid A", { exact: true }).waitFor();
  const coordination = page.getByRole("region", { name: "Phối hợp bản vẽ và mô hình" });
  await coordination.getByText("Đã hiển thị 1/1 mô hình", { exact: true }).waitFor({ timeout: 30000 });
  assert.ok(await coordination.locator("svg[aria-label='Bản vẽ DXF của bạn'] path").count() > 0);
  await coordination.getByLabel("Chọn cấu kiện IFC").selectOption({ index: 1 });
  await coordination.getByTestId("ifc-selection").getByText("Synthetic wall", { exact: true }).waitFor();
  await page.screenshot({ path: resolve(root, "native.png") });
  if (process.env.BIM_NATIVE_DWG_INPUT) {
    const dwg = resolve(process.env.BIM_NATIVE_DWG_INPUT);
    await page.getByLabel("Chọn tệp IFC, PDF, DXF hoặc DWG").setInputFiles(dwg);
    await page.getByRole("button", {name:"Bắt đầu kiểm tra",exact:true}).click();
    await page.getByText("Đã xử lý 4/4 tệp", {exact:true}).waitFor({timeout:120000});
    await page.getByRole("button", {name:`Xem kết quả ${basename(dwg)}`,exact:true}).click();
    await expect(page.locator(".inspection-detail-content")).toContainText("Đã chuyển DWG bằng ODA File Converter");
    await coordination.getByLabel("Bản vẽ CAD phối hợp").selectOption({label:basename(dwg)});
    await coordination.getByRole("img", {name:"Bản vẽ DXF của bạn"}).locator("path").first().waitFor({state:"attached"});
    await coordination.screenshot({path:resolve(root,"native-real-dwg.png")});
  }
  await openTestProject(page, "Native synthetic regression");
  await uploadSyntheticFixture(page);
  await page.getByRole("button", { name: "Bắt đầu kiểm tra", exact: true }).click();
  await page.getByText("Đã xử lý 4/4 tệp", { exact: true }).waitFor({ timeout: 60000 });
  await coordination.getByText("Đã hiển thị 3/3 mô hình", { exact: true }).waitFor({ timeout: 30000 });
  const clashes = page.getByRole("region", { name: "Kiểm tra va chạm 3D" });
  await clashes.getByLabel("Tôi đã kiểm tra các IFC cùng công trình và hệ tọa độ").check();
  await clashes.getByRole("button", { name: "Chạy kiểm tra va chạm", exact: true }).click();
  await clashes.getByText("Hoàn tất trong phạm vi đã chọn", { exact: true }).waitFor({ timeout: 30000 });
  assert.equal(await clashes.getByTestId("clash-row").count(), 2);
  await clashes.getByRole("button", { name: "Xem va chạm 1 trong 3D", exact: true }).click();
  await coordination.getByText("Đang cô lập 2 cấu kiện", { exact: true }).waitFor();
  await expect(coordination.locator(".ifc-canvas")).toBeInViewport({ ratio: .5 });
  assert.equal(await coordination.getByTestId("clash-selection").locator("code").count(), 2);
  await clashes.getByTestId("clash-row").filter({ hasText: "DEMO contained: pipe" }).getByRole("button", { name: /^Xem va chạm/ }).click();
  await expect(coordination.locator(".ifc-canvas")).toBeInViewport({ ratio: .5 });
  const containedImage = resolve(root, "contained.png");
  await coordination.locator(".ifc-canvas").screenshot({ path: containedImage });
  const { stdout: colorsJson } = await run(resolve(".venv/Scripts/python.exe"), ["-c", "import json,sys; from PIL import Image; pixels=list(Image.open(sys.argv[1]).convert('RGB').getdata()); print(json.dumps({'rust':sum(r-g>15 and g-b>15 and r-b>40 for r,g,b in pixels),'teal':sum(g-r>12 and b-r>8 for r,g,b in pixels)}))", containedImage], { windowsHide: true });
  const colors = JSON.parse(colorsJson);
  assert.ok(colors.rust > 30 && colors.teal > 30, `Both contained partners must be visible in WebView2: ${colorsJson}`);
  await page.screenshot({ path: resolve(root, "native-clash.png") });
  await page
    .getByLabel("Chọn tệp IFC, PDF, DXF hoặc DWG")
    .setInputFiles(resolve(fixtures, "close-during-check.ifc"));
  await page
    .getByRole("button", { name: "Bắt đầu kiểm tra", exact: true })
    .click();
  const temporary = resolve(root, "data/tmp");
  let sources = [];
  for (let attempt = 0; attempt < 100; attempt++) {
    sources = (
      await readdir(temporary, { recursive: true }).catch(() => [])
    ).filter((name) => /source\.(ifc|pdf)$/.test(name));
    if (sources.length) break;
    await delay(50);
  }
  assert.ok(
    sources.length,
    "The close test must interrupt a real copied input.",
  );
  await page
    .locator(".inspection-file")
    .filter({ hasText: "close-during-check.ifc" })
    .getByText("Đang kiểm tra", { exact: true })
    .waitFor();
  // The app is closed through its window so Tauri's normal shutdown runs.
  const { stdout } = await run(
    "powershell.exe",
    [
      "-NoProfile",
      "-Command",
      `(Get-Process -Id ${app.pid}).CloseMainWindow()`,
    ],
    { windowsHide: true },
  );
  assert.match(stdout, /True/i, "Windows must accept a normal window close.");
  for (let attempt = 0; attempt < 100 && !closed; attempt++) await delay(100);
  assert.equal(closed, true, "The app did not finish its shutdown.");
  assert.ok(
    processorHealth,
    "The native app must contact its local processor.",
  );
  assert.equal(
    await fetch(processorHealth).then(
      () => true,
      () => false,
    ),
    false,
    "The local processor must stop with its app.",
  );
  const leftovers = await readdir(temporary, { recursive: true }).catch(
    () => [],
  );
  assert.equal(
    leftovers.some((name) => name.startsWith("session-")),
    false,
    `Temporary session remains after closing: ${leftovers.join(", ")}`,
  );
  assert.deepEqual(errors, []);
  await writeFile(
    resolve(root, "result.json"),
    JSON.stringify(
      {
        status: "passed",
        executable,
        cwd: root,
        checks: [
          "production WebView2 and CSP",
          "dev server stopped",
          "packaged IFC/PDF/DXF processor",
          "DXF preview and IFC GLB GUID selection under production CSP",
          "packaged synthetic IFC import and isolated clash worker: two hard findings",
          "two source/GUID highlights and source group isolation",
          "enclosed partner visible through a translucent host",
          "real file upload",
          "PDF text",
          "normal close during IFC processing",
          "local processor stops with app",
          "temporary session cleanup",
        ],
        source_kind: process.env.BIM_NATIVE_DWG_INPUT ? "synthetic_regressions_and_user_dwg" : "synthetic",
        real_dwg_conversion: !!process.env.BIM_NATIVE_DWG_INPUT,
        contained_visible_pixels: colors,
        installed: false,
      },
      null,
      2,
    ),
  );
  console.log(
    `PASS: native Windows upload and close/cleanup; evidence in ${root}`,
  );
} catch (error) {
  await page
    ?.screenshot({ path: resolve(root, "failure.png") })
    .catch(() => {});
  throw error;
} finally {
  if (!closed && app.pid) {
    await run("taskkill", ["/PID", String(app.pid), "/T", "/F"], {
      windowsHide: true,
    }).catch(() => {});
  }
  await browser?.close().catch(() => {});
  await cleanLocalTestDatabase(database);
}

import { signIn, openTestProject } from "./account-helper.mjs";
import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir, readFile, readdir } from "node:fs/promises";
import { resolve } from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

await mkdir("data/artifacts/inspection", { recursive: true });
const fixtures = resolve(`data/artifacts/inspection/fixtures-${Date.now()}`);
await promisify(execFile)(
  resolve(
    process.platform === "win32"
      ? ".venv/Scripts/python.exe"
      : ".venv/bin/python",
  ),
  ["frontend/tests/make_inspection_fixtures.py", fixtures],
  { windowsHide: true },
);
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,
});
const page = await browser.newPage({ viewport: { width: 1536, height: 1060 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
try {
  await page.goto("http://127.0.0.1:1420/#inspection");
  await signIn(page);
  await page
    .getByRole("heading", { name: "Kiểm tra hồ sơ", exact: true })
    .waitFor();
  await page.getByText("Sẵn sàng kiểm tra", { exact: true }).waitFor();
  await openTestProject(page);
  assert.equal(
    await page
      .getByRole("button", { name: "Bắt đầu kiểm tra", exact: true })
      .isDisabled(),
    true,
  );
  await page.getByLabel("Chọn tệp IFC, PDF, DXF hoặc DWG").setInputFiles({
    name: "model.rvt",
    mimeType: "application/octet-stream",
    buffer: Buffer.from("unsupported"),
  });
  await page
    .getByRole("alert")
    .filter({ hasText: "Xuất RVT/RTE sang IFC" })
    .waitFor();
  await page
    .getByLabel("Chọn tệp IFC, PDF, DXF hoặc DWG")
    .setInputFiles([
      resolve(fixtures, "ARCH.ifc"),
      resolve(fixtures, "drawing.pdf"),
      resolve(fixtures, "blank.pdf"),
    ]);
  assert.equal(await page.locator(".inspection-file").count(), 3);
  assert.equal(await page.getByLabel("Bộ môn của ARCH.ifc").count(), 0);
  await page
    .getByRole("button", { name: "Bắt đầu kiểm tra", exact: true })
    .click();
  await page
    .getByText("Đã xử lý 3/3 tệp", { exact: true })
    .waitFor({ timeout: 60000 });
  const ifc = page.locator(".inspection-file").filter({ hasText: "ARCH.ifc" });
  await ifc.getByText("Đọc được", { exact: true }).waitFor();
  await page
    .getByRole("button", { name: "Xem kết quả ARCH.ifc", exact: true })
    .click();
  await page
    .locator(".inspection-type-list")
    .getByText("IfcWall", { exact: false })
    .waitFor();
  assert.equal(await page.getByText("1 cấu kiện", { exact: true }).count(), 1);
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Tải báo cáo JSON" }).click();
  const download = await downloadPromise;
  const report = JSON.parse(await readFile(await download.path(), "utf8"));
  assert.equal(report.kind, "ifc");
  assert.equal(report.discipline, "ARCH");
  assert.equal(report.result.element_count, 1);
  assert.equal(report.clash_detection, "not_run");
  await page
    .getByRole("button", { name: "Xem kết quả drawing.pdf", exact: true })
    .click();
  await page.getByText("ARCH Level 1 - grid A", { exact: true }).waitFor();
  await page
    .getByRole("button", { name: "Xem kết quả blank.pdf", exact: true })
    .click();
  await page.getByText(/Không tìm thấy chữ/).waitFor();
  await page.getByRole("button", { name: "Thư viện bản vẽ", exact: true }).click();
  await page
    .getByRole("button", { name: "Kiểm tra hồ sơ", exact: true })
    .click();
  assert.equal(await page.locator(".inspection-file").count(), 3);
  await page.screenshot({
    path: "data/artifacts/inspection/desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 375, height: 812 });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    true,
  );
  await page.screenshot({
    path: "data/artifacts/inspection/mobile.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 1536, height: 1060 });
  assert.equal(
    await page
      .getByRole("button", { name: "Đã xử lý các tệp", exact: true })
      .isDisabled(),
    true,
  );
  await page.getByLabel("Chọn tệp IFC, PDF, DXF hoặc DWG").setInputFiles({
    name: "bad.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("not a PDF"),
  });
  await page
    .getByRole("button", { name: "Xem kết quả bad.pdf", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Bắt đầu kiểm tra", exact: true })
    .click();
  await page
    .getByText(
      "Nội dung không đúng định dạng IFC/PDF/DXF/DWG. Hãy kiểm tra hoặc xuất lại tệp.",
      { exact: true },
    )
    .waitFor();
  const retry = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/inspections") &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Thử lại tệp lỗi", exact: true })
    .click();
  assert.equal((await retry).status(), 422);
  await page.getByRole("button", { name: "Bỏ bad.pdf", exact: true }).click();
  const ifcBytes = await readFile(resolve(fixtures, "ARCH.ifc"));
  await page.getByLabel("Chọn tệp IFC, PDF, DXF hoặc DWG").setInputFiles({
    name: "cancel.ifc",
    mimeType: "application/octet-stream",
    buffer: ifcBytes,
  });
  await page
    .getByRole("button", { name: "Bắt đầu kiểm tra", exact: true })
    .click();
  await page
    .locator(".inspection-file")
    .filter({ hasText: "cancel.ifc" })
    .getByText("Đang kiểm tra", { exact: true })
    .waitFor();
  await page.getByRole("button", { name: "Hủy kiểm tra", exact: true }).click();
  await page
    .locator(".inspection-file")
    .filter({ hasText: "cancel.ifc" })
    .getByText("Đã hủy", { exact: true })
    .waitFor();
  const pdfBytes = await readFile(resolve(fixtures, "drawing.pdf"));
  const transfer = await page.evaluateHandle(
    (bytes) => {
      const transfer = new DataTransfer();
      transfer.items.add(
        new File([new Uint8Array(bytes)], "dropped.pdf", {
          type: "application/pdf",
        }),
      );
      return transfer;
    },
    [...pdfBytes],
  );
  await page
    .locator(".inspection-dropzone")
    .dispatchEvent("drop", { dataTransfer: transfer });
  assert.equal(await page.locator(".inspection-file").count(), 5);
  await page
    .getByRole("button", { name: "Bắt đầu kiểm tra", exact: true })
    .click();
  await page
    .getByText("Đã xử lý 5/5 tệp", { exact: true })
    .waitFor({ timeout: 60000 });
  await page
    .locator(".inspection-file")
    .filter({ hasText: "cancel.ifc" })
    .getByText("Đọc được", { exact: true })
    .waitFor();
  await page
    .getByLabel("Chọn tệp IFC, PDF, DXF hoặc DWG")
    .setInputFiles(resolve(fixtures, "ARCH.ifc"));
  await page
    .getByRole("alert")
    .filter({ hasText: "đã có trong danh sách" })
    .waitFor();
  assert.equal(await page.locator(".inspection-file").count(), 5);
  await page.getByLabel("Chọn tệp IFC, PDF, DXF hoặc DWG").setInputFiles({
    name: "too-big.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.alloc(26 * 1024 * 1024),
  });
  await page
    .getByRole("alert")
    .filter({ hasText: "PDF tối đa 25 MiB" })
    .waitFor();
  const leftovers = await readdir("data/inspections/tmp", {
    recursive: true,
  }).catch(() => []);
  assert.equal(
    leftovers.some((name) => /source\.(ifc|pdf)$/.test(name)),
    false,
  );
  assert.deepEqual(errors, []);
  console.log(
    "PASS: real IFC/PDF upload, drag/drop, discipline, partial PDF, download, retry, cancellation, size/duplicate rejection, cleanup, persistence and mobile layout.",
  );
} catch (error) {
  await page.screenshot({
    path: "data/artifacts/inspection/failure.png",
    fullPage: true,
  });
  throw error;
} finally {
  await browser.close();
}

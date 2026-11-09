import { signIn } from "./account-helper.mjs";
import { chromium, expect } from "@playwright/test";
import assert from "node:assert/strict";

const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE });
const page = await browser.newPage();
await page.route("**/api/projects**", route => route.fulfill({ status: 503, json: { detail: "database_unavailable" } }));
const errors = [];
page.on("pageerror", error => errors.push(error.message));
try {
  await page.goto("http://127.0.0.1:1420/#inspection");
  const session=await signIn(page);
  await page.evaluate(user=>localStorage.setItem(`bim-insight.workspace.v1.${user.realm_id}.${user.id}`,JSON.stringify({project_id:"11111111-1111-4111-8111-111111111111",revision:"R01"})),session.user);
  await page.reload(); await signIn(page);
  await page.getByText("Sẵn sàng kiểm tra", { exact: true }).waitFor();
  await page.getByRole("alert").filter({ hasText: "MongoDB" }).waitFor();
  await expect(page.getByRole("button", { name: "Chọn tệp từ máy", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Mở phiên tạm", exact: true })).toHaveCount(0);
  await expect(page.getByLabel("Dự án đang mở")).toBeEnabled();
  await expect(page.getByRole("button", { name: "Tải lại", exact: true })).toBeEnabled();
  const atlas = await browser.newPage();
  await atlas.route("**/api/projects?**", route => route.fulfill({ json: { items: [], total: 0, offset: 0, storage: { database: "bim_insight", host: "cluster0.21qrqqs.mongodb.net" } } }));
  await atlas.goto("http://127.0.0.1:1420/#inspection");
  await signIn(atlas);
  await atlas.getByText("Sẵn sàng kiểm tra", { exact: true }).waitFor();
  await expect(atlas.locator(".project-intro")).toContainText("lưu theo dự án");
  await expect(atlas.getByRole("button", {name:"Chọn tệp từ máy", exact:true})).toBeDisabled();
  assert.deepEqual(errors, []);
  console.log("PASS: unavailable or absent project blocks uploads; project selection and retry remain available, with no temporary escape.");
} finally { await browser.close(); }

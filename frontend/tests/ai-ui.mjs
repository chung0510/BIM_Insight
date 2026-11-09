import { signIn, TEST_PASSWORD } from "./account-helper.mjs";
import { chromium, expect } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const origin = "http://127.0.0.1:1420";
assert.equal(process.env.BIM_UI_TEST, "1");
const session = await fetch(origin + "/api/auth/login", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username:"uiadmin",password:TEST_PASSWORD})}).then(r=>r.json());
const options = {headers:{"X-BIM-Session":session.session_token}};
const projects = await fetch(`${origin}/api/projects?limit=100`,options).then(response => response.json());
assert.equal(projects.storage.host, "127.0.0.1", "Run against the isolated local UI test server.");
const project = projects.items.find(item => item.name === "Pilot workspace test");
assert.ok(project, "Run test:projects to prepare its isolated pilot workspace first.");
const runs = await fetch(`${origin}/api/projects/${project.id}/runs?limit=1`,options).then(response => response.json());
const restored = await fetch(`${origin}/api/projects/${project.id}/runs/${runs.items[0].id}`,options).then(response => response.json());
const report = restored.report;
const output = resolve(`data/artifacts/integration/ui-ai-${Date.now()}`);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on("pageerror", error => errors.push(error.message));
await page.addInitScript(({key,preference}) => localStorage.setItem(key,JSON.stringify(preference)), {key:`bim-insight.workspace.v1.${session.user.realm_id}.${session.user.id}`,preference:{project_id:project.id,revision:"R01",run_id:report.id}});
await page.route("**/api/projects/ai/runtime", route => route.fulfill({ json: { configured: true, files_present: true } }));
let release, releaseReload, markReloadPending, delayReload = false, calls = 0, saved = null;
const gate = new Promise(done => { release = done; });
const reloadGate = new Promise(done => { releaseReload = done; });
const reloadPending = new Promise(done => { markReloadPending = done; });
await page.route("**/issues/*/advice**", async route => {
  const request = route.request();
  const url = new URL(request.url());
  if (request.method() === "GET") {
    if (delayReload) { markReloadPending(); await reloadGate; }
    return route.fulfill({ json: { items: saved ? [saved] : [], total: saved ? 1 : 0 } });
  }
  if (url.pathname.endsWith("/feedback")) {
    saved.feedback = { ...request.postDataJSON(), revision: request.postDataJSON().expected_revision + 1 };
    return route.fulfill({ json: saved.feedback });
  }
  calls++;
  if (calls === 1) { await gate; return route.fulfill({ json: {} }).catch(() => {}); }
  if (calls === 2) return route.fulfill({ status: 422, json: { detail: "ai_output_invalid" } });
  const issueId = url.pathname.split("/issues/")[1].split("/")[0];
  const issue = report.issues.find(item => item.id === issueId);
  saved = { id: "e".repeat(32), created_at: new Date().toISOString(), model: { id: "Qwen/Qwen3-4B", revision: "1cfa9a7208912126459214e8b04321603b3df60c", fine_tuned: false, quantization: "NF4" }, proposal: { summary: "Đối chiếu hình học và yêu cầu tuyến trước khi sửa thiết kế.", options: [{ action: "verify_geometry", target: "pair", rationale: "Kiểm tra mô hình và ý đồ phối hợp giữa hai cấu kiện đang chọn.", checks: ["complete_geometry", "recheck_geometry"], references: [issue.a, issue.b] }], missing_data: ["route_levels"], citations: ["guide:intersection:v1"], requires_review: true }, references: [{ id: "guide:intersection:v1", title: "Hướng dẫn phối hợp trong BIM Insight", version: "1", scope: "general_guidance", text: "Hướng dẫn chung cần người phụ trách xác minh." }], feedback: { revision: 0, state: "unreviewed", reviewer: "", note: "" }, metrics: { elapsed_seconds: 1, input_tokens: 100, output_tokens: 100 } };
  return route.fulfill({ json: saved });
});
try {
  await page.goto(`${origin}/#inspection`);
  await signIn(page);
  const clashes = page.getByRole("region", { name: "Kiểm tra va chạm 3D" });
  await clashes.getByText("Đã kiểm tra một phần — cần xem lại", { exact: true }).waitFor({ timeout: 30000 });
  await clashes.getByLabel("Lọc loại va chạm").selectOption("intersection");
  await clashes.getByRole("button", { name: "Rà soát cặp 1", exact: true }).click();
  const ai = clashes.getByRole("region", { name: "Đề xuất Qwen cho xung đột" });
  const generate = ai.getByRole("button", { name: "Tạo đề xuất bằng Qwen", exact: true });
  await expect(generate).toBeEnabled();
  await generate.focus(); await page.keyboard.press("Enter");
  await ai.getByRole("button", { name: "Hủy chạy Qwen", exact: true }).waitFor();
  await expect(clashes.getByRole("button", { name: "Chạy kiểm tra va chạm", exact: true })).toBeDisabled();
  await ai.getByRole("button", { name: "Hủy chạy Qwen", exact: true }).click();
  release();
  await expect(generate).toBeEnabled();
  assert.equal(await ai.getByTestId("ai-result").count(), 0);
  await generate.click();
  await ai.getByRole("alert").filter({ hasText: "chưa đạt kiểm tra" }).waitFor();
  assert.equal(await ai.getByTestId("ai-result").count(), 0);
  await generate.click();
  await ai.getByTestId("ai-result").waitFor();
  await expect(ai.getByLabel("Người phản hồi đề xuất")).toHaveAttribute("readonly", "");
  await ai.getByLabel("Nhận xét đề xuất").fill("UI mock only; geometry and human review unchanged.");
  await ai.getByRole("button", { name: "Lưu phản hồi đề xuất", exact: true }).click();
  await ai.getByText("Đã lưu phản hồi về đề xuất. Nhãn xung đột giữ theo kết quả rà soát riêng.", { exact: true }).waitFor();
  delayReload = true;
  await ai.getByRole("button", { name: "Tải lại đề xuất", exact: true }).click();
  await reloadPending;
  await expect(ai.getByRole("button", { name: "Lưu phản hồi đề xuất", exact: true })).toBeDisabled();
  releaseReload();
  await expect(generate).toBeEnabled();
  await ai.getByRole("button", { name: "Lưu phản hồi đề xuất", exact: true }).click();
  await expect(ai.getByRole("button", { name: "Lưu phản hồi đề xuất", exact: true })).toBeEnabled();
  await ai.getByText("Nguồn tham chiếu và lần chạy", { exact: true }).click();
  await ai.screenshot({ path: resolve(output, "ai-desktop.png") });
  await page.setViewportSize({ width: 375, height: 812 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await ai.screenshot({ path: resolve(output, "ai-375.png") });
  assert.equal(saved.feedback.revision, 2);
  assert.deepEqual(errors, []);
  const result = { status: "passed", provider: "UI mock; real Qwen covered by live/native checks", output, calls, checks: ["keyboard generation", "cancel and late response ignored", "invalid output and retry", "feedback separate from geometry review", "history reload cannot be aborted by feedback", "source/provenance details", "375px without overflow"] };
  await writeFile(resolve(output, "result.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
} catch (error) { await page.screenshot({ path: resolve(output, "failure.png"), fullPage: true }).catch(() => {}); throw error; }
finally { release(); releaseReload(); await browser.close(); }

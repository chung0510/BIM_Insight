import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {expect} from '@playwright/test';
import {downloadClashReport, signIn} from './account-helper.mjs';

// Geometry and human reviews use the isolated API; Qwen transport is a fixture (native_api.py tests the real GPU).
export async function checkRunConclusions(page,output){
  await page.setViewportSize({width:1440,height:1000});
  let configured=false, calls=0, epoch=0, release;
  const history=[];
  const gate=new Promise(done=>{release=done;});
  await page.route('**/api/projects/ai/runtime',route=>route.fulfill({json:{configured,files_present:configured}}));
  await page.route('**/issues/*/advice**',route=>route.fulfill({json:{items:[],total:0}}));
  await page.getByLabel('Tôi đã kiểm tra các IFC cùng công trình và hệ tọa độ',{exact:true}).check();
  await page.getByRole('button',{name:'Chạy kiểm tra va chạm',exact:true}).click();
  const report=await downloadClashReport(page);
  assert.equal(report.issues.length,2);
  const pair=report.issues.find(issue=>issue.kind==='intersection')??report.issues[0];
  const groups=[{id:'g1',kind:pair.kind,count:1,types:[pair.a.ifc_type,pair.b.ifc_type],source_names:[pair.a.source_name,pair.b.source_name],representative:pair}];
  const evidence={scope:'all_saved_issues',issue_count:report.issues.length,kind_counts:Object.fromEntries(['intersection','clearance','surface_review'].map(kind=>[kind,report.issues.filter(issue=>issue.kind===kind).length])),
    review_counts:{unreviewed:report.issues.length,needs_fix:0,intentional:0,insufficient_data:0},group_count:report.issues.length,groups,coverage:report.coverage,
    run_status:report.status,assessment:report.status==='partial'?'incomplete':'findings',diagnostics:report.diagnostics.map(item=>item.code)};
  function saved(){return {id:calls.toString(16).padStart(32,'0'),created_at:new Date().toISOString(),stale:false,epoch,
    model:{id:'Qwen/Qwen3-4B',quantization:'NF4',fine_tuned:false,revision:'fixture'},metrics:{elapsed_seconds:42,input_tokens:759,output_tokens:124},
    evidence:structuredClone(evidence),proposal:{assessment:evidence.assessment,summary:'Cần đối chiếu ý đồ thiết kế và phối hợp các bộ môn trước khi chỉnh mô hình.',
      priorities:[{group_id:'g1',action:'verify_geometry',rationale:'Đối chiếu hình học và ý đồ thiết kế cho nhóm cấu kiện được tham chiếu.'}],
      next_steps:['review_design_intent','recheck_geometry'],citations:['stats','g1'],requires_review:true}};}
  await page.route('**/runs/*/conclusions**',async route=>{
    if(route.request().method()==='GET')return route.fulfill({json:{items:history.map(item=>({...item,stale:item.epoch<epoch})),total:history.length}});
    calls++;
    if(calls===1){await gate;return route.fulfill({json:saved()}).catch(()=>{});}
    if(calls===2)return route.fulfill({status:422,json:{detail:'ai_output_invalid'}});
    if(calls===5)return route.fulfill({status:503,json:{detail:'ai_out_of_memory'}});
    const item=saved();history.unshift(item);return route.fulfill({json:item});
  });
  page.on('response',response=>{
    if(response.ok() && response.request().method()==='POST' && /\/issues\/[^/]+\/review$/.test(new URL(response.url()).pathname)){
      epoch++;evidence.review_counts.unreviewed--;evidence.review_counts.intentional++;
    }
  });
  const panel=page.getByRole('region',{name:'Kết luận tổng thể Qwen',exact:true});
  const generate=panel.getByRole('button',{name:'Tạo kết luận tổng thể',exact:true});
  try{
    await panel.getByRole('button',{name:'Tải lại kết luận',exact:true}).click();
    await expect(generate).toBeDisabled();
    await expect(panel).toContainText('Chưa cấu hình Qwen local');
    configured=true;
    await panel.getByRole('button',{name:'Tải lại kết luận',exact:true}).click();
    await expect(generate).toBeEnabled();
    await page.getByRole('button',{name:'Rà soát cặp 1',exact:true}).click();
    await page.getByRole('region',{name:'Đề xuất Qwen cho xung đột',exact:true}).getByRole('button',{name:'Tạo đề xuất bằng Qwen',exact:true}).waitFor();
    await generate.focus();await page.keyboard.press('Enter');
    await expect(panel.getByRole('button',{name:'Hủy tạo kết luận',exact:true})).toBeVisible();
    await expect(page.locator('.ifc-viewer')).toHaveCount(0);
    await expect(page.getByRole('button',{name:'Chạy kiểm tra va chạm',exact:true})).toBeDisabled();
    await expect(page.getByRole('button',{name:'Tạo đề xuất bằng Qwen',exact:true})).toBeDisabled();
    await expect(page.getByLabel('Trạng thái rà soát',{exact:true})).toBeDisabled();
    await panel.getByRole('button',{name:'Hủy tạo kết luận',exact:true}).click();release();
    await expect(generate).toBeEnabled();
    assert.equal(await panel.getByTestId('run-conclusion-result').count(),0);
    await generate.click();
    await expect(panel.getByRole('alert')).toContainText('chưa đạt kiểm tra');
    assert.equal(await panel.getByTestId('run-conclusion-result').count(),0);
    await generate.click();
    await expect(panel.getByTestId('run-conclusion-result')).toBeVisible();
    await expect(page.getByRole('button',{name:'Chạy kiểm tra va chạm',exact:true})).toBeEnabled();
    await page.getByLabel('Lọc loại va chạm',{exact:true}).selectOption('clearance');
    await expect(page.getByText('Không có bằng chứng khớp bộ lọc.',{exact:true})).toBeVisible();
    await expect(panel).toContainText('2 cặp đã lưu');
    await panel.getByRole('button',{name:'Xem minh chứng kết luận 1 trong 3D',exact:true}).click();
    await expect(page.getByTestId('clash-selection')).toBeVisible({timeout:60000});
    await panel.scrollIntoViewIfNeeded();await panel.screenshot({path:resolve(output,'conclusion-desktop.png')});
    const pending=page.waitForEvent('download');
    await panel.getByRole('button',{name:'Tải kết luận JSON',exact:true}).click();
    const downloaded=JSON.parse(await readFile(await (await pending).path(),'utf8'));
    assert.deepEqual(downloaded.evidence.kind_counts,evidence.kind_counts);
    assert.equal(downloaded.proposal.requires_review,true);
    await page.getByLabel('Lọc loại va chạm',{exact:true}).selectOption('all');
    const editor=page.getByRole('region',{name:'Rà soát xung đột',exact:true});
    await editor.getByLabel('Trạng thái rà soát',{exact:true}).selectOption('intentional');
    await editor.getByLabel('Nhận xét',{exact:true}).fill('UI verification only: checked fixture design intent.');
    await editor.getByRole('button',{name:'Lưu rà soát',exact:true}).click();
    await expect(panel).toContainText('Nhãn hoặc dữ liệu đã thay đổi');
    assert.equal(history[0].evidence.review_counts.intentional,0);
    await expect(generate).toBeEnabled();await generate.click();
    await expect(panel.getByLabel('Kết luận tổng thể đã lưu').locator('option')).toHaveCount(2);
    await expect(panel.getByTestId('run-conclusion-result')).not.toContainText('Nhãn hoặc dữ liệu đã thay đổi');
    await page.reload();await signIn(page);
    await expect(panel.getByLabel('Kết luận tổng thể đã lưu').locator('option')).toHaveCount(2);
    await panel.getByLabel('Kết luận tổng thể đã lưu').selectOption(history[1].id);
    await expect(panel).toContainText('Nhãn hoặc dữ liệu đã thay đổi');
    await expect(generate).toBeEnabled();await generate.click();
    await expect(panel.getByRole('alert')).toContainText('GPU chưa đủ bộ nhớ');
    await expect(panel.getByTestId('run-conclusion-result')).toBeVisible();
    await page.setViewportSize({width:375,height:812});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
    await panel.scrollIntoViewIfNeeded();await panel.screenshot({path:resolve(output,'conclusion-mobile.png')});
    return {run_conclusion_ui:true,summary_independent_of_table_filters:true,conclusion_cancel_invalid_retry:true,
      shared_ai_lock_and_viewer_pause:true,conclusion_saved_history:true,review_change_flags_stale:true,
      conclusion_json_export:true,conclusion_evidence_3d:true,conclusion_mobile_375:true,
      conclusion_ai_transport_fixture:true,native_qwen_test:'.local/run-conclusions-20261109/native-api-verification.json'};
  }finally{release();}
}

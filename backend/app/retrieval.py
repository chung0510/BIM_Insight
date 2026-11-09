import re

from fastapi import HTTPException


GUIDES = {
    "intersection": "Giao hình học: xác minh đúng bộ nguồn và hệ tọa độ. Ưu tiên xem xét đổi tuyến cơ điện; giữ yêu cầu vận hành. Lỗ mở chỉ là phương án phối hợp sau phê duyệt kết cấu. Luôn kiểm tra lại hình học sau thay đổi.",
    "clearance": "Thiếu khoảng hở theo ngưỡng người dùng chọn: kiểm tra yêu cầu cách nhiệt, bảo trì, lắp đặt và cao độ tuyến. Chưa coi ngưỡng thử nghiệm là quy chuẩn. Xem xét đổi tuyến cơ điện rồi kiểm tra lại hình học.",
    "surface_review": "Giao hoặc tiếp xúc bề mặt chưa đủ để khẳng định xuyên khối. Chỉ đề xuất xác minh hình học, ý đồ thiết kế và mô hình kín. Chưa đề xuất di chuyển cấu kiện khi bằng chứng còn mơ hồ.",
}


def retrieve(projects, project_id, revision, issue, document_ids):
    kind = issue["kind"]
    references = [{"id": f"guide:{kind}:v1", "title": "Hướng dẫn phối hợp trong BIM Insight", "version": "1", "scope": "general_coordination_guidance_not_a_standard", "trust": "app_guidance", "text": GUIDES[kind]}]
    terms = set(re.findall(r"\w+", f"{issue['a']['ifc_type']} {issue['b']['ifc_type']} pipe duct beam ống dầm tuyến".lower()))
    candidates = []
    for identifier in dict.fromkeys(document_ids):
        report = projects.read_report(identifier)
        if report.get("project_id") != str(project_id) or report.get("kind") != "pdf" or report.get("status") not in {"completed", "partial"}:
            raise HTTPException(422, "ai_reference_invalid")
        for page in (report.get("result") or {}).get("pages", []):
            text = page.get("text_preview", "").strip()
            if not text:
                continue
            score = len(terms.intersection(re.findall(r"\w+", text.lower())))
            candidates.append((score, {"id": f"pdf:{identifier}:p{page['page']}", "inspection_id": identifier, "title": report["name"], "version": report["sha256"][:12], "sha256": report["sha256"], "page": page["page"], "scope": "first_2000_characters_of_page_no_ocr", "trust": "untrusted_reference_text", "text": text[:600]}))
    if document_ids and not candidates:
        raise HTTPException(422, "ai_reference_no_text")
    references.extend(item for _, item in sorted(candidates, key=lambda item: item[0], reverse=True)[:2])
    return references

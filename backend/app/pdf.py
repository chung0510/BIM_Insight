from pathlib import Path
import math

from pypdf import PdfReader
from app.limits import MAX_PDF_PAGES


def inspect_pdf(path: Path) -> dict:
    report = {
        "status": "failed", "scope": "pdf_metadata_and_text", "clash_detection": "not_run",
        "page_count": 0, "processed_pages": 0, "pages": [], "text_status": "not_detected",
        "diagnostics": [],
    }
    try:
        with Path(path).open("rb") as handle:
            if not handle.read(1024).lstrip().startswith(b"%PDF-"):
                raise ValueError("Invalid header")
            handle.seek(0)
            reader = PdfReader(handle, strict=False)
            if reader.is_encrypted and not reader.decrypt(""):
                report["diagnostics"].append({"code": "pdf_password_required"})
                return report
            report["page_count"] = len(reader.pages)
            for index in range(min(report["page_count"], MAX_PDF_PAGES)):
                page = reader.pages[index]
                scale = float(page.user_unit)
                if not math.isfinite(scale) or scale <= 0:
                    report["diagnostics"].append({"code": "invalid_page_size", "page": index + 1})
                    continue
                width = float(page.mediabox.width) * scale * 25.4 / 72
                height = float(page.mediabox.height) * scale * 25.4 / 72
                if not all(math.isfinite(value) and value > 0 for value in [width, height]):
                    report["diagnostics"].append({"code": "invalid_page_size", "page": index + 1})
                    continue
                try:
                    contents = page.get_contents()
                    if contents is not None and len(contents.get_data()) > 16 * 1024 * 1024:
                        report["diagnostics"].append({"code": "page_content_limit", "page": index + 1})
                        continue
                    text = (page.extract_text() or "").strip()
                except Exception:
                    report["diagnostics"].append({"code": "page_text_failed", "page": index + 1})
                    continue
                report["pages"].append({
                    "page": index + 1, "width_mm": round(width, 2), "height_mm": round(height, 2),
                    "rotation": page.rotation, "text_characters": len(text), "text_preview": text[:2000],
                })
            report["processed_pages"] = len(report["pages"])
    except Exception:
        report["diagnostics"].append({"code": "invalid_pdf"})
        return report
    if any(page["text_characters"] for page in report["pages"]):
        report["text_status"] = "detected"
    else:
        report["diagnostics"].append({"code": "text_not_detected"})
    if report["page_count"] > MAX_PDF_PAGES:
        report["diagnostics"].append({"code": "page_limit", "limit": MAX_PDF_PAGES})
    if not report["page_count"]:
        report["diagnostics"].append({"code": "no_pages"})
    report["status"] = "partial" if report["diagnostics"] else "completed"
    return report

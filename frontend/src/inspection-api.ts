import { invoke, isTauri } from "@tauri-apps/api/core";

export type FileKind = "ifc" | "pdf" | "dxf" | "dwg";
export type ProcessingLimits = { queue_files: number; open_files: number; clash_models: number; clash_elements: number; clash_issues: number; timeout_seconds: number; pdf_pages: number; viewer_bytes: number };
export type Connection = { base_url: string; token: string; file_limits: Record<FileKind, number>; processing_limits: ProcessingLimits; deployment?: "desktop" | "web" | "web_demo" };
export type ProcessingStats = { elapsed_seconds?: number; memory_bytes?: number; peak_memory_bytes?: number; memory_limit_bytes?: number; system_available_bytes?: number; last_progress?: {phase: string} | null };
export type ProcessingProgress = ProcessingStats & { phase: string; done?: number; total?: number };
let accountToken = "";
export function setAccountToken(token: string) { accountToken = token; }
export function accountSessionExpired(detail: unknown) {
  if (detail === "account_session_required" || detail === "account_session_expired") window.dispatchEvent(new Event("bim-account-expired"));
}
export type Diagnostic = {
  code: string;
  guid?: string;
  page?: number;
  limit?: number;
  peak_memory_bytes?: number;
  memory_limit_bytes?: number;
  elapsed_seconds?: number;
};
export type Inspection = {
  id: string;
  name: string;
  kind: "ifc" | "pdf" | "dxf" | "dwg";
  assets?: { drawing?: string; model?: string; mapping?: string; converted_dxf?: string; details?: string };
  dataset?: string | null;
  project_id?: string | null;
  revision?: string | null;
  logical_source?: string;
  created_at?: string;
  clash_ready?: boolean;
  discipline: string;
  size_bytes: number;
  sha256: string;
  status: "completed" | "partial" | "failed";
  error_code?: string;
  elapsed_seconds: number;
  processing?: ProcessingStats;
  report_url: string;
  clash_detection: "not_run";
  result: {
    diagnostics: Diagnostic[];
    diagnostics_truncated?: boolean;
    ifc_schema?: string;
    geometry_policy?: number;
    reference_count?: number;
    reference_elements?: { guid: string; ifc_type: string; name: string | null }[];
    reference_elements_truncated?: boolean;
    geometry_failures?: { guid: string; ifc_type: string; name: string | null; detail?: string }[];
    geometry_settings?: { linear_deflection_m: number; scope: string; clash_geometry: string };
    viewer_optimization?: { version: number; before_bytes: number; after_bytes: number };
    project_unit_scale_to_m?: number;
    element_count?: number;
    excluded_count?: number;
    aggregate_count?: number;
    subtraction_count?: number;
    source_guids?: string[];
    storeys?: { guid: string; name: string; elevation_m: number }[];
    dxf_version?: string;
    conversion?: { converter: string; version: string; output_format: string; output_sha256: string; output_bytes: number; audit: boolean };
    unit_name?: string;
    unit_scale_to_m?: number | null;
    modelspace_count?: number;
    block_count?: number;
    layers?: { name: string; visible: boolean }[];
    entity_types?: Record<string, number>;
    layouts?: { name: string; entity_count: number }[];
    text_sample?: string[];
    external_references?: { name: string; path: string }[];
    triangle_count?: number;
    type_counts?: Record<string, number>;
    elements_truncated?: boolean;
    elements?: {
      guid: string;
      ifc_type: string;
      name: string | null;
      triangle_count: number;
      bounds_m: { min: number[]; max: number[] };
    }[];
    page_count?: number;
    processed_pages?: number;
    text_status?: string;
    pages?: {
      page: number;
      width_mm: number;
      height_mm: number;
      rotation: number;
      text_characters: number;
      text_preview: string;
    }[];
  } | null;
};

const messages: Record<string, string> = {
  account_session_required: "Hãy đăng nhập để tiếp tục.",
  account_session_expired: "Phiên đăng nhập đã hết hạn hoặc bị thu hồi. Hãy đăng nhập lại.",
  invalid_credentials: "Tên đăng nhập hoặc mật khẩu chưa đúng.",
  current_password_invalid: "Mật khẩu hiện tại chưa đúng.",
  auth_rate_limited: "Có nhiều lần thử trong thời gian ngắn. Hãy chờ một phút rồi thử lại.",
  setup_required: "Hãy tạo tài khoản quản trị đầu tiên trên máy này.",
  setup_already_completed: "Hệ thống đã có quản trị viên. Hãy đăng nhập.",
  username_unavailable: "Tên đăng nhập này đã được sử dụng.",
  admin_required: "Chức năng này dành cho quản trị viên.",
  project_permission_denied: "Bạn chưa có quyền thực hiện thao tác này trong dự án.",
  member_unavailable: "Chưa tìm thấy tài khoản đang hoạt động để chia sẻ.",
  reviewer_role_required: "Quyền rà soát dành cho tài khoản Giảng viên hoặc Admin được chia sẻ hồ sơ.",
  account_changed: "Tài khoản đã thay đổi. Tải lại danh sách trước khi lưu.",
  profile_changed: "Hồ sơ đã thay đổi ở phiên khác hoặc quyền tài khoản vừa được cập nhật. Tải lại hồ sơ trước khi lưu.",
  password_change_required: "Tài khoản cần đổi mật khẩu tạm trước khi sử dụng chức năng này.",
  password_must_differ: "Mật khẩu mới phải khác mật khẩu tạm được cấp.",
  mail_not_configured: "Chưa thiết lập Gmail gửi mã. Hãy liên hệ Admin hoặc vào Tài khoản → Email khôi phục để cấu hình.",
  mail_configuration_invalid: "Chưa đọc được cấu hình Gmail trên máy này. Admin cần thiết lập lại email khôi phục.",
  mail_connection_failed: "Chưa kết nối được Gmail. Kiểm tra mạng, Gmail gửi thư, Xác minh 2 bước và Mật khẩu ứng dụng 16 ký tự.",
  verification_code_invalid: "Mã xác nhận không đúng, đã hết hạn, đã dùng hoặc vượt số lần thử. Hãy yêu cầu mã mới.",
  email_unavailable: "Email đã gắn với tài khoản khác. Kiểm tra lại địa chỉ hoặc liên hệ Admin.",
  excel_file_invalid: "Chọn file .xlsx hợp lệ, tối đa 2 MiB. Không dùng file có macro hoặc liên kết bên ngoài.",
  excel_formula_not_allowed: "Excel có ô công thức. Chuyển công thức thành giá trị văn bản/số rồi tải lại.",
  excel_one_sheet_required: "Dùng một sheet danh sách tài khoản trong file Excel.",
  excel_scope_limit: "File cần có tiêu đề và 1–200 dòng tài khoản, tối đa 20 cột.",
  excel_columns_invalid: "Tiêu đề Excel bị thiếu, trùng hoặc có dữ liệu ngoài các cột có tiêu đề.",
  excel_columns_mismatch: "Số ô dữ liệu không khớp số cột trong file.",
  excel_headers_required: "Cần các cột Họ và tên, Mã giảng viên hoặc Mã sinh viên, email.",
  excel_identity_required: "Điền đúng một mã giảng viên hoặc mã sinh viên ở dòng này.",
  excel_code_as_text_required: "Đặt ô mã ở định dạng Văn bản (Text) và nhập lại mã gốc; không dùng số quá dài, số thập phân hoặc giá trị đúng/sai.",
  provision_row_invalid: "Kiểm tra họ tên, mã 3–48 ký tự và địa chỉ email hợp lệ.",
  provision_duplicate_in_file: "Mã hoặc email bị trùng trong file.",
  provision_identity_exists: "Mã hoặc email đã có tài khoản trong hệ thống.",
  provision_rows_invalid: "Danh sách có mã/email trùng hoặc dữ liệu không hợp lệ. Kiểm tra lại trước khi cấp.",
  provision_request_changed: "Yêu cầu cấp đã thay đổi hoặc hết hạn. Tải lại danh sách lô cấp để kiểm tra.",
  provision_in_progress: "Lô này đang được xử lý. Đợi hoàn tất rồi tải lại danh sách lô cấp.",
  provision_export_unavailable: "File cấp tài khoản chưa sẵn sàng, đã hết hạn hoặc bạn không có quyền tải.",
  provision_export_machine: "Hãy tải file trên máy đã cấp tài khoản; máy này không đọc được bản xuất được bảo vệ.",
  account_protected_or_changed: "Tài khoản được bảo vệ hoặc đã thay đổi. Hãy tải lại danh sách.",
  own_admin_role_protected: "Bạn không thể tự hạ quyền quản trị của mình.",
  last_admin_protected: "Cần giữ ít nhất một tài khoản quản trị đang hoạt động.",
  unsupported_file_type:
    "Hỗ trợ IFC, PDF, DXF và DWG. Xuất RVT/RTE sang IFC trước khi kiểm tra.",
  invalid_file_header:
    "Nội dung không đúng định dạng IFC/PDF/DXF/DWG. Hãy kiểm tra hoặc xuất lại tệp.",
  file_too_large:
    "Tệp vượt dung lượng cho phép. Hãy xuất một phần công trình nhỏ hơn.",
  file_required: "Hãy chọn một tệp để kiểm tra.",
  processor_busy: "Có một tệp đang được kiểm tra. Hãy thử lại sau giây lát.",
  processing_timeout:
    "Tác vụ chưa hoàn tất trong thời gian xử lý cho phép. Hãy thử riêng tầng hoặc khu vực.",
  processing_memory_limit:
    "Tiến trình đã vượt ngân sách RAM an toàn của lượt xử lý và đã dừng. Hãy giải phóng RAM trước khi chạy lại.",
  processing_failed: "Không xử lý được tệp. Hãy kiểm tra bản xuất và thử lại.",
  inspection_connection_lost: "Luồng xử lý tệp bị gián đoạn. Giữ terminal chạy app mở, kết nối lại và thử lại tệp; lượt này chưa có kết quả hoàn tất.",
  clash_connection_lost: "Mất kết nối với bộ xử lý va chạm. Giữ terminal chạy app mở, khởi động lại app nếu đã dừng rồi chạy kiểm tra lại. Lượt này chưa có kết luận.",
  processing_output_limit: "Báo cáo vượt giới hạn dung lượng xuất. Phạm vi chưa đầy đủ; hãy chia tầng hoặc khu vực để kiểm tra và xuất tiếp.",
  processing_disk_space: "Ổ lưu dữ liệu chưa đủ chỗ trống cho tệp và dữ liệu hình học sinh ra. Giải phóng dung lượng rồi thử lại.",
  source_cache_unavailable: "Chưa đọc hoặc lưu được cache trên máy. Kiểm tra quyền thư mục dữ liệu của app và ứng dụng đang giữ tệp, rồi thử lại.",
  invalid_session_token:
    "Kết nối xử lý đã thay đổi. Hãy kết nối lại rồi thử lại tệp.",
  origin_not_allowed: "Không được phép kết nối từ cửa sổ này.",
  invalid_ifc: "Không đọc được mô hình IFC.",
  invalid_pdf: "Không đọc được cấu trúc PDF.",
  pdf_password_required:
    "PDF cần mật khẩu. Hãy dùng một bản xuất không khóa để kiểm tra.",
  text_not_detected:
    "Không tìm thấy chữ có thể trích xuất. Có thể cần OCR hoặc xem lại bản xuất.",
  page_text_failed: "Chưa trích xuất được nội dung của trang này.",
  page_content_limit:
    "Trang có nội dung quá lớn để trích xuất trong lần kiểm tra này.",
  page_limit:
    "Đã chạm giới hạn số trang đọc trong một PDF; các trang còn lại chưa được xử lý.",
  invalid_page_size: "Không xác định được khổ trang hợp lệ.",
  no_pages: "PDF không có trang để đọc.",
  missing_representation: "Cấu kiện chưa có hình học để kiểm tra.",
  missing_or_duplicate_guid:
    "Cấu kiện thiếu hoặc trùng mã GUID trong cùng tệp.",
  geometry_failed: "Chưa dựng được hình học của cấu kiện.",
  ifc_body_nonphysical: "Đối tượng khai báo là cấu kiện vật lý nhưng chỉ có đường/điểm hoặc hình học rỗng. Cần kiểm tra bản xuất IFC.",
  ifc_opening_geometry_failed: "Lỗ mở chưa tạo được khối khoét hợp lệ. Lỗ mở và cấu kiện chủ bị ảnh hưởng chưa được đánh giá; cần kiểm tra bản xuất IFC.",
  ifc_inventory_incomplete: "Chưa đối soát đủ mọi đối tượng trong IFC. Lượt kiểm tra chưa thể kết luận đầy đủ.",
  no_elements: "Không tìm thấy cấu kiện trong mô hình.",
  ifc_units_unknown: "IFC chưa khai báo đơn vị chiều dài hợp lệ. Cần xuất lại với đơn vị rõ ràng trước khi xem hoặc căn khớp.",
  invalid_guid: "Mã IFC GUID sai định dạng; cấu kiện này chưa được đưa vào trình xem.",
  invalid_dxf: "Không đọc được cấu trúc DXF.",
  conversion_required: "Báo cáo DWG cũ chỉ có header. Hãy nhập lại DWG vào dự án để chuyển sang DXF và kiểm tra nội dung.",
  project_required: "Chọn hoặc tạo dự án trước khi đưa hồ sơ vào kiểm tra.",
  dwg_converter_not_installed: "Chưa tìm thấy ODA File Converter chính thức trên máy. Cài bộ chuyển từ Open Design Alliance rồi kết nối lại.",
  dwg_conversion_failed: "Không chuyển được DWG hoặc DXF sau chuyển vượt dung lượng cho phép. Hãy mở kiểm tra tệp trong phần mềm CAD, hoặc xuất bản vẽ nhỏ hơn.",
  dwg_conversion_timeout: "Chuyển DWG chưa hoàn tất trong thời gian cho phép. Hãy thử bản vẽ theo tầng hoặc khu vực nhỏ hơn.",
  dwg_reimport_required: "DWG này đã lưu bằng bộ đọc header cũ. Nhập lại tệp để chuyển DXF; báo cáo cũ được giữ nguyên.",
  cad_units_unknown: "DXF chưa khai báo đơn vị hợp lệ. Cần xác nhận đơn vị và xuất lại trước khi căn khớp.",
  cad_xref_unresolved: "Bản vẽ có tham chiếu ngoài chưa được nạp; preview chưa đủ nội dung.",
  cad_audit_review: "Cấu trúc CAD có lỗi hoặc cần sửa trong bộ nhớ; hãy xem lại bản xuất.",
  cad_entities_unsupported: "Một số loại đối tượng CAD chưa được hiển thị trong preview.",
  cad_grid_limit: "Danh sách trục đã vượt giới hạn; chưa đủ phạm vi để xác nhận căn khớp.",
  cad_preview_limit: "Bản vẽ vượt giới hạn preview. Hãy xuất riêng mặt bằng hoặc khu vực nhỏ hơn.",
  cad_preview_failed: "Chưa tạo được preview DXF. Metadata đã đọc được vẫn được giữ lại.",
  cad_empty_modelspace: "Model space không có hình học; hãy kiểm tra layout hoặc xuất view riêng.",
  ifc_viewer_limit: "Đã đọc IFC nhưng bản xem 3D vượt ngân sách trình xem; dữ liệu dùng kiểm tra va chạm vẫn được giữ. Với hồ sơ đã nhập trước bản tối ưu, nhập lại vào dự án để tạo lại bản xem. Nếu vẫn vượt giới hạn, xuất theo tầng hoặc khu vực.",
  ifc_viewer_failed: "Chưa xuất được đầy đủ mô hình xem 3D; hãy kiểm tra phần hình học còn thiếu.",
  ifc_iterator_failed: "Chưa dựng được toàn bộ hình học. Các cấu kiện đã đọc được vẫn được giữ; phần còn thiếu được ghi trong báo cáo.",
  ifc_body_missing: "Cấu kiện chỉ có biểu diễn phụ hoặc khoảng bảo trì, chưa có hình học vật lý để kiểm tra.",
  ifc_body_context_ambiguous: "Các phần hình học của cấu kiện khai báo hệ tọa độ khác nhau; cần kiểm tra bản xuất IFC trước khi phối hợp.",
  alignment_source_invalid: "Nguồn chưa đủ điều kiện liên kết. Hãy chọn DXF và IFC đã đọc được.",
  alignment_storey_invalid: "Tầng đã chọn không có trong mô hình IFC tham chiếu.",
  alignment_not_ready: "Cần khớp nhiều trục và xác nhận cùng công trình và đúng tầng trước khi lưu.",
  asset_not_found: "Không tìm thấy dữ liệu xem. Hãy nhập và kiểm tra lại tệp.",
  clash_frame_unconfirmed: "Hãy kiểm tra và xác nhận các IFC cùng công trình và hệ tọa độ.",
  clash_reimport_required: "Hãy nhập và kiểm tra lại IFC để lưu bản nguồn cho bộ kiểm tra va chạm.",
  clash_duplicate_source: "Chọn các tệp IFC khác nhau; không so một mô hình với chính nó.",
  clash_mixed_datasets: "Bộ mẫu tổng hợp phải được kiểm tra riêng với hồ sơ của bạn.",
  clash_link_invalid: "Liên kết bản vẽ không còn phù hợp với các IFC đã chọn. Hãy căn khớp lại.",
  clash_source_missing: "Không tìm thấy bản IFC đã lưu. Hãy nhập lại tệp.",
  clash_source_hash_mismatch: "Dấu kiểm IFC hoặc dữ liệu ánh xạ đã thay đổi. Hãy nhập lại tệp trước khi kiểm tra.",
  clash_no_geometry: "Chưa có hình học hợp lệ để so giữa các IFC.",
  clash_scope_limit: "Đã vượt số cấu kiện tối đa trong một lượt kiểm tra. Hãy xuất riêng tầng hoặc khu vực nhỏ hơn.",
  clash_geometry_failed: "Chưa dựng đủ hình học cho lần kiểm tra này.",
  clash_cache_permission_denied: "App không có quyền đọc hoặc ghi cache hình học trên máy. Kiểm tra quyền thư mục dữ liệu hoặc tạo lại cache bằng đúng tài khoản Windows đang chạy app.",
  clash_check_failed: "Bộ kiểm tra hình học chưa hoàn tất. Hãy thử phạm vi nhỏ hơn.",
  clash_missing_geometry: "Một số cấu kiện chưa có hình học; chưa thể kết luận cho toàn bộ phạm vi.",
  clash_nonmanifold: "Một số hình học không tạo thành khối kín. Các giao cắt bề mặt cần xem xét riêng.",
  clash_surface_review: "Có bề mặt giao hoặc trùng nhau nhưng chưa xác lập được mức xuyên khối. Cần xem cặp cấu kiện trong 3D trước khi kết luận.",
  clash_reference_ambiguous: "Có đối tượng cùng mã tham chiếu giữa các tệp. Cần xác minh đối tượng dùng chung trước khi kết luận.",
  clash_issue_limit: "Đã chạm số kết quả tối đa của lượt kiểm tra; kết quả chưa đầy đủ. Hãy chia khu vực để kiểm tra tiếp.",
  clash_invalid_measurement: "Một phép đo hình học không hợp lệ; kết quả chưa đầy đủ.",
  database_unavailable: "Chưa kết nối được MongoDB. Kiểm tra kết nối Atlas hoặc dịch vụ local rồi tải lại; thao tác dự án chưa được xác nhận lưu.",
  project_not_found: "Không tìm thấy dự án. Hãy chọn lại hoặc tạo dự án mới.",
  project_busy: "App hoặc thiết bị khác đang xử lý dữ liệu dự án. Hãy đợi hoàn tất hoặc hủy tác vụ đang chạy rồi thử lại.",
  project_deleting: "Dự án đang chờ xóa. Bấm Xóa dự án để tiếp tục dọn dữ liệu.",
  project_delete_failed: "Xóa dữ liệu chưa hoàn tất. Đóng tệp đang mở trong phần mềm khác rồi bấm Xóa dự án để thử lại.",
  project_delete_invalid_artifact: "Thông tin tệp dự án chưa hợp lệ. Chưa thể xóa an toàn; cần kiểm tra dữ liệu lưu của dự án.",
  storage_namespace_mismatch: "Dự án có tệp trong cấu hình R2 trước đây. Kết nối lại đúng bucket/database đã dùng rồi thử xóa lại.",
  storage_file_deleting: "Tệp R2 đang được dọn bởi một lượt xóa dự án. Hãy đợi hoàn tất rồi đồng bộ lại.",
  project_artifact_missing: "Thiếu tệp đã lưu và chưa có bản sao R2 đã xác minh. Kiểm tra cấu hình R2 hoặc nhập lại đúng bộ nguồn.",
  storage_not_configured: "Chưa cấu hình R2. Làm theo hướng dẫn kết nối R2 trong README rồi mở lại app.",
  storage_configuration_invalid: "Chưa đọc được cấu hình R2 trên tài khoản Windows này. Hãy cấu hình lại R2 theo README.",
  storage_unavailable: "Chưa kết nối được R2. Kiểm tra mạng, endpoint và quyền Object Read & Write của token rồi thử lại.",
  storage_hash_mismatch: "Tệp tải từ R2 không khớp SHA-256 đã lưu. App giữ cache cũ và dừng phục hồi tệp này.",
  storage_immutable_conflict: "Nội dung tệp khác bản đã lưu trên R2. Hãy kiểm tra nguồn và nhập lại bản cập nhật.",
  storage_byte_budget: "Đã chạm giới hạn 8 GB trong app, kể cả dung lượng đang giữ chỗ. Chưa tải thêm tệp lên R2.",
  storage_request_budget: "Đã chạm giới hạn request R2 của app trong tháng này. Chưa gửi thêm request.",
  storage_file_too_large: "Tệp vượt dung lượng đồng bộ R2 cho phép. Hãy chia phạm vi mô hình trước khi đồng bộ.",
  storage_cancelled: "Đã dừng đồng bộ R2; các tệp đã xác minh vẫn được giữ lại.",
  ai_not_configured: "Chưa cấu hình Qwen local. Chạy cấu hình AI theo README rồi mở lại app.",
  ai_summary_no_evidence: "Lượt kiểm tra chưa có đủ bằng chứng hình học để tổng hợp. Hoàn tất kiểm tra IFC trước khi tạo kết luận Qwen.",
  ai_configuration_invalid: "Chưa đọc được cấu hình AI trên tài khoản Windows này. Hãy cấu hình lại theo README.",
  ai_runtime_missing: "Thiếu môi trường AI, model local hoặc CUDA. Kiểm tra cấu hình Qwen trên máy.",
  ai_runtime_version: "Môi trường AI khác phiên bản đã khóa. Dùng đúng requirements-ai.lock trước khi chạy.",
  ai_model_hash_mismatch: "Tệp model không khớp hash đã khóa hoặc đang thiếu. Chưa chạy Qwen với bộ model này.",
  ai_context_limit: "Đoạn tham chiếu vượt context đã kiểm chứng trên laptop. Hãy bớt tài liệu tham chiếu rồi thử lại.",
  ai_out_of_memory: "GPU chưa đủ bộ nhớ trống để chạy Qwen. Đóng ứng dụng đang dùng GPU rồi thử lại.",
  ai_output_invalid: "Qwen trả đề xuất chưa đạt kiểm tra cấu trúc, nguồn hoặc phạm vi. Đề xuất này chưa được lưu; hãy rà soát bằng chứng rồi thử lại.",
  ai_timeout: "Qwen vượt thời gian xử lý trên máy. Tiến trình đã dừng; chưa có đề xuất mới được lưu.",
  ai_unavailable: "Chưa chạy được Qwen local. Kiểm tra môi trường AI và thử lại; chưa có đề xuất mới được lưu.",
  ai_reference_invalid: "PDF tham chiếu cần thuộc đúng dự án của lượt kiểm tra này.",
  ai_reference_no_text: "PDF được chọn chưa có chữ trích xuất được. Bản scan cần OCR trước khi dùng làm tham chiếu AI.",
  advice_not_found: "Không tìm thấy đề xuất AI trong cặp xung đột này.",
  source_context_invalid: "Chọn dự án và nguồn logic hợp lệ trước khi nhập.",
  source_revision_conflict: "Nguồn này đã thay đổi. Hãy nhập lại bản cập nhật.",
  clash_project_revision_mismatch: "Các IFC cần thuộc cùng dự án. Hãy mở đúng bộ hồ sơ trước khi kiểm tra.",
  alignment_project_revision_mismatch: "DXF và IFC cần cùng dự án và nhóm dữ liệu; liên kết phải đúng với các tệp đã chọn.",
  review_revision_conflict: "Nhãn đã được cập nhật ở nơi khác. Tải lại nhãn rồi kiểm tra trước khi lưu lại.",
  run_not_found: "Không tìm thấy lượt kiểm tra trong dự án này.",
  issue_not_found: "Không tìm thấy bằng chứng xung đột trong lượt này.",
  case_not_found: "Không tìm thấy ca dữ liệu trong lượt này.",
};
export function errorMessage(code: unknown) {
  accountSessionExpired(code);
  return typeof code === "string" && messages[code]
    ? messages[code]
    : "Không hoàn tất được kiểm tra. Hãy kết nối lại và thử lại.";
}
export function authHeaders(connection: Pick<Connection, "token">): Record<string, string> {
  return { ...(connection.token ? { Authorization: `Bearer ${connection.token}` } : {}), ...(accountToken ? { "X-BIM-Session": accountToken } : {}) };
}
export async function processorFetch(connection: Connection, url: string, options: RequestInit = {}) {
  if (!url.startsWith("/api/inspections/") && url !== "/api/projects" && !url.startsWith("/api/projects?") && !url.startsWith("/api/projects/") && !url.startsWith("/api/auth/") && !url.startsWith("/api/admin/")) throw new Error("Đường dẫn dữ liệu không hợp lệ.");
  const response = await fetch(`${connection.base_url}${url}`, {
    ...options, headers: { ...authHeaders(connection), ...options.headers },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw Object.assign(new Error(errorMessage(payload.detail)), { status: response.status });
  }
  return response;
}

export type LinkResult = {
  id?: string;
  confirmed: boolean;
  grid_xy_ready: boolean;
  matched_axes: number;
  total_axes: number;
  elevation_m: number;
  max_distance_m: number | null;
  link_url?: string;
  model_id: string;
  drawing_id: string;
  storey_guid: string;
  dx_m: number;
  dy_m: number;
  rotation_deg: number;
  unit_scale_to_m: number;
  project_name?: string;
  revision?: string;
  model_sha256?: string;
  drawing_sha256?: string;
};

export type ClashElement = { source_id: string; source_name: string; guid: string; ifc_type: string; name: string | null; storey_guid: string | null; canonical_guid?: string };
export type ClashIssue = {
  id: string;
  kind: "intersection" | "clearance" | "surface_review";
  a: ClashElement;
  b: ClashElement;
  distance_m: number | null;
  required_clearance_m: number | null;
  point_m: [number, number, number];
  recommendation: string;
  group_id?: string;
};
export type FocusedPair = Pick<ClashIssue, "id" | "a" | "b"> & { point_m?: [number, number, number] };
export type CaseLabel = "unreviewed" | "intersection" | "clearance" | "no_clash" | "insufficient_data";
export type ReviewState = "unreviewed" | "needs_fix" | "intentional" | "insufficient_data";
export type Review = { revision: number; state?: ReviewState; label?: CaseLabel; reviewer: string; note: string; updated_at: string | null; origin?: "human"; expert_accepted?: boolean };
export type AnalyticCase = { case_id: string; label: string; expected: CaseLabel; detected: string; expected_origin: "analytic"; split_group: string; geometry_complete: boolean; a: ClashElement; b: ClashElement };
export type ReviewedCase = AnalyticCase & { review: Review };
export type ReviewBundle = { issues: { issue_id: string; review: Review }[]; cases: ReviewedCase[] };
export type ProjectInfo = { id: string; name: string; description: string; created_at: string; owner_id?: string; owner_name?: string; deleting?: boolean; permissions?: { view: boolean; edit: boolean; review: boolean; share: boolean; delete: boolean } };
export type WorkspaceContext = { project: ProjectInfo | null; reports: Inspection[]; restoredRun: ClashReport | null };
export type ClashReport = {
  id: string;
  status: "completed" | "partial" | "failed";
  verdict: "unavailable" | "incomplete" | "findings" | "clear_in_scope";
  dataset: string | null;
  issues: ClashIssue[];
  diagnostics: Diagnostic[];
  elapsed_seconds?: number;
  coverage: { tested_elements: number; candidate_pairs: number; missing_geometry: number; nonmanifold: number; routing_elements: number; shared_reference_pairs: number; reference_elements?: number; source_elements?: number; subtraction_elements?: number; aggregate_elements?: number } | null;
  geometry_diagnostics?: { source_id: string; source_name: string; guid?: string; name?: string; ifc_type: string; reason: string; detail?: string }[];
  evaluation: { scope: "synthetic_only"; cases: number; precision: number; recall: number; tp: number; fp: number; fn: number; assessed_cases?: number; uncertain_cases?: number; typed_case_accuracy?: number; failed_cases?: string[]; case_results?: AnalyticCase[] } | null;
  report_url: string;
  project_id?: string | null;
  revision?: string | null;
  created_at?: string;
  parameters?: { model_ids: string[]; mode: "hard" | "clearance"; tolerance_mm: number; clearance_mm: number; shared_references_confirmed: boolean; link_id?: string | null };
  sources?: { id: string; name: string; sha256: string; discipline: string }[];
  drawing_link?: LinkResult | null;
};
export type RunSummary = Pick<ClashReport, "id" | "status" | "verdict" | "dataset" | "created_at" | "revision" | "parameters"> & { issue_count: number };
export async function connectProcessor(): Promise<Connection> {
  const connection = isTauri()
    ? await invoke<Pick<Connection, "base_url" | "token">>("backend_connection")
    : { base_url: "", token: "" };
  const response = await fetch(`${connection.base_url}/api/health`, {
    headers: authHeaders(connection),
  });
  const health = await response.json();
  if (!response.ok || !health.capabilities?.file_inspection || !health.processing_limits || !health.file_limits)
    throw new Error(
      "Bộ xử lý chưa sẵn sàng. Hãy mở lại ứng dụng hoặc kết nối lại.",
    );
  return { ...connection, file_limits: health.file_limits, processing_limits: health.processing_limits, deployment: health.deployment };
}
export function inspectFile(
  connection: Connection,
  file: File,
  onProgress: (percent: number) => void,
  setRequest: (request: XMLHttpRequest) => void,
  context: { project_id: string; logical_source: string },
  onProcessing?: (value: ProcessingProgress) => void,
): Promise<Inspection> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    setRequest(request);
    request.open("POST", `${connection.base_url}/api/inspections`);
    for (const [key, value] of Object.entries(authHeaders(connection)))
      request.setRequestHeader(key, value);
    request.setRequestHeader("Accept", "application/x-ndjson");
    request.timeout = (connection.processing_limits.timeout_seconds + 300) * 1000;
    request.upload.onprogress = (event) => {
      if (event.lengthComputable)
        onProgress(Math.round((event.loaded / event.total) * 100));
    };
    let offset = 0, streamed: Inspection | undefined, failed = false, lastActivity = 0;
    const heartbeat = setInterval(() => {
      if (!failed && lastActivity && performance.now() - lastActivity > 30000) {
        failed = true;
        reject(new Error(errorMessage("inspection_connection_lost")));
        request.abort();
      }
    }, 1000);
    request.onloadend = () => clearInterval(heartbeat);
    const isStream = () => request.getResponseHeader("Content-Type")?.includes("application/x-ndjson");
    function readEvents() {
      const text = request.responseText;
      if (text.length > 256 * 1024**2) throw new Error(errorMessage("processing_output_limit"));
      let end;
      while ((end = text.indexOf("\n", offset)) !== -1) {
        const line = text.slice(offset, end); offset = end + 1;
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        if (event.type === "progress" && typeof event.phase === "string") onProcessing?.(event);
        else if (event.type === "result" && typeof event.report?.id === "string") streamed = event.report;
        else if (event.type === "error") throw new Error(errorMessage(event.code));
        else throw new Error(errorMessage("inspection_connection_lost"));
      }
    }
    request.onprogress = () => {
      if (failed || !isStream()) return;
      lastActivity = performance.now();
      try { readEvents(); }
      catch (error) { failed = true; reject(error instanceof Error ? error : new Error(errorMessage("inspection_connection_lost"))); request.abort(); }
    };
    request.onload = () => {
      if (failed) return;
      try {
        if (isStream()) {
          readEvents();
          if (streamed) resolve(streamed);
          else reject(new Error(errorMessage("inspection_connection_lost")));
          return;
        }
        const payload = JSON.parse(request.responseText);
        if (request.status >= 200 && request.status < 300 && payload.id)
          resolve(payload);
        else reject(new Error(errorMessage(payload.detail)));
      } catch {
        reject(new Error("Bộ xử lý trả về kết quả chưa hợp lệ. Hãy thử lại."));
      }
    };
    request.onerror = () =>
      reject(
        new Error("Mất kết nối với bộ xử lý. Hãy kết nối lại rồi thử lại tệp."),
      );
    request.ontimeout = () =>
      reject(new Error("Kết nối hết thời gian chờ. Hãy thử một tệp nhỏ hơn."));
    request.onabort = () =>
      reject(new DOMException("Đã hủy kiểm tra", "AbortError"));
    const body = new FormData();
    body.append("file", file);
    if (context) for (const [key, value] of Object.entries(context)) body.append(key, value);
    request.send(body);
  });
}

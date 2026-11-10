# BIM Insight — Phối hợp và kiểm tra hồ sơ

**Bản web thử nghiệm Render Free:** xem [hướng dẫn deploy](docs/DEPLOY_RENDER.md) và Blueprint [render.yaml](render.yaml). Bản này có giới hạn upload 20 MiB, tệp lưu tạm và chưa có DWG/Qwen/Gmail SMTP.

## Kiểm tra DWG/DXF, IFC, PDF và va chạm 3D ngay trong app

**Kết luận tổng thể · Qwen3-4B · 09/11/2026:** mở lượt kiểm tra đã lưu, tìm khung **Kết luận tổng thể** phía trên bộ lọc/bảng rồi bấm **Tạo kết luận tổng thể**. App thống kê mọi cặp đã lưu, kể cả các trang chưa mở; bộ lọc trên bảng không làm đổi phạm vi. Qwen nhận mức tổng hợp và tối đa 6 nhóm tiêu biểu để viết nhận định, ưu tiên xử lý và bước tiếp theo. Số liệu chính xác và giới hạn hình học được hiển thị riêng. Không cần chạy lại IFC hoặc thêm DXF.

Kết luận có lịch sử trong MongoDB (`project_conclusions`), nút tải JSON và mở cặp minh chứng trong 3D. Thay nhãn rà soát sẽ làm bản cũ có cảnh báo cần cập nhật; không sửa lịch sử, kết quả hình học hoặc bộ nhãn. Người có quyền rà soát mới được tạo; thành viên chỉ xem có thể đọc bản đã lưu. Kiểm tra lại phiên đăng nhập/quyền trước khi lưu sau suy luận; xóa dự án xóa cả kết luận. Trong lúc Qwen chạy, app tạm giải phóng viewer và khóa tác vụ IFC/AI khác; có nút hủy.

Đã thử API bằng Qwen thật trên GPU RTX 3050 Laptop với bản sao báo cáo **9.014 cặp** (6.583 giao hình học, 2.431 bề mặt cần rà soát), khoảng **44–46 giây** gồm kiểm hash/nạp/sinh. Giữ trạng thái chưa đủ cơ sở vì hình học chưa kín; không biến số cặp thành số lỗi thiết kế đã xác nhận. UI desktop/375 px đã kiểm tra tạo/hủy/thử lại, JSON, lịch sử, cảnh báo nhãn thay đổi và chọn 3D bằng fixture phản hồi AI; phép thử GPU/API dùng model thật. Bằng chứng tại `.local/run-conclusions-20261109/`. Model gốc NF4 **chưa fine-tune**, kết luận cần người phụ trách rà soát. Áp dụng source mới bằng `Ctrl+C` rồi `npm.cmd start`; chưa build lại bộ cài Windows.

Kiểm chứng cuối phần kết luận: **351 backend tests đạt, 3 skip**, build frontend và hai parser stream đạt; UI desktop/375 px không có lỗi JavaScript. Chạy lại UI bằng `npm.cmd run test:conclusions` với Chromium theo cấu hình kiểm thử hiện có; script dùng database localhost riêng và tự dọn. Biên bản tổng hợp: `.local/run-conclusions-20261109/verification.json`.

**Sửa quyền cache Windows · 09/11/2026:** hai lượt người dùng lưu sau đó bị `clash_geometry_failed` ở Plumbing dù 6.404 cấu kiện đã dựng xong. Nguyên nhân là cache chuyển từ môi trường kiểm thử giữ DACL riêng của `CodexSandboxOffline`; tài khoản Windows chạy app không đọc hoặc thay thế được cache. IFC Plumbing được xác minh dựng thành công với cả 1 và 2 luồng. Đã bỏ cách chuyển cache này, chỉ xóa đúng 5 cache dẫn xuất do sandbox tạo và tạo lại qua luồng cache của app dưới tài khoản Windows thực; không sửa IFC, mapping, báo cáo cũ, tài khoản, cấu hình hoặc dữ liệu MongoDB/R2.

Lỗi đọc/ghi cache thiếu quyền nay được báo riêng bằng `clash_cache_permission_denied`, dừng trước khi dựng lại tốn thời gian và không tự xóa thư mục không có quyền. Giao diện ghi rõ **Kiểm tra trực tiếp IFC · DXF không bắt buộc**. Có thể chạy va chạm khi chỉ nhập các IFC cùng công trình/hệ tọa độ; DXF chỉ bổ sung đối chiếu mặt bằng.

Sau sửa quyền, đã chạy lại đúng 5 nguồn/ID/tham số của lượt người dùng: 18.783 cấu kiện, không thiếu hình học, 557/557 lô, 6.583 giao khối và 2.431 cặp bề mặt cần xem lại. Kết quả vẫn `partial` do 251 mesh chưa kín, không còn lỗi cache. Bộ kiểm thử giao diện xác nhận chạy thật 3 IFC không có DXF và hiển thị đúng thông báo quyền trên desktop/mobile; tình huống lỗi quyền ở UI dùng fixture, còn ACL và bộ Snowdon được kiểm tra dưới tài khoản Windows thực. Minh chứng mới ở `.local/clash-cache-fix-20261109/`; số đo/việc chuyển cache trong biên bản trước bên dưới là lịch sử, không dùng để suy ra quyền truy cập của tài khoản app.

**Dùng lại:** dừng app cũ bằng `Ctrl+C`, chạy `npm.cmd start`, mở dự án hiện tại và bấm **Chạy kiểm tra va chạm**. Không cần nhập lại IFC hoặc thêm DXF. Các lượt lỗi cũ vẫn giữ nguyên trong lịch sử; kết quả mới được lưu thành lượt mới.

Kiểm tra cuối: hai lượt đúng nguồn người dùng cho cùng 9.014 cặp cần xem lại, không thiếu hình học; lượt tạo lại cache 304,7 giây, lượt dùng lại 153,1 giây, RSS cây worker cao nhất khoảng 1,58 GiB. 335 backend tests đạt/3 skip, build và hai parser stream đạt. `npm.cmd run test:cache-permissions` kiểm tra luồng UI không DXF, thông báo lỗi quyền, desktop/mobile và không có lỗi JavaScript. Chi tiết `.local/clash-cache-fix-20261109/verification.json`.

**Phân loại IFC và phạm vi va chạm · 09/11/2026:** bộ đọc phân biệt cấu kiện vật lý, đối tượng cha, lỗ mở và đường/điểm tham chiếu. Chỉ tách riêng proxy có biểu diễn tham chiếu được xác định chỉ gồm đường/điểm, kể cả qua mapped item; không bỏ hàng loạt theo tên hoặc `IfcBuildingElementProxy`. Đối tượng khai báo Body nhưng không có bề mặt/khối vẫn được báo chưa đánh giá. JSON đầy đủ giữ kiểm kê từng đối tượng cùng GUID, loại, trạng thái và nguyên nhân lỗi.

Bước va chạm kiểm kê lại **IFC gốc**, xác minh checksum/đơn vị và chọn cấu kiện độc lập với bản xem GLB. Lỗ mở phải dựng được thể tích kín hợp lệ; lỗ mở lỗi và cấu kiện chủ bị ảnh hưởng được đánh dấu chưa đánh giá, không nhận khối tường chưa khoét làm kết quả đúng. Lô dựng hình lỗi được thử lại từng cấu kiện; phần thất bại còn lại ngăn kết luận đầy đủ. Mesh hở, tham chiếu chung chưa xác minh và giới hạn kết quả vẫn được báo riêng. Ngưỡng giao dưới 1 mm dùng lưới mịn hơn tương ứng; đây vẫn là kiểm tra trên lưới tam giác, không phải chứng nhận thiết kế chính xác tuyệt đối.

Cache hình học dùng policy 4. Khi kiểm tra nhiều IFC, app chuẩn bị cache từng nguồn rồi chỉ nạp **hai nguồn của một cặp** vào cây hình học. Với nhiều hơn hai IFC, mỗi cặp chạy trong tiến trình riêng và kết thúc trước cặp kế tiếp để Windows thu hồi bộ nhớ native. Giữ các giới hạn RAM/thời gian và số liệu đo, không tăng RAM vô hạn. Đủ mọi cặp có hình học mới được coi là hoàn tất; nguồn thiếu hình học hoặc chạm giới hạn vẫn là chưa đầy đủ.

**Áp dụng trên hồ sơ đã nhập:** dừng app cũ bằng `Ctrl+C`, chạy `npm.cmd start`, chọn đúng dự án rồi nhập lại IFC cùng tên nguồn. Cùng nội dung nhưng báo cáo dùng bộ đọc cũ sẽ được xử lý lại thành báo cáo mới; hồ sơ hiện tại cập nhật, lịch sử cũ và checksum nguồn được giữ nguyên. Không cần tạo Revision hoặc xóa dự án. 64 cảnh báo Architecture Snowdon trong bảng ngày 08/11 bên dưới đã được xác định là đường tham chiếu và được tách riêng ở bộ đọc mới.

**Kiểm chứng bản sửa:** cả 5 IFC Snowdon nhập thành công, mở được 5/5 mô hình trong app. Kiểm kê đủ 19.802 đối tượng `IfcElement`: 18.783 cấu kiện vật lý, 64 tham chiếu, 798 phần khoét và 157 đối tượng cha; không thiếu hình học khi chạy va chạm. Lượt hard từ cache trống hoàn tất 684/684 lô so sánh sau 371,7 giây; dùng lại cache mất 151,3 giây và khớp toàn bộ 9.022 bằng chứng/độ phủ. Clearance 1 mm / 50 mm hoàn tất 163,5 giây, thu được 22.559 cặp cần xem xét. RSS đỉnh của cây worker tối đa 1,59 GiB, dưới ngân sách thử 1,75 GiB; đây không phải tổng RAM cả trình duyệt/app. Kết quả giữ `partial` vì 251 mesh chưa kín và có giao bề mặt cần rà soát, không phải lỗi thiếu cấu kiện hoặc bị dừng RAM; các cặp chưa được chuyên gia xác nhận là lỗi thiết kế.

333 kiểm thử backend đạt, 3 ca tùy chọn skip; DPAPI được kiểm tra bằng tài khoản Windows với dữ liệu giả. Build, hai bộ kiểm thử stream và giao diện desktop/mobile đạt: thống kê tham chiếu, JSON đầy đủ, 3D cặp va chạm thật, nhập lại nguồn, mở lịch sử và xóa dự án thử có tệp dùng chung. 5 cache từng được chuyển vào app ở lượt này nhưng chưa được kiểm tra bằng quyền Windows thực; cách chuyển đó đã được sửa trong mục mới ở trên. Không ghi dự án thử vào Atlas/R2; giữ nguyên hồ sơ gốc, tài khoản, cấu hình và trọng số. Minh chứng lịch sử `.local/ifc-coverage-20261109/verification.json`. Chưa benchmark IFC 1–2 GiB, chưa build lại bộ cài hoặc có nghiệm thu chuyên gia.

**Quản lý dự án đơn giản hơn · 09/11/2026:** đã bỏ thao tác chọn/nhập Revision ở dự án, nhập tệp, căn khớp và kiểm tra va chạm. Chọn dự án rồi nhập tệp; bản cập nhật cùng nguồn tự trở thành hồ sơ hiện tại. Nội dung cũ và nguồn/hash của từng lượt kiểm tra được giữ để mở lại lịch sử. Metadata phiên bản cũ vẫn đọc được; các hướng dẫn Revision thủ công trong biên bản lịch sử phía dưới không còn áp dụng cho giao diện hiện tại.

**Xóa dự án:** trong **Dự án và lịch sử**, chọn dự án mình sở hữu → **Xóa dự án** → xác nhận **Xóa toàn bộ dự án**. App xóa hồ sơ đã nhập, GLB/DXF sinh ra, báo cáo, liên kết, kết quả, nhãn/nhận xét, đề xuất AI và metadata gắn với dự án; dọn cache riêng cùng các bản sao R2. Tệp dùng chung được giữ tới khi dự án cuối cùng được xóa. Tài khoản, cấu hình, hồ sơ gốc trong `data/inputs`, trọng số/adapter và bản xuất do người dùng lưu ngoài app được giữ nguyên. Đây là thao tác xóa vĩnh viễn; nếu mạng hoặc tệp đang mở làm gián đoạn, dự án giữ trạng thái chờ xóa để thử lại.

Xóa và đồng bộ R2 được tuần tự hóa qua MongoDB giữa các thiết bị. Khi app báo đang bận, đợi tác vụ kết thúc rồi thử lại; sau một tiến trình bị tắt đột ngột, khóa hết hạn sau tối đa 2 phút. Chi phí dung lượng trong app chỉ giảm một lần cho mỗi blob đã dọn, kể cả khi thử lại sau lỗi. `DeleteObject` không trừ ngân sách A/B nội bộ vì là [thao tác miễn phí của R2](https://developers.cloudflare.com/r2/pricing/).

Đã thử giao diện desktop/mobile: nhập bản sửa cùng nguồn, căn khớp/va chạm không nhập Revision, mở lại lượt cũ, hủy xác nhận bằng Escape và xóa dự án nhưng giữ tệp dùng chung của dự án khác. Đã thử R2 thật với **1 IFC mẫu mới 3.385 byte và 2 dự án thử**: xóa dự án đầu giữ blob, xóa dự án cuối dọn blob/quota; dữ liệu thử được dọn. Không xóa dự án đang làm việc của người dùng. Minh chứng backend/R2 ở `.local/project-lifecycle-20261109/`; kiểm thử trình duyệt dùng MongoDB localhost riêng, ảnh trong thư mục tạm Windows `bim-insight-project-lifecycle-20261109`.

**Sửa nhập IFC Snowdon và tiến độ RAM · 08/11/2026:** worker chỉ nạp phần xử lý cần thiết; tự chọn lô 64/128/512 cấu kiện theo ngân sách RAM, dùng 1–2 luồng và giải phóng mô hình IFC native trước khi tối ưu GLB. Giữ giới hạn an toàn và tham số dựng hình. Trong lúc nhập hoặc kiểm tra va chạm, app tạm đóng trình xem IFC để dành bộ nhớ, sau đó mở lại. Giao diện hiển thị bước xử lý, số đối tượng, RAM worker đang dùng/đỉnh, ngân sách và RAM hệ thống còn trống; cả báo cáo thất bại và JSON tải xuống đều giữ số đo. Đây là RSS được lấy mẫu, không phải toàn bộ RAM của app hoặc bảo đảm đọc mọi tệp trong mọi tình trạng bộ nhớ.

Nhập tệp hỗ trợ tiến độ NDJSON, nhịp phản hồi mỗi 2 giây và báo gián đoạn nếu luồng đã mở mất nhịp 30 giây; API JSON cũ vẫn hoạt động. Đã sửa khôi phục lựa chọn dự án bị xóa để tránh 404, đồng thời giữ đúng tệp người dùng đang chọn khi danh sách dự án tải lại.

Đã thử **5 IFC thật trong `data/inputs/37/MODEL` qua giao diện**, giới hạn worker 0,85 GiB, mở đủ 5/5 mô hình và xuất JSON Architecture đủ 6.393 cấu kiện:

| IFC Snowdon | Thời gian worker | Đỉnh RSS đo được | Cấu kiện đọc được | Kết quả |
| --- | ---: | ---: | ---: | --- |
| Architecture · 92,5 MiB | 116,7 giây | 773,1 MiB | 6.393 | `partial`, 64 cấu kiện chưa dựng được hình học |
| Electrical | 5,8 giây | 188,2 MiB | 2.107 | `completed` |
| HVAC | 8,5 giây | 188,9 MiB | 2.627 | `completed` |
| Plumbing | 28,1 giây | 312,8 MiB | 6.404 | `completed` |
| Structural | 9,5 giây | 148,7 MiB | 1.252 | `completed` |

Đây là bước nhập/xem, chưa phải kết luận va chạm toàn bộ Snowdon. 194 kiểm thử backend liên quan đạt, 3 ca tùy chọn skip; hai bộ kiểm thử đọc luồng, giao diện desktop/mobile và build frontend đạt. Trình duyệt thử sạch không có lỗi JavaScript. File `executors/200.js` có `M_ID` tại vị trí tương ứng trong ảnh thuộc **Urban VPN Proxy 5.14.4**; có thể tạm tắt tiện ích ở `chrome://extensions` rồi tải lại localhost để xác nhận trong trình duyệt đang dùng. Không sửa tiện ích/cấu hình trình duyệt.

Kiểm thử dùng database localhost/thư mục riêng đã dọn, không ghi Atlas/R2 làm việc; checksum cả 5 IFC gốc trước/sau khớp. Minh chứng và ảnh: `.local/snowdon-20261108/verification.json`. Chưa benchmark IFC 1–2 GiB hoặc build lại bộ cài Windows. Để áp dụng source mới, dừng terminal app cũ bằng `Ctrl+C`, chạy `npm.cmd start`, rồi nhập lại Architecture trong đúng dự án; lượt thất bại không khóa phiên bản nguồn.

**Lịch sử dọn dữ liệu · 08/11/2026:** tại thời điểm dọn đã xóa tệp nhập/kết quả/cache test, gồm 4 lượt kiểm tra, 20.956 kết quả và khoảng 2,55 GiB dữ liệu sinh ra; MongoDB không còn dữ liệu dự án và R2 được xác minh rỗng lúc đó. Sau đó người dùng đã nhập bộ Snowdon mới. Giữ nguyên 2 tài khoản, cấu hình, hồ sơ `data/inputs`, trọng số `data/models` và adapter `data/adapters`; 438 tệp được đối chiếu checksum trước/sau đợt dọn. Bản sao tài khoản được mã hóa DPAPI. Biên bản ở `.local/cleanup-20261108-result.json`; tóm tắt kiểm chứng trước đây được giữ trong `.local/cleanup-20261108/`. Các số đo và đường dẫn artifact Office/Timber phía dưới là lịch sử: cache/GLB test đã được dọn, lượt nhập/kiểm tra sau tạo lại.

**Sửa giới hạn bản xem IFC Office · 08/11/2026:** gộp các buffer hình học và accessor giống hệt trong GLB, giữ nguyên từng GUID, phép biến đổi, vị trí đỉnh, chỉ số tam giác, pháp tuyến và vật liệu. Trên HVAC Office 328,6 MiB/47.525 cấu kiện/10.910.233 tam giác, bản xem giảm từ **304,5 MiB xuống 41,4 MiB** và mở được trong ngân sách cũ; không tăng giới hạn RAM/trình xem hoặc giảm chi tiết hình học. Phép kiểm tra va chạm tiếp tục dùng IFC gốc.

Bước nhập dựng tối đa 512 cấu kiện mỗi iterator và giải phóng cache chuyển đổi giữa các lô; một lô lỗi được ghi nhận riêng, các lô sau vẫn được đọc. Lỗi tối ưu GLB giữ lại mapping và bản xem gốc còn hợp lệ. Lượt worker HVAC Office hoàn tất trong **216,36 giây**, đỉnh RSS **3.800 MiB**, ngân sách thử **3,95 GiB**; đây là số đo khi nhập, chưa phải thời gian chạy va chạm hoặc bảo đảm tốc độ cho mọi IFC.

Đã đối chiếu toàn bộ 47.525 cấu kiện trước/sau tối ưu; mở **5/5 mô hình Office, 76.491 cấu kiện** trên giao diện, chọn cấu kiện từng nguồn, xoay/zoom và xem desktop/mobile; xuất JSON đủ 47.525 cấu kiện HVAC. Backend: **278 ca đạt trong sandbox**, **15 ca DPAPI đạt khi chạy lại dưới tài khoản Windows**, 2 ca tùy chọn skip; build frontend đạt. Test chỉ dùng MongoDB localhost riêng; giữ nguyên Atlas/R2, tài khoản và cấu hình làm việc. Minh chứng: `.local/office-viewer-20261108/verification.json`. Các GLB còn nhiều hình học riêng biệt vẫn có thể chạm ngân sách; chưa benchmark IFC 1–2 GiB hoặc đóng gói lại Windows cho bản sửa này.

**Khắc phục RAM và tốc độ va chạm · 08/11/2026:** đọc lưới tam giác/đa giác có sẵn trong IFC bằng bộ đọc mesh, kể cả qua `IfcMappedItem`; chỉ áp dụng khi body không có hình học khác hoặc các feature cắt/bổ sung trên chính nó hay đối tượng cha. Đường cong, khối tham số và Boolean tiếp tục dùng OpenCascade với tham số chia lưới 0,5 mm. Mỗi iterator xử lý tối đa 128 cấu kiện. App dựng và lưu xong từng nguồn trong tiến trình riêng trước khi nạp lưới vào cây kiểm tra, tránh cộng dồn bộ nhớ dựng IFC và bộ nhớ so sánh.

**Đo trên 4 IFC Timber thật:** 12.625 cấu kiện, chế độ giao/khoảng hở với ngưỡng giao 0,1 mm và khoảng hở 10 mm. Lượt chưa có cache mất **211,45 giây**, lượt dùng lại cache **47,99 giây**; RAM cao nhất ghi nhận **2.757 MiB**, dưới ngân sách thử cố định **2,95 GiB**. Hai lượt khớp toàn bộ **14.100 cặp cần rà soát** và coverage; JSON đầy đủ khoảng 16,69 MiB. Báo cáo vẫn là `partial`: 2 cấu kiện nguồn thiếu hình học và 3.250 lưới chưa kín. Đây là kết quả hình học để rà soát, chưa phải lỗi thiết kế đã được chuyên gia xác nhận hoặc kiểm chứng độ chính xác 0,1 mm của công trình.

Cache hình học nằm tại `data/inspections/cache/clash-geometry`, dùng dấu vết IFC, mapping, phiên bản cache/bộ đọc và cấu hình dựng lưới để kiểm tra trước khi dùng lại. Cache hỏng được dựng lại; có khóa tệp giữa các tiến trình khi tạo cache. Cache phiên bản 2 thay thế cách xử lý cũ; chỉ lưu local, không đăng ký backup R2. Trên máy hiện tại đã chuẩn bị đúng 4 cache Timber, khoảng 1,32 GiB; IFC/mapping gốc được đối chiếu SHA-256 và giữ nguyên. Khi dừng vì RAM, báo cáo mới lưu mức sử dụng đo được, ngân sách và thời gian; giao diện phân biệt lịch sử lượt thất bại.

Đã chạy lại bằng chính cache trong thư mục app dưới tài khoản Windows đang sử dụng: **46,12 giây**, không dựng lại nguồn, kết quả/coverage khớp các lượt trên. Các số đo này là bộ kiểm tra hình học local; thời gian mở giao diện, lưu dự án hoặc đồng bộ mạng có thể cộng thêm.

Kiểm chứng: 115 kiểm thử backend đạt, 2 skip; thêm kiểm thử mặt đa giác có lỗ đạt ở cả hai bộ đọc. Giao diện đạt thử tiến độ/hủy/mất kết nối/số liệu RAM; bộ thử năng lực tổng hợp đạt 13 tệp, 6 IFC, 2.204 cấu kiện, 1.100 giao hình học và xuất đủ JSON. 16 mẫu hình học HVAC thật khớp giữa các cỡ lô và khi đọc lại cache. Minh chứng: `.local/clash-memory-20261108/verification.json`. Chưa benchmark IFC 1–2 GiB hoặc đóng gói lại bộ cài Windows cho bản sửa này.

**Phản hồi khi kiểm tra va chạm · 07/11/2026:** app hiển thị mô hình đang dựng, số cấu kiện/lô đã xử lý, thời gian và số bằng chứng đang thu thập. API gửi tiến độ cùng nhịp phản hồi mỗi 2 giây; nếu luồng bị ngắt hoặc mất nhịp 30 giây, giao diện báo mất kết nối và mở lại thao tác. Có giới hạn chờ trước khi nhận phản hồi và giới hạn tổng thời gian. Hủy/đóng kết nối chờ tiến trình worker dừng và dọn thư mục tác vụ. Lượt có kết quả hoàn chỉnh để kết nối HTTP kết thúc bình thường. Bộ kiểm tra dùng 1–2 luồng tùy RAM, giữ OpenCascade/sai số dựng lưới 0,5 mm; JSON lưu dự án/tải xuống giữ định dạng hiện có. Đã thử tiến độ trực tiếp, hủy, ngắt kết nối giữa luồng và kết quả một phần trên giao diện desktop/mobile; kiểm thử worker thật xác nhận không còn tiến trình sau khi hủy.

Đọc/xem IFC và tính va chạm là hai bước khác nhau. Mốc 07/11 đã dừng phép đo ở 15 phút khi còn dựng HVAC; mốc 08/11 phía trên đã chạy hết hình học đọc được của bộ Timber và trả báo cáo với phần thiếu được ghi rõ. Tiến độ kỹ thuật không phải kết luận không có xung đột. Bằng chứng cũ ở `.local/clash-fix-20261107/`; không ghi dữ liệu thử vào Atlas/R2 làm việc.

Bản **0.12.0** nhập DWG và chuyển sang DXF bằng ODA File Converter trên máy; xem layer, tải DXF sau chuyển và lưu nguồn/hash/kết quả trong dự án. Mọi lượt nhập mới yêu cầu dự án và nguồn logic; cập nhật tệp được quản lý tự động; đã bỏ phiên làm việc không gắn dự án cùng các nút sinh bộ mẫu khỏi giao diện/API sử dụng. Giữ phân quyền, cấp tài khoản Excel, đổi mật khẩu bắt buộc, khôi phục Gmail, hồ sơ cá nhân, 14 nhà 3D tương tác, R2 và Qwen local. Hướng dẫn DWG và chạy app ở cuối README.

- Hàng đợi nhập không yêu cầu chọn bộ môn. Backend nhận diện từ tên gốc: ARK/ARCH → Kiến trúc, STRUC/STR → Kết cấu, MEP/HVAC/ELE → Cơ điện; tên không rõ hoặc chứa nhiều nhóm được lưu là OTHER và vẫn được xử lý. Đây là nhãn tổ chức hồ sơ, không xác nhận nội dung hay căn khớp tọa độ.
- IFC: schema, số cấu kiện vật lý, loại/GUID, hình học, bounds theo mét và phần không đọc được; số lỗ mở/phần khoét được thống kê riêng. Màn hình tóm tắt tối đa 20 cấu kiện/100 chẩn đoán; nút Tải báo cáo JSON xuất toàn bộ chi tiết đã đọc, không cắt theo số mẫu trên màn hình. Chi tiết lưu thành asset riêng, được backup/khôi phục cùng dự án.
- PDF: tổng số trang, khổ trang vật lý, xoay trang và mẫu chữ trích xuất trong tối đa 500 trang đầu. Trang chưa xử lý hoặc không lấy được chữ được ghi rõ; chưa có OCR.
- DXF: metadata, đơn vị, layer/block/layout, chữ Unicode và preview Model space; zoom/pan, tìm và bật/tắt layer. Không tự đọc Xref, ảnh hoặc tài liệu ngoài. Đối tượng chưa hỗ trợ, lỗi audit và giới hạn preview được báo rõ. Preview tối đa 200.000 path/64 MiB; bảng layer giữ trạng thái hiển thị của nguồn.
- IFC thật: GLB có GUID theo nguồn, xoay/zoom/chọn cấu kiện, khung dây và bật/tắt từng mô hình. Đối tượng cha có hình học ở thành phần con được thống kê riêng; lỗ mở không được vẽ như khối đặc. Cấu kiện sai GUID hoặc thiếu đơn vị chiều dài không được tự coi là hợp lệ. GLB giữ vertex cục bộ và placement để giảm mất chính xác ở tọa độ lớn; renderer dùng gốc chung cục bộ.
- Liên kết tầng: chọn DXF, IFC tham chiếu, dự án, tầng và dịch/xoay; so nhiều trục độc lập trong sai số 1 mm trên cả hai đầu trục. Phải xác nhận cùng công trình/đúng tầng trước khi lưu liên kết nguồn–hash–transform–cao độ. Thay đầu vào hoặc transform xóa xác nhận đang hiển thị. Đây là phạm vi trục XY/tầng; không xác nhận mọi cấu kiện hoặc toàn bộ các bộ môn.
- Va chạm: giao hình học (hard) và khoảng hở (clearance) bằng lưới tam giác IfcOpenShell, giữ lỗ mở thật; AABB chỉ dùng tìm ứng viên. Chọn kết quả để tới 3D, tô hai màu và cô lập đúng cặp nguồn/GUID; cấu kiện lớn hiển thị bán trong suốt để thấy cấu kiện nằm bên trong. Có gợi ý xử lý theo quy tắc, coverage và báo cáo JSON lưu local; điểm được chiếu lên DXF khi có liên kết đúng nguồn/tầng đã xác nhận.
- Fixture kiểm thử tổng hợp chỉ dành cho bộ test offline, không sinh từ màn hình sử dụng. Báo cáo lịch sử có nguồn tổng hợp vẫn giữ nhãn xuất xứ; không được coi là đánh giá độ chính xác trên công trình thực.
- Dự án: lưu nguồn logic/hash và lịch sử chạy; cùng nội dung mở lại tệp đã lưu, nội dung mới tự cập nhật hồ sơ hiện tại. Mỗi lượt lịch sử dùng đúng nguồn và tham số của lượt đó. Có phân trang, chọn tối đa 200 hồ sơ để phối hợp; một lượt chạy mới vẫn cần xác nhận tọa độ. Trình xem tải lần lượt, ngân sách tổng dữ liệu GLB và ánh xạ 512 MiB; GLB mỗi mô hình tối đa 256 MiB, ánh xạ 64 MiB. Mô hình vượt giới hạn GLB vẫn có thể kiểm tra va chạm nếu ánh xạ và bản nguồn hợp lệ.
- Rà soát: lọc bộ môn/tầng/loại/trạng thái, nhóm theo cặp cấu kiện chính và giữ mọi bằng chứng. Lưu nhận xét/người rà soát/trạng thái riêng với kết quả hình học; cập nhật cũ bị chặn để tránh ghi đè nhãn mới. Xuất bộ nhãn JSON có nguồn/hash/ca âm tính và xuất xứ nhãn.
- Pilot kiểm thử offline: 60 ca phân tích có biến thể kích thước, góc xoay và vị trí. Nhãn người dùng chưa rà soát được giữ tách biệt. Bộ máy hiện báo 10 ca cần rà soát/thiếu dữ liệu, gồm bề mặt chạm xoay và một mesh chưa kín; kết quả là `partial`. Các biến thể thuộc cùng một họ mô hình, không phải 10 công trình độc lập hoặc dữ liệu chuyên gia đã duyệt.
- DWG: tự tìm ODA File Converter đã cài chính thức, kiểm chữ ký nhà phát hành; chuyển bản sao trong tiến trình riêng với tham số cố định, tối đa 10 phút và DXF đầu ra 256 MiB. Lưu DWG gốc, DXF, SHA-256 và phiên bản bộ chuyển; xem/căn khớp bằng luồng CAD chung. Thiếu bộ chuyển hoặc chuyển lỗi được báo rõ, không coi header là kết quả kiểm tra nội dung.
- Tối đa 200 tệp trong hàng đợi; IFC 2 GiB, DWG/DXF 256 MiB, PDF 100 MiB mỗi tệp. Xử lý tuần tự, tối đa 30 phút/tệp hoặc lượt kiểm tra hình học; có thể hủy. Ngân sách worker tối đa 8 GiB, đồng thời không quá nửa RAM vật lý và chừa khoảng 1 GiB RAM khả dụng khi bắt đầu (sàn worker 0,5 GiB). Kiểm tra chỗ trống đĩa trước khi xử lý. Dung lượng tệp được nhận không bảo đảm mọi hình học phức tạp đều xử lý được trên laptop; cần chia phạm vi khi thiếu tài nguyên.

**Tối ưu IFC và kiểm thử bộ 35 · 07/11/2026:** bước nhập dùng geometry iterator hybrid để tái sử dụng hình học lặp, chỉ thử lại riêng đối tượng chưa dựng được; đọc buffer và tính bounds theo lô để giảm cấp phát RAM. Giữ sai số dựng lưới preview mặc định 1 mm; va chạm vẫn dựng lại từ IFC gốc bằng cấu hình riêng 0,5 mm. Chọn Body vật lý, giữ đầy đủ nhiều Body cùng hệ tọa độ và áp dụng cùng quy tắc cho lỗ mở ở bước nhập/va chạm. Lỗ mở vẫn được kiểm tra hình học dù không vẽ thành khối đặc; lỗi được báo thiếu hình học.

**Tăng tốc tiếp:** bước nhập tự chọn 2 luồng khi có ít nhất 2 lõi CPU vật lý và ngân sách worker đạt 2,5 GiB; quyết định trước khi đọc mô hình. Khi ít RAM dùng 1 luồng, giữ nguyên bộ bảo vệ tài nguyên. Benchmark bộ xử lý trên cùng tệp HVAC: 77,6 giây/1 luồng → 42,2 giây/2 luồng; đỉnh RSS tăng từ 1.655 lên 2.066 MiB. Kiến trúc đo được 21,6 giây và Kết cấu 39,0 giây khi dùng 2 luồng. Đã đối chiếu đủ 7.211 cấu kiện HVAC: cùng GUID, tam giác, bounds và dữ liệu mesh/transform GLB theo GUID; không đổi độ chi tiết hoặc cấu hình va chạm. 101 kiểm thử liên quan đạt, 2 skip. Đây là số đo bộ xử lý; thời gian trên giao diện còn phụ thuộc RAM trống, tải CPU và tải 3D. Bằng chứng ở `.local/ifc-fix-20261107/speed-verification.json`.

Đã thử 4 IFC thật trong `data/inputs/35/MODEL` cùng một DWG và một DXF trên giao diện đã build: ARK 36 giây, ELE 4 giây, HVAC 79 giây, STRUC 77 giây; hiển thị 4/4 mô hình và tải JSON đầy đủ. STRUC có 8 đối tượng thiếu hình học ngay trong nguồn nên báo `partial`. Các lượt dev chịu áp lực RAM đã bị chặn ở ARK/HVAC; dùng `npm start` để chạy giao diện đã build cùng backend, giảm bộ nhớ của môi trường phát triển. Chừa khoảng 4–5 GiB RAM trống trước khi thử bộ này. Cả 403 tệp đầu vào giữ nguyên SHA-256; 144 backend tests đạt, 2 skip, kiểm thử giao diện 13 tệp/2.204 cấu kiện/1.100 giao hình học tổng hợp đạt. Chưa benchmark công trình thật 1–2 GiB; bộ cài Windows chưa build lại. Bằng chứng và giới hạn từng lượt ở `.local/ifc-fix-20261107/verification.json` và kế hoạch duy nhất bên dưới.

“Đọc được” và “Đã lưu liên kết tầng” chưa có nghĩa là không xung đột. Lần chạy va chạm cần xác nhận các IFC cùng công trình/hệ tọa độ gốc. Bản này chỉ so giữa các tệp, tối đa 50 IFC/100.000 cấu kiện/50.000 kết quả mỗi lượt; thiếu hình học, bề mặt chưa kín, tham chiếu chung chưa xác minh, giới hạn hoặc lỗi được báo là chưa đầy đủ. Chạm giới hạn kết quả sẽ dừng thu thập, giữ các kết quả đã có và đánh dấu `partial`; danh sách và các nhóm bằng chứng hiển thị 100 mục mỗi trang, JSON xuất toàn bộ kết quả đã lưu. Báo cáo chi tiết/đầu ra worker tối đa 128 MiB, báo cáo dự án tối đa 256 MiB; chạm giới hạn phải chia phạm vi, không được coi là kiểm tra hoàn chỉnh. Bề mặt trùng/giao chưa xác lập mức xuyên khối được đưa vào nhóm cần xem lại. Số đo xấp xỉ từ mesh; chỉ số giao của bộ máy không phải khoảng dịch chuyển tối ưu. Khoảng hở do người dùng chọn, không mặc định là quy chuẩn. Giao có chủ ý và đề xuất Qwen cần người thiết kế xem xét. Qwen hiện dùng model gốc NF4, chưa fine-tune chuyên ngành. Các mô hình trong thư viện học tập vẫn là minh họa.

**Đầu vào mục tiêu đã chốt ngày 01/11/2026:** bản vẽ **DWG/DXF kèm mô hình 3D**, ưu tiên IFC. Bản vẽ dùng để đối chiếu và định vị; mô hình 3D có cấu kiện, đơn vị và cao độ dùng để tính va chạm. Các nguồn cần cùng dự án và xác nhận căn khớp. DWG sẽ được chuyển thành DXF local trên bản sao; Qwen3-4B giải thích/đề xuất từ kết quả hình học. Xem tiến độ trong [kế hoạch 12 tuần duy nhất](docs/KE_HOACH_TRIEN_KHAI_12_TUAN.md).

Bản đóng gói tự chạy bộ xử lý local và không cần Python/Node/npm hay nhập token kỹ thuật. Giữ nguyên tệp nguồn; các bản xử lý tạm được dọn khi xong/hủy/đóng app, phiên bỏ dở được dọn khi khởi động lại. IFC đọc được được giữ trong `cache/models/<SHA-256>.ifc` để chạy lại va chạm; CAD/PDF nhập vào dự án có cache riêng trong `cache/files/`. Báo cáo, artifact xem, liên kết và kết quả va chạm lưu trong `reports/`, `assets/`, `links/`, `clashes/` tại `%LOCALAPPDATA%\com.noodt.bim-insight\inspections`. Metadata, nhãn, tài khoản và phiên đăng nhập ở MongoDB local hoặc Atlas theo cấu hình, mặc định database `bim_insight`. Cần sao lưu cả database và thư mục dữ liệu. LocalStorage chỉ giữ preference và sổ tay theo tài khoản/hệ thống; token đăng nhập chỉ nằm trong bộ nhớ. Hàng đợi chỉ giữ trong phiên giao diện; báo cáo 0.3 thiếu cache cần nhập lại IFC. MongoDB cần kết nối để đăng nhập, xác thực quyền và lưu lịch sử. Từ 0.12.0 không còn lựa chọn phiên tạm; mất kết nối dự án sẽ chặn nhập mới và cho phép tải lại/chọn dự án khác.

## Chạy từ source

A Vietnamese BIM workspace with a warm retro architecture-studio design, account roles, private project sharing and interactive Three.js models. Built on React, TypeScript, Vite and Tauri.

```sh
npm install
# Set up the backend .venv below before the first run.
npm run dev
```

Open http://127.0.0.1:1420. `npm run dev` starts both the local processor and Vite; the browser proxy keeps its authentication token on the server. For the desktop app, use `npm run tauri dev` with the Tauri Rust prerequisites installed. `npm run dev:ui` is a UI-only preview without file inspection.

The experience includes two sample lessons, local learning progress, course search, a construction quiz and a notebook with text export. The drawing library contains eight sample sheets across architecture, structure, MEP and 3D perspectives, with filtering, zoom, SVG/image download and links to related models.

Fourteen original procedural residence studies replace the generic decorative houses. The shared Three.js viewer supports orbit/zoom, pause, roof separation, camera presets, wireframe and component selection. Authentication, four role dashboards and seven workspace pages use distinct residences. Gallery posters are rendered from the same geometry, bundled locally and used as fallback if WebGL is unavailable. These are artistic massing studies; uploaded IFC models and engineering checks are separate.

Notes and workspace preferences are stored on the current device under the signed-in account. Library drawings and procedural models are illustrations; real project files are opened in the inspection workspace.

```sh
npm run build
npx playwright install chromium
npm run test:ui
npm run test:inspection
npm run test:coordination
npm run test:clash
```

Use the isolated test-server and account setup in section 8 before UI tests; never use the working database. An existing Chromium executable can be supplied through `PLAYWRIGHT_CHROMIUM_EXECUTABLE`. Checks cover roles, sharing, drawing/3D interactions, account-scoped notes, inspection and responsive layouts. Evidence goes into the ignored `data/artifacts/` folder.

The single implementation plan is [Kế hoạch triển khai 12 tuần](docs/KE_HOACH_TRIEN_KHAI_12_TUAN.md). Version 0.8.0 adds real account roles and project access control to private R2 sync/recovery and local Qwen3-4B NF4 advice. Real-project acceptance, specialist fine-tuning and engineering AI evaluation remain pending. Fonts and architectural imagery are bundled locally; the 3D module loads only when opened, with a static image fallback when WebGL is unavailable.

## Local backend — week 1

Use Python 3.12 x64 and either MongoDB Community or your configured Atlas cluster. Run from the repository root:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend/requirements.lock
.venv\Scripts\python.exe -m pip install --no-deps -e ./backend
.venv\Scripts\python.exe -m app
```

The standalone CLI API binds to `127.0.0.1:8765`. `GET /api/health` reports process status; `GET /api/ready` checks MongoDB. Protected routes require the local Bearer token from the ignored `data/runtime/backend-token` file plus `X-BIM-Session` returned by `/api/auth/login`. Bootstrap/register/login/state require the local Bearer token only; registration always creates User accounts. The normal UI starts its own processor on a free loopback port and supplies both headers. Do not start the standalone CLI separately for normal app use, or expose these tokens.

Authenticated clash endpoints: `GET /api/inspections/demo`, `POST /api/inspections/clashes` and `GET /api/inspections/clashes/{id}`. Requests select inspection IDs, mode, thresholds and explicit coordinate/shared-reference confirmations; arbitrary source paths are rejected. The job verifies cached source hashes and runs in a separate process with the same timeout, memory and cancellation controls as inspection.

Optional environment variables are `BIM_MONGODB_URI` (default `mongodb://127.0.0.1:27017`), `BIM_DATABASE` (default `bim_insight`), `BIM_DATA_DIR` (managed inspection data directory) and CLI `BIM_API_TOKEN` (at least 32 characters). The backend accepts loopback MongoDB or Atlas hosts under `.mongodb.net` with verified TLS; unsafe TLS options are rejected. Explicit URI environment configuration takes priority over the saved Windows DPAPI configuration. The backend rejects unknown browser origins and reports database failures as errors. Uploads use `POST /api/inspections`; authenticated JSON downloads use `GET /api/inspections/{id}/report`.

```powershell
$env:BIM_TEST_MONGODB_URI = 'mongodb://127.0.0.1:27017'
$env:BIM_RUN_DESKTOP_TEST = '1'
.venv\Scripts\python.exe -m pytest backend/tests -q
```

The API/account suite needs local MongoDB. Set `BIM_TEST_MONGODB_URI=mongodb://127.0.0.1:27017` for the optional integration checks and `BIM_RUN_DESKTOP_TEST=1` for the live ephemeral-port processor check. Fixtures use and remove isolated test databases. UI tests need the isolated dev server, `BIM_UI_TEST=1` and test accounts described in section 8; synthetic IFC/PDF fixtures preserve existing source files.

## IFC and AI feasibility checks

These commands generate technical artifacts in ignored directories. Use a new fixture directory; the generator refuses to overwrite existing inputs.

```powershell
.venv\Scripts\python.exe -m backend.research.hardware_probe
.venv\Scripts\python.exe -m backend.research.make_fixture data/fixtures/my-first-house
.venv\Scripts\python.exe -m backend.research.ifc_probe data/fixtures/my-first-house/MEP.ifc --output data/artifacts/week1/ifc-mep.json
```

The IFC probe preserves source files and reports GUIDs, types, world bounds in metres, triangle counts, exclusions and import failures. It does **not** detect clashes. Generated fixtures are labelled synthetic; the pipe is a rectangular envelope and the data has no engineering acceptance. IFC and pilot reports require a new `.json` destination and never overwrite existing files, including hardlink aliases; choose a new report path for each run.

Keep the AI environment separate from the backend:

```powershell
python -m venv .venv-ai
.venv-ai\Scripts\python.exe -m pip install torch==2.11.0+cu128 --index-url https://download.pytorch.org/whl/cu128
.venv-ai\Scripts\python.exe -m pip install -r backend/research/requirements-ai.lock
.venv-ai\Scripts\python.exe -m pytest backend/research/tests -q
.venv-ai\Scripts\python.exe -m backend.research.pilot download --output data/artifacts/week1/qwen-download.json
.venv-ai\Scripts\python.exe -m backend.research.pilot inference --output data/artifacts/week1/qwen-inference.json
.venv-ai\Scripts\python.exe -m backend.research.pilot train --output data/artifacts/week1/qwen-train-1.json --adapter-dir data/adapters/pilot-1
```

The approved `Qwen/Qwen3-4B` revision and weight hashes are pinned in `backend/research/configs/pilot.json`. The full training base downloads about 8 GB into `data/models`; this is local storage, not an R2 upload. Inference/training use only the local files after hash verification and do not execute remote model code. Leave enough disk space and run heavy IFC and AI tasks separately.

The pilot uses ten synthetic missing-data prompts to check runtime behaviour, and 20 optimizer steps to test training feasibility. These prompts are **not expert-labelled research data** and the pilot measures no engineering accuracy. Training succeeds only when optimizer updates occurred, losses are finite, the adapter changed, and its weights survive save/reload. GradScaler skips are counted separately; the loop allows at most twice the requested update count in attempts. OOM, missing dependencies or exhausting that limit produce a failed JSON result. The adapter unit tests use a tiny random Qwen3 model and cannot establish that the full 4B model fits the laptop.

On 30 October 2026, both full Qwen3-4B pilot configurations completed 20 real updates and adapter round trips. The chosen default keeps frozen embedding/head weights in fp16 (`keep_frozen_fp16=true`): observed CUDA allocation peaked at about 2.66 GiB, compared with 4.13 GiB for standard k-bit preparation. Process RSS peaked at about 4.61 GiB and total system RAM usage at 14.22 GiB. These short-prompt, batch-1 results do not guarantee longer-context training or engineering accuracy; run heavy IFC and AI tasks separately. Detailed evidence and remaining deployment work are recorded in the single plan.

To rebuild the Windows app and its IFC/PDF processor (Windows x64, Python 3.12 backend environment and Rust/Tauri prerequisites):

```powershell
npm.cmd run tauri -- build --bundles nsis
Get-FileHash src-tauri/target/release/bundle/nsis/bim_insight_0.4.0_x64-setup.exe -Algorithm SHA256
```

The build runs TypeScript/Vite and PyInstaller before Tauri packages the local processor. Training dependencies and Qwen weights are excluded from this runtime. After building, `node frontend/tests/inspection-native.mjs` generates its own synthetic IFC/PDF inputs and tests the production WebView2 app from a separate working directory, including normal window closure during processing and temporary-file cleanup. Its results go to `data/artifacts/inspection/native-*`; the app under test runs its packaged processor.

The bundle identifier is `com.noodt.bim-insight`. Build and native app tests do not by themselves establish a successful fresh installation or complete BIM/AI deployment. The installer is unsigned. Current inspection evidence is in `data/artifacts/inspection/`, and earlier hardware/AI evidence in `data/artifacts/week1/`; implementation status stays in the single plan linked above.

## Cấu trúc thư mục và cách chạy — cập nhật 02/11/2026

```text
BIM_Insight/
├── frontend/                 # Giao diện React/Vite
│   ├── src/                  # Trang, component, CSS, kết nối API
│   ├── public/               # Ảnh, favicon và tài nguyên tĩnh
│   ├── tests/                # Kiểm thử UI và app Windows
│   ├── design-system/        # Tài liệu thiết kế giao diện
│   ├── package.json          # Dependency và lệnh riêng frontend
│   └── vite.config.ts        # Cấu hình Vite; dist/ sinh khi build
├── backend/
│   ├── app/                  # FastAPI, MongoDB, đọc IFC/PDF, worker
│   ├── research/             # Pilot Qwen3-4B, cấu hình và test AI
│   ├── tests/                # Kiểm thử API/IFC/PDF/MongoDB
│   ├── requirements.lock     # Dependency Python đã khóa phiên bản
│   └── bim_backend.spec      # Đóng gói bộ xử lý bằng PyInstaller
├── data/                     # Dữ liệu local, được loại khỏi Git
│   ├── inputs/               # Đặt IFC/PDF/DXF/GLB cần thử tại đây
│   ├── fixtures/             # Dữ liệu IFC tổng hợp để kiểm thử
│   ├── models/               # Trọng số Qwen3-4B
│   ├── adapters/             # Adapter từ các pilot train
│   ├── inspections/          # Báo cáo, viewer/link/clash, cache IFC, phiên tạm
│   ├── artifacts/            # Log, ảnh kiểm thử, benchmark, bằng chứng
│   ├── cache/                # Cache công cụ và Hugging Face
│   ├── build/                # Tệp trung gian PyInstaller
│   └── runtime/              # Token backend CLI, không chia sẻ
├── src-tauri/                # Vỏ app Windows/Rust, resources và bộ cài
├── scripts/                  # Điều phối dev và build backend
├── docs/                    # Một kế hoạch triển khai 12 tuần
├── .venv/                   # Môi trường Python backend của máy
├── .venv-ai/                # Môi trường AI riêng của máy
├── package.json              # Lệnh dùng chung, npm workspace frontend
├── package-lock.json         # Lockfile npm duy nhất
└── README.md
```

Hai môi trường Python giữ tại gốc vì venv đã cài không hỗ trợ di chuyển trực tiếp. `node_modules/`, `frontend/dist/`, `src-tauri/target/` và `src-tauri/binaries/` là thư mục do công cụ sinh. Dữ liệu cũ đã chuyển vào `data/`; nội dung báo cáo lịch sử vẫn ghi đường dẫn tại thời điểm chạy.

### 1. Chuẩn bị lần đầu hoặc trên máy mới

Dùng PowerShell tại **thư mục gốc** cho các lệnh dưới đây. Cần Node.js từ 22.12, Python **3.12 x64**; app Windows từ source/build cần thêm Rust, MSVC Build Tools, Windows SDK và WebView2. MongoDB local hoặc Atlas phải kết nối được để xác thực tài khoản và quản lý dự án, kể cả khi dùng phiên tạm.

```powershell
Set-Location 'D:\dowload\BIM_Insight'
npm.cmd install
if (-not (Test-Path '.venv\Scripts\python.exe')) { py -3.12 -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .\backend
```

Máy này đã có môi trường; những lần sau chỉ cần chạy mục 2 hoặc 3. Npm ở gốc tự cài dependency cho workspace `frontend/`. Chế độ local mặc định cần MongoDB đang chạy tại `127.0.0.1:27017`; để dùng Atlas đã có, cấu hình theo mục 3a.

### 2. Chạy nhanh giao diện và backend để phát triển

```powershell
npm.cmd run dev
```

Mở **http://127.0.0.1:1420** → **Kiểm tra hồ sơ** → chọn/kéo thả DXF/IFC/PDF → chọn bộ môn → **Bắt đầu kiểm tra**. Kéo xuống khu vực **Phối hợp bản vẽ và mô hình** để mở layer và 3D. Lệnh tự mở backend local và proxy có xác thực; giữ terminal này mở, nhấn **Ctrl+C** để dừng. Báo cáo ở `data/inspections/reports/`.

Với bộ Nha02: nhập DXF **Floor Plan – MẶT BẰNG KIẾN TRÚC TẦNG 1** và IFC ARCH/STR/MEP; điền dự án, chọn IFC ARCH tham chiếu và tầng **TẦNG 1 · 0.000 m**, giữ dịch X/Y và góc xoay bằng 0 rồi bấm **So trục XY**. Kiểm tra phạm vi trước khi tự đánh dấu xác nhận và lưu. Trùng GUID giữa ARCH–STR được báo trên màn hình; liên kết trục chưa phải kết quả kiểm tra va chạm.

**Thử va chạm khi chưa có IFC tuyến ống:**

1. Bấm **Dùng bộ mẫu tổng hợp** ở ô nhập → **Bắt đầu kiểm tra** để đọc 4 tệp mẫu. Hàng đợi cần còn ít nhất 4 chỗ; tệp của bạn được giữ nguyên.
2. Trong nhóm **Bộ mẫu tổng hợp**, kéo xuống **Kiểm tra va chạm 3D**. Giữ 3 IFC, kiểm tra mô hình chung rồi đánh dấu xác nhận công trình/hệ tọa độ → **Chạy kiểm tra va chạm**.
3. Mặc định tìm được 2 cặp giao. Đổi chế độ sang **Giao và khoảng hở**, giữ 50 mm rồi chạy lại: 4 cặp, gồm khoảng cách xấp xỉ 40 mm. Bấm số cặp để xem hai cấu kiện trong 3D; tải báo cáo bằng nút JSON.
4. Muốn đánh dấu trên DXF: điền dự án bộ mẫu, chọn IFC STR và tầng DEMO Level 1, giữ dịch/xoay 0, so trục rồi tự xác nhận/lưu liên kết. Chạy lại va chạm, chọn cặp để xem điểm chiếu XY trên mặt bằng.

Chọn **Hồ sơ của bạn** để kiểm tra Nha02 riêng; xác minh tọa độ và bộ nguồn trước khi chạy. Không có tuyến ống thì app chỉ kiểm tra cấu kiện thực sự có trong IFC, và báo chưa đánh giá hệ tuyến còn thiếu. Tham chiếu dùng chung chỉ được bỏ qua sau khi bạn đã xác minh; kết quả hình học và gợi ý theo quy tắc cần người thiết kế rà soát. Đổi nguồn/tham số/liên kết làm kết quả đang xem hết hiệu lực. Hủy rồi chạy lại được; bản IFC đã cache và báo cáo hoàn tất vẫn được giữ.

Các lệnh `npm.cmd` chạy được cả khi PowerShell chặn script `npm.ps1`.

**Lưu dự án và thử pilot 60 ca:**

1. Mở **Dự án và lịch sử** → nhập tên → **Tạo dự án** (hoặc chọn dự án có sẵn). Dự án được chọn trước khi nhập tệp để gắn đúng metadata.
2. Bấm **Dùng bộ pilot 60 ca** → **Bắt đầu kiểm tra**. App đọc 3 IFC và 1 DXF; chọn nhóm pilot để mở riêng với hồ sơ thật/bộ mẫu 6 ca. Giữ nguồn logic mặc định hoặc đặt tên dễ nhận diện như `ARCH`, `STR`, `MEP`.
3. So/lưu liên kết tầng khi muốn định vị trên DXF. Chạy kiểm tra 3D sau khi xác nhận hệ tọa độ. Với pilot mặc định: hard có 29 cặp gắn cờ (20 giao + 9 bề mặt cần xem lại); clearance có 35 cặp. Kết quả `partial`, không phải toàn bộ 60 ca đã được kết luận đúng.
4. Dùng bộ lọc và nút **Rà soát** để lưu trạng thái, tên người rà soát và nhận xét. Trong **Bộ ca gán nhãn**, xem cả ca âm tính và lưu nhãn người dùng riêng. **Xuất bộ nhãn JSON** giữ nguồn/hash/tham số/xuất xứ nhãn; nhãn không tự sửa IFC hoặc xác nhận chuyên gia.
5. Đóng/mở app, vào **Kiểm tra hồ sơ**: dự án và lượt gần nhất được khôi phục. Chọn lượt khác trong **Lịch sử kiểm tra** để xem đúng nguồn/nhận xét. Muốn chạy mới, xác nhận lại tọa độ.
6. Khi tệp nguồn thay đổi, chọn cùng dự án và nhập lại tệp với cùng tên nguồn logic. App tự cập nhật hồ sơ hiện tại; lịch sử vẫn mở đúng các nguồn cũ. Đồng bộ dự án lên R2 trước khi chuyển máy; app tự lấy lại tệp đã xác minh khi cache thiếu hoặc sai hash.

Không có MongoDB thì chọn **Phiên tạm**, hoặc **Mở phiên tạm** ở thông báo lỗi. Chế độ này xử lý local như trước; muốn lưu lịch sử và nhãn, chọn dự án rồi nhập/chạy lại hồ sơ.

Chạy riêng giao diện bằng `npm run dev:ui` khi chỉ sửa UI; lệnh này không mở bộ xử lý IFC/PDF.

### 3. Chạy app Windows từ source

```powershell
# Chuẩn bị resources một lần trước khi chạy desktop trên source mới:
npm.cmd run build:backend
npm.cmd run tauri -- dev
```

App tự mở cửa sổ Windows và bộ xử lý. Chế độ dev lưu báo cáo tại `data/inspections/`; bản app đã đóng gói vẫn lưu ở `%LOCALAPPDATA%\com.noodt.bim-insight\inspections` để giữ dữ liệu người dùng hiện có. `BIM_DATA_DIR` có thể chỉ định một thư mục khác.

### 3a. Kết nối Atlas đã có trên máy

Đóng app/dev server trước khi đổi kết nối. Tại thư mục gốc, chạy:

```powershell
.\.venv\Scripts\python.exe -m app --configure-database
```

Dán URI Atlas có tài khoản/mật khẩu vào lời nhắc **MongoDB URI (hidden)**; ký tự không hiển thị. Nhấn Enter ở **Database [bim_insight]** để dùng database riêng của app. Lệnh kiểm tra kết nối trước khi lưu; lỗi xác thực/mạng không ghi đè cấu hình đang có. Không đưa URI thật vào chat, Git hoặc lệnh có ghi lịch sử shell.

Sau khi thành công, cấu hình được Windows DPAPI mã hóa theo tài khoản hiện tại tại `data/inspections/database.dpapi` và `%LOCALAPPDATA%\com.noodt.bim-insight\inspections\database.dpapi`. Source và app Windows đọc cấu hình này khi khởi động. Nếu đã đặt `BIM_DATA_DIR`, cấu hình source được lưu tại thư mục đó. Tệp DPAPI cần được thiết lập lại khi đổi tài khoản/máy Windows; không đưa tệp này vào bộ cài.

Mở lại app và đăng nhập → **Kiểm tra hồ sơ → Dự án và lịch sử**. Với Admin, phần đầu panel hiện **MongoDB Atlas · bim_insight · host đang dùng** khi truy vấn thành công. Database xuất hiện trong Compass sau lần ghi đầu tiên, chẳng hạn tạo Admin. Kết nối đã lưu trong Compass chỉ được dùng lại khi bạn chủ động cung cấp URI hoặc cho phép xuất kết nối đó.

`BIM_MONGODB_URI` và `BIM_DATABASE` trong môi trường được ưu tiên hơn cấu hình đã lưu. Atlas mất kết nối sẽ báo lỗi; app không tự chuyển dữ liệu sang MongoDB local và không bỏ qua xác thực. **Mở phiên tạm** dùng khi không muốn gắn tệp vào dự án; MongoDB vẫn cần cho phiên đăng nhập. R2 sao lưu tệp sau khi bạn bấm đồng bộ; tệp chưa đồng bộ cần giữ trên thiết bị.

Tham khảo [kết nối ứng dụng với Atlas](https://www.mongodb.com/docs/atlas/driver-connection/) và [TLS trong PyMongo](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/security/tls/).

### 4. Chạy riêng backend để kiểm tra API

```powershell
.\.venv\Scripts\python.exe -m app
```

API ở **http://127.0.0.1:8765/api/health**; các route bảo vệ dùng token trong `data/runtime/backend-token`. Đây là chế độ debug API riêng; chạy giao diện đầy đủ bằng mục 2 hoặc 3. Không gửi token lên Git hoặc kèm báo cáo lỗi.

### 5. Build và mở bản Windows đóng gói

```powershell
npm.cmd run tauri -- build --bundles nsis
```

Lệnh tự build frontend, backend rồi tạo bộ cài tại:

```text
src-tauri/target/release/bundle/nsis/bim_insight_0.12.0_x64-setup.exe
```

Có thể mở trực tiếp `src-tauri/target/release/bim_insight.exe` tại máy build; giữ nguyên thư mục `backend/` bên cạnh EXE. Bản đóng gói không cần terminal, Node hay Python dev để kiểm tra IFC/PDF. Đăng nhập, dự án/lịch sử/nhãn cần MongoDB local hoặc Atlas được cấu hình và đang kết nối. Bộ cài chưa ký số.

### 6. Kiểm thử sau khi sửa source

```powershell
npm.cmd run build
.\.venv\Scripts\python.exe -m pytest backend/tests -q
```

Các test API/tài khoản cần MongoDB local đang chạy. Đặt `BIM_TEST_MONGODB_URI=mongodb://127.0.0.1:27017` và `BIM_RUN_DESKTOP_TEST=1` trước lệnh pytest để bao gồm kiểm thử tích hợp/process. Với UI, chuẩn bị database test và tài khoản theo **mục 8** trước khi chạy các lệnh dưới đây:

```powershell
npm.cmd run test:ui
npm.cmd run test:inspection
npm.cmd run test:coordination
npm.cmd run test:clash
npm.cmd run test:projects
npm.cmd run test:project-offline
npm.cmd run test:ai-ui
```

Cần Chromium của Playwright; cài lần đầu bằng `npx playwright install chromium`, hoặc đặt `PLAYWRIGHT_CHROMIUM_EXECUTABLE` tới Chromium đã có. `test:projects` tạo dữ liệu qua API thật, vì vậy chỉ dùng server local tách biệt và `BIM_UI_TEST=1` theo mục 8. `test:ai-ui` chạy sau `test:projects`, dùng provider giả lập để thử hủy/lỗi/thử lại và phản hồi. Test backend tự dùng database riêng và dọn sau khi chạy; thiếu MongoDB thì chưa kiểm chứng được phân quyền. Các test native mặc định dùng local; mục 7 là luồng tùy chọn cho Qwen/R2 thật.

Sau khi build Windows, **tắt dev server** rồi chạy `npm.cmd run test:native` và `npm.cmd run test:projects-native` lần lượt. Test thứ hai cần MongoDB, mở app hai lần với profile/database/data riêng để kiểm tra khôi phục lịch sử và nhãn; có lưu lại namespace test trong kết quả, không dùng database làm việc. Hai test dùng WebView2 CDP local cho kiểm thử, không đưa cờ debug vào cấu hình phát hành. Test AI riêng: `.\.venv-ai\Scripts\python.exe -m pytest backend/research/tests -q`. Log và ảnh kiểm thử nằm trong `data/artifacts/`.

### 7. Kết nối R2 và Qwen để chạy đầy đủ trong app

**R2:** tạo bucket **Standard, private**, ví dụ `bim-insight`; trong R2 → **Manage API Tokens**, tạo S3 token **Object Read & Write** chỉ cho bucket đó. Giữ endpoint S3, Access Key ID và Secret Access Key để tự nhập trên máy. Secret chỉ hiện một lần khi tạo token. Xem [hướng dẫn Cloudflare](https://developers.cloudflare.com/r2/api/tokens/).

```powershell
# Chạy ở thư mục gốc; đóng app/dev server trước khi cấu hình:
.\.venv\Scripts\python.exe -m app --configure-r2
```

Nhập endpoint dạng `https://<account-id>.r2.cloudflarestorage.com`, tên bucket và hai key ở lời nhắc nhập ẩn. Lệnh kiểm tra quyền đọc bucket cùng MongoDB trước khi lưu `r2.dpapi` cho source và app Windows. Key không nằm trong frontend hoặc bộ cài. Mở lại app → chọn dự án → **Đồng bộ dự án lên R2**. Chỉ khi hiện đủ số tệp **đã xác minh** mới coi bộ tệp đã có bản sao. Lỗi mạng hoặc hủy có thể thử tiếp; các tệp hoàn tất không upload lại. Báo cáo, nguồn IFC/DXF/PDF/DWG, GLB/mapping/preview và liên kết tầng được đồng bộ; nhãn và đề xuất ở MongoDB.

App cảnh báo từ 7 GB, chặn thêm dung lượng từ 8 GB và giữ chỗ cho cả upload chưa rõ kết quả. Giới hạn mỗi tệp đồng bộ là 2 GiB, request mỗi tháng là 800.000 Class A/8.000.000 Class B. App đối soát các tệp khác trong bucket định kỳ; bộ đếm và giới hạn này không phải hard billing cap cho toàn tài khoản. [R2 Standard hiện có 10 GB-month, 1 triệu A/10 triệu B miễn phí mỗi tháng](https://developers.cloudflare.com/r2/pricing/); không tự upload bộ trọng số gốc khoảng 8 GB lên R2.

**Qwen local:** giữ `.venv-ai` theo `backend/research/requirements-ai.lock` và bộ model đã tải ở `data/models/qwen3-4b`. Cấu hình đường dẫn tuyệt đối được lệnh sau tự lưu bằng DPAPI:

```powershell
.\.venv\Scripts\python.exe -m app --configure-ai --ai-python .venv-ai/Scripts/python.exe --ai-model data/models/qwen3-4b
```

Mở lại app, chọn dự án rồi chạy kiểm tra va chạm → **Rà soát** một cặp → **Tạo đề xuất bằng Qwen**. Có thể chọn tối đa 3 PDF đang mở thuộc cùng dự án; chỉ trích đoạn chữ đã đọc được, chưa OCR. Model/worker chạy offline, kiểm tra hash trước mỗi lần nạp, chia sẻ một slot với xử lý IFC, có hủy và timeout 180 giây. Bản Windows cần môi trường AI/model ngoài bộ cài và GPU CUDA phù hợp; thiếu prerequisite sẽ báo lỗi, không tự tải hoặc gọi AI cloud.

Đề xuất dùng model gốc **Qwen3-4B NF4**, kèm bằng chứng, nguồn/phiên bản, phương án định tính và dữ liệu còn thiếu. Backend gắn GUID từ báo cáo, kiểm tra target/citation và từ chối số đo do model tự sinh. **Lưu phản hồi đề xuất** tách khỏi nhãn xung đột; chọn để xem xét chưa phải phê duyệt kỹ thuật hoặc xác nhận đã sửa xong. Model gốc còn có thể trả lời không đạt kiểm tra và cần rà soát; không tự sửa RVT/DWG.

Thư mục model gốc chỉ chứa các tệp runtime đã pin, `source-manifest.json` và metadata tải về trong `.cache`. Đặt adapter, trọng số thay thế hoặc chat template thêm ở thư mục riêng; app từ chối các tệp override để provenance luôn đúng với model đã xác minh.

**Chuyển máy:** cấu hình lại Atlas/R2 trên tài khoản Windows mới, dùng cùng database/bucket, rồi chọn dự án/lượt kiểm tra đã đồng bộ. App kiểm tra SHA-256 và tải tệp vào cache mới. Cài môi trường AI/model rồi cấu hình AI riêng trên máy đó; DPAPI của máy cũ không dùng như một file key mang sang máy mới.

**Test native tích hợp thật** sau khi build và tắt dev server (tạo namespace/prefix test riêng trên các dịch vụ đã cấu hình):

```powershell
$env:BIM_TEST_DATABASE_CONFIG="$PWD\data\inspections\database.dpapi"
$env:BIM_TEST_R2_CONFIG="$PWD\data\inspections\r2.dpapi"
$env:BIM_TEST_AI_CONFIG="$PWD\data\inspections\ai.dpapi"
$env:BIM_TEST_INTEGRATIONS='1'
npm.cmd run test:projects-native
```

Test này chạy Qwen thật, đồng bộ R2, đóng app rồi mở lại với cache trống để kiểm tra khôi phục. Dữ liệu test tách theo timestamp và được ghi trong `data/artifacts/projects/native-*/result.json`; không chạy với dữ liệu gốc Nha02. Các kiểm tra mã hóa DPAPI và WebView2 cần chạy dưới tài khoản Windows thật, ngoài sandbox hạn chế hồ sơ người dùng. Chỉ chạy luồng tích hợp này khi chủ động muốn tạo dữ liệu trên các dịch vụ đã cấu hình; kiểm thử phân quyền 0.8.0 dùng localhost, không cần Atlas/R2/Qwen thật.

### 8. Chạy bản phân quyền 0.8.0

Tại thư mục gốc, dùng cấu hình MongoDB đã lưu của bạn:

```powershell
Set-Location 'D:\dowload\BIM_Insight'
npm.cmd run dev
```

Mở `http://127.0.0.1:1420`. Lần đầu, tự đặt tên đăng nhập và mật khẩu Admin (ít nhất 12 ký tự); không có tài khoản mặc định. Hồ sơ cũ chưa có chủ được nhận vào Admin này, giữ nguyên tệp nguồn. Nếu kết nối bị ngắt giữa bước tạo tài khoản/nhận hồ sơ, đăng nhập lại bằng tài khoản vừa tạo để tiếp tục. Các tài khoản đăng ký tiếp theo luôn là **Người dùng**; Admin vào **Tài khoản** để đổi vai trò hoặc khóa/mở khóa. Đổi mật khẩu trong **Tài khoản của tôi**. Đóng/tải lại app yêu cầu đăng nhập lại.

| Vai trò | Giao diện và quyền hiện có |
|---|---|
| Admin | Dashboard quản trị; danh sách tài khoản, đổi vai trò, khóa/mở khóa; dự án riêng và hồ sơ được chia sẻ. Không tự đọc được dự án riêng của người khác. |
| Giảng viên | Dashboard rà soát; mục **Hồ sơ được chia sẻ**; nhận xét/phản hồi AI khi chủ dự án cấp quyền rà soát; có thể tạo dự án riêng. |
| Sinh viên | Dashboard thực hành; tạo/nhập/kiểm tra hồ sơ riêng, xem nhận xét và chia sẻ dự án để nhận góp ý. |
| Người dùng | Dashboard dự án; tạo/nhập/kiểm tra hồ sơ riêng, chia sẻ và xem hồ sơ được cấp quyền. |

Sinh viên và Người dùng cùng quyền dự án riêng trong mốc này. Mỗi chủ dự án có thể tự ghi nhận xét của mình; nhận xét được gắn danh tính thật trong hệ thống, chưa phải điểm/chấp thuận của giảng viên. Chưa triển khai khóa học, lớp học, giao bài hay chấm điểm theo rubric.

Trong **Dự án và lịch sử → Chia sẻ và quyền truy cập**, nhập đúng tên đăng nhập và chọn **Chỉ xem hồ sơ** hoặc **Rà soát — Giảng viên / Admin**. Người được chia sẻ không được sửa nguồn, chạy lại kiểm tra, đồng bộ R2 hoặc chia sẻ tiếp. Quyền xem vẫn cho phép xem 2D/3D, báo cáo và nhận xét; quyền rà soát thêm lưu nhận xét/đề xuất. Có thể thu hồi bất kỳ lúc nào; backend kiểm tra quyền ở từng yêu cầu. Nhấn **Tải lại** để cập nhật quyền và dọn hồ sơ đang hiển thị sau khi bị thu hồi.

Mật khẩu lưu PBKDF2 có salt; token phiên lưu hash trong MongoDB, hết hạn sau 8 giờ. Đăng xuất, khóa tài khoản và đổi mật khẩu thu hồi phiên tương ứng. Bảo vệ Admin cuối cùng, chống ghi đè thay đổi vai trò đồng thời và không cho tự hạ quyền Admin. Các API tải artifact, R2 và AI kiểm tra quyền ở backend trước khi đọc/xử lý.

**Ranh giới triển khai:** phù hợp backend Windows do bạn quản lý. Người kiểm soát máy/backend và credential Atlas/R2 vẫn có thể truy cập trực tiếp database/storage. Muốn phát hành cho nhiều máy sinh viên không tin cậy cần API trung tâm giữ credential; mốc này chưa triển khai API trung tâm. Không đưa credential vào bộ cài hoặc gửi cho người dùng cuối.

**Kiểm thử giao diện trên database local tách biệt:** cần MongoDB tại `127.0.0.1:27017`. Không chạy bằng database làm việc hoặc URI Atlas. Terminal thứ nhất:

```powershell
$env:BIM_MONGODB_URI='mongodb://127.0.0.1:27017'
$env:BIM_DATABASE='bim_insight_test_ui_roles'
$env:BIM_DATA_DIR="$PWD\data\artifacts\rbac-080\manual-ui-data"
npm.cmd run dev
```

Terminal thứ hai, với database test mới/chưa có Admin, chạy lần lượt:

```powershell
$env:BIM_UI_TEST='1'
npm.cmd run test:accounts
npm.cmd run test:ui
npm.cmd run test:inspection
npm.cmd run test:coordination
npm.cmd run test:clash
npm.cmd run test:projects
npm.cmd run test:sharing
npm.cmd run test:account-session
npm.cmd run test:project-offline
npm.cmd run test:ai-ui
```

`test:accounts` tạo 4 tài khoản dùng riêng cho test; mật khẩu test không dùng ở database thật. `test:sharing`/`test:ai-ui` cần `test:projects` tạo pilot trước. Các test native mặc định dùng database local riêng và tự dọn; pytest tự dọn database của từng fixture. Sau bộ test trình duyệt thủ công, tắt dev server rồi dọn **đúng database test đã đặt ở trên**:

```powershell
@'
from pymongo import MongoClient
client = MongoClient("mongodb://127.0.0.1:27017")
client.drop_database("bim_insight_test_ui_roles")
client.close()
'@ | .venv\Scripts\python.exe -
```

Tắt terminal test hoặc xóa các biến `BIM_MONGODB_URI`, `BIM_DATABASE`, `BIM_DATA_DIR`, `BIM_UI_TEST` trước khi chạy lại app làm việc để dùng đúng cấu hình MongoDB đã mã hóa.

### 9. Giao diện nhà ở 3D và animation

Chạy như mục 8 bằng `npm.cmd run dev`; bản Windows nằm ở đường dẫn bộ cài mục 5. Đăng nhập dùng Fallingwater, đăng ký Villa Savoye, bước tạo Admin Farnsworth House. Form giữ đăng ký Người dùng mặc định. Animation chuyển form ngắn; mô hình tự xoay chậm và tạm dừng trong lúc nhập liệu. Chế độ giảm chuyển động của hệ điều hành sẽ dừng tự xoay/animation, vẫn cho phép xoay/zoom bằng cử chỉ hoặc bàn phím.

Kéo mô hình để xoay, cuộn chuột hoặc chụm hai ngón để zoom. Không còn thanh 5 nút nổi. Mô hình tự quay lại sau **5 giây kể từ thao tác cuối/thả chuột**, không quay khi đang giữ chuột. Khi canvas có focus, dùng **←/→, ↑/↓, +/−, Home**; **Space** để dừng/tiếp tục quay. Trạng thái dừng bằng Space được giữ đến khi bạn bật lại hoặc đổi cảnh. Trong cửa sổ mô hình đầy đủ có **Tách mái**, **Khung dây**, góc nhìn và danh sách cấu kiện. Nếu WebGL không khả dụng, app hiển thị poster của chính mô hình đó. Viewer IFC của dự án giữ các công cụ phục vụ kiểm tra kỹ thuật.

| Giao diện | Nhà ở minh họa · nguồn tham khảo |
|---|---|
| Đăng nhập | [Fallingwater](https://fallingwater.org/media-resources/fallingwater-facts/) |
| Đăng ký | [Villa Savoye](https://www.villa-savoye.fr/decouvrir/les-5-points-de-l-architecture-moderne-selon-le-corbusier) |
| Tạo Admin | [Farnsworth House](https://edithfarnsworthhouse.org/history-farnsworth-house/) |
| Dashboard Admin | [The Glass House](https://theglasshouse.org/explore/the-glass-house/) |
| Dashboard Giảng viên | [Villa Tugendhat](https://whc.unesco.org/en/list/1052/) |
| Dashboard Sinh viên | [Eames House](https://eamesfoundation.org/work/case-study-house-8/) |
| Dashboard Người dùng | [Stahl House](https://stahlhouse.com/) |
| Kiểm tra hồ sơ | [Robie House](https://flwright.org/explore/robie-house) |
| Hồ sơ được chia sẻ | [Rietveld Schröder House](https://www.rietveldschroderhuis.nl/en) |
| Thư viện bản vẽ | [Casa Malaparte](https://www.italia.it/it/campania/cosa-fare/vacanza-da-sogno-capri) |
| Bộ sưu tập mô hình | [Maison Louis Carré](https://www.alvaraalto.fi/en/architecture/maison-louis-carre/) |
| Sổ tay | [Casa Luis Barragán](https://casaluisbarragan.org/) |
| Quản lý tài khoản | [Casa Gilardi](https://casagilardi.mx/) |
| Tài khoản cá nhân | [Red House](https://www.nationaltrust.org.uk/visit/london/red-house) |

Đây là lựa chọn biên tập các nhà ở tiêu biểu, không phải bảng xếp hạng khách quan. Mô hình do app dựng lại theo hình khối đặc trưng, có giản lược/thay đổi tỷ lệ và cảnh quan; không phải bản sao BIM khảo sát. Bản vẽ 2D mẫu là ví dụ độc lập, không phải bản vẽ thật của các nhà này. Không dùng bộ nhà minh họa làm bằng chứng kiểm tra xung đột hay nhãn huấn luyện. Ảnh poster do renderer của app tạo, không lấy ảnh/mesh từ các website tham khảo.

Nguồn nằm ở `frontend/src/models.ts`, `residence-geometry.ts`, `residence-stage.ts`, `HouseModel.tsx`, `ResidencePreview.tsx`. Renderer giới hạn pixel ratio 1.5 và khoảng 30 lần vẽ/giây, dừng khi cảnh ra khỏi viewport/tab bị ẩn; dọn tài nguyên WebGL khi đổi cảnh hoặc đăng xuất. Thư viện dùng 14 poster WebP, tổng dung lượng dưới 0.5 MB; chỉ mở mô hình đang xem. Không thêm dependency hoặc gọi dịch vụ 3D bên ngoài.

Sau khi chuẩn bị database test và tài khoản theo mục 8:

```powershell
npm.cmd run test:residence-geometry
$env:BIM_UI_TEST='1'
npm.cmd run test:residences
```

Để tạo lại poster khi thay hình khối, chạy `node frontend/tests/render-residence-posters.mjs` khi dev server test đang mở. Kiểm thử trình duyệt cần Chromium như mục 6; log/ảnh của mốc này ở `data/artifacts/residences-090/`. Không dùng URI Atlas hoặc dữ liệu công trình thật cho bộ test giao diện.

### 10. Chỉnh sửa hồ sơ cá nhân · 0.10.0

Chọn **Tài khoản của tôi** ở cuối menu. Chỉnh sửa **Tên hiển thị, Email liên hệ, Số điện thoại, Đơn vị, Chức vụ, Giới thiệu** rồi bấm **Lưu hồ sơ**. Tên mới cập nhật trên header/menu và ô người rà soát; nhận xét đã lưu vẫn giữ danh tính lịch sử. **Hủy thay đổi** đưa form về lần lưu gần nhất. Username và vai trò hiển thị chỉ đọc; avatar dùng chữ viết tắt tên.

API GET/POST `/api/auth/profile` dùng phiên tài khoản và chỉ đọc/ghi chính hồ sơ đó. Thông tin liên hệ không nằm trong danh sách tài khoản/thành viên. Nếu hai phiên cùng sửa hoặc mật khẩu/quyền vừa đổi, phiên cũ có thể nhận thông báo xung đột; bản nháp được giữ lại để bạn đối chiếu trước khi chọn **Tải lại hồ sơ**. Thao tác tải lại thay bản nháp bằng dữ liệu đang lưu. Phần **Đổi mật khẩu** vẫn có xác nhận mật khẩu hiện tại và thu hồi các phiên cũ.

Sau khi chuẩn bị server và 4 tài khoản test ở mục 8, chạy `npm.cmd run test:profile-gestures`. Test dùng database local riêng, kiểm tra thao tác chuột/cảm ứng, thời gian 5 giây, lưu hồ sơ, xung đột và phản hồi đến muộn sau đăng xuất. Log/ảnh mốc này: `data/artifacts/profile-0100/`. Không chạy bộ test bằng URI Atlas làm việc.

### 11. Cấp tài khoản và khôi phục mật khẩu · 0.11.0

Sidebar giữ đủ mục chức năng ở cửa sổ laptop. Khi chiều cao thấp, phần trang trí được ẩn; dưới 590 px, các mục menu xếp hai cột. Điện thoại dùng nút mở menu; không cần cuộn riêng trong menu để tới **Tài khoản của tôi**.

**Admin → Tài khoản → Cấp tài khoản:** chọn Giảng viên/Sinh viên, điền họ tên, mã và email rồi chọn **Cấp tài khoản và tải Excel**. Mã là tên đăng nhập; hệ thống nhận cả mã và email, không phân biệt chữ hoa/thường. Mã/email phải duy nhất trong hệ thống. Tài khoản tự đăng ký vẫn là Người dùng; không thể tự chọn quyền giảng viên/sinh viên/Admin qua form đăng ký.

Để cấp hàng loạt, chọn **Import Excel**, tải mẫu giảng viên hoặc sinh viên. Điền một sheet `.xlsx` có các cột sau:

| Họ và tên | Mã giảng viên | email |
|---|---|---|
| Nguyễn Văn A | 2351628 | giangvien@example.org |

Với sinh viên, đổi tên cột mã thành **Mã sinh viên** hoặc dùng mẫu sinh viên. Có thể dùng cả hai cột mã trong một file; mỗi dòng chỉ điền đúng một loại mã. Các cột bổ sung được giữ trong file xuất. Tối đa **200 tài khoản, 20 cột, 2 MiB**, một sheet; chuyển ô công thức thành giá trị trước khi tải. Định dạng cột mã là **Text/Văn bản** trước khi nhập để giữ số 0 đầu và mã dài. Mẫu tải từ app đặt sẵn định dạng Text; mã số nguyên có định dạng `000000` cũng được đọc theo phần số 0 hiển thị. App báo lỗi với mã số quá dài có thể đã bị Excel làm tròn; phải nhập lại mã gốc ở dạng Text.

App hiển thị bảng xem trước và lỗi theo dòng, kiểm tra trùng mã/email trước khi cấp. File kết quả giữ các cột gốc và thêm **Tên đăng nhập, Vai trò, Mật khẩu tạm, Kết quả**. Mỗi tài khoản có mật khẩu tạm riêng, bắt buộc đổi ngay sau đăng nhập bằng mã hoặc email; chỉ sau khi đổi xong mới mở được workspace/API nghiệp vụ. Mật khẩu tạm cũ hết hiệu lực sau khi đổi. Mật khẩu lưu trong tài khoản ở dạng hash; bản tải lại được mã hóa và tự hết hạn sau 24 giờ. Giữ file Excel an toàn và chỉ gửi riêng cho đúng người.

Nếu mất mạng khi cấp, không tạo lô khác ngay. Trong **Các lô cấp gần đây**, chọn **Tiếp tục cấp** cho lô chưa hoàn tất hoặc **Tải lại Excel** cho lô đã cấp. App tiếp tục đúng lô và giữ mật khẩu đã sinh; không tạo tài khoản trùng khi retry. Bản xuất được bảo vệ theo Windows, cần tải lại trên máy đã tạo lô.

**Thiết lập Gmail:** vào **Admin → Tài khoản → Email khôi phục**. Bật Xác minh 2 bước cho Gmail gửi thư, tạo [Mật khẩu ứng dụng Google](https://support.google.com/accounts/answer/185833?hl=en-ST), rồi nhập Gmail và mật khẩu ứng dụng 16 ký tự trong app. Chọn **Lưu và kiểm tra Gmail**. App dùng `smtp.gmail.com:465` với TLS được xác thực, lưu cấu hình DPAPI và không đọc lại password vào giao diện. Không nhập mật khẩu Google thông thường hoặc gửi key vào chat. Xem thêm [cấu hình SMTP chính thức](https://developers.google.com/workspace/gmail/imap/imap-smtp).

Cấu hình gửi thư thuộc backend/Windows user trên máy này, không đi theo bộ cài. Máy khác cần cấu hình gửi thư riêng; phiên bản này chưa có dịch vụ gửi mail tập trung. Kiểm tra kết nối thành công xác nhận đăng nhập SMTP; muốn kiểm chứng email đến hộp thư, tiếp tục luồng xác nhận email dưới đây với địa chỉ của bạn.

**Gắn email cho tài khoản hiện có:** vào **Tài khoản của tôi → Email đăng nhập và khôi phục**, nhập địa chỉ, gửi mã rồi xác nhận. Email liên hệ trong hồ sơ không tự trở thành định danh đăng nhập/khôi phục. Email trong danh sách do Admin cấp được gắn với tài khoản đó; Admin cần kiểm tra đúng người trước khi cấp. Tài khoản tự đăng ký có thể nhập email lúc đăng ký rồi xác nhận ở hồ sơ.

**Quên mật khẩu:** tại màn hình đăng nhập chọn **Quên mật khẩu?**, nhập mã/tên đăng nhập/email đã gắn với tài khoản, nhận mã 6 số, nhập mã và mật khẩu mới. Mã có hiệu lực 10 phút, tối đa 5 lần thử và chỉ dùng một lần; gửi lại sẽ hủy mã trước. Yêu cầu gửi có giới hạn, phản hồi không tiết lộ tài khoản có tồn tại. Đặt lại mật khẩu thu hồi phiên cũ; app yêu cầu đăng nhập lại. Khi chưa nhận được mã, kiểm tra Spam, Gmail gửi thư trên máy backend và địa chỉ tài khoản đã được gắn/xác nhận.

**Kiểm thử riêng cho cấp tài khoản/mail:** không dùng Atlas làm việc. Dùng database localhost riêng và SMTP giả lập để không gửi thư thật:

```powershell
$env:BIM_UI_TEST='1'
$env:BIM_MONGODB_URI='mongodb://127.0.0.1:27017'
$env:BIM_DATABASE='bim_insight_test_accounts011_' + [DateTimeOffset]::Now.ToUnixTimeMilliseconds()
$env:BIM_DATA_DIR='D:\dowload\BIM_Insight\data\artifacts\accounts-0110\ui-data'
node frontend/tests/accounts-server.mjs
```

Terminal khác đặt `BIM_UI_TEST=1`, đường dẫn Chromium như mục 6. Trên database mới, chạy `npm.cmd run test:accounts` để tạo bốn vai trò test, rồi `npm.cmd run test:account-provisioning`. Script kiểm tra form/Excel, đổi mật khẩu bắt buộc, đăng nhập mã/email và OTP; thư thử chỉ ghi vào `test-outbox.jsonl` trong thư mục artifact. Backend tests dùng `.venv\Scripts\python.exe -m pytest backend/tests/test_provisioning.py backend/tests/test_recovery.py -q`. Tắt server và dọn đúng database test đã tạo; không dùng cấu hình/địa chỉ gửi thư thật cho các script này. Log/ảnh mốc: `data/artifacts/accounts-0110/`.

### 12. DWG và dự án lưu lâu dài · 0.12.0

Cài **Windows x64 ODA File Converter** từ [Open Design Alliance](https://www.opendesign.com/guestfiles/oda_file_converter), giữ thư mục cài mặc định trong `%LOCALAPPDATA%\Programs\ODA` hoặc `C:\Program Files\ODA`. App tự nhận diện bản có chữ ký hợp lệ; không cần nhập đường dẫn hay mật khẩu. Bộ chuyển là phần mềm cài riêng, không được đóng gói lại trong bộ cài BIM Insight; sử dụng theo điều khoản ODA. Máy hiện tại đã cài ODA 27.10.0.

Vào **Kiểm tra hồ sơ → chọn hoặc tạo dự án → mở revision → chọn DWG/IFC/PDF → Bắt đầu kiểm tra**. Khung **DWG → DXF** báo trạng thái bộ chuyển. Chọn kết quả DWG để xem thống kê, mở layer ở khu vực phối hợp và **Tải DXF đã chuyển**. DWG giữ nguyên; DXF dẫn xuất lưu tại `assets/<report-id>/converted.dxf`. Đồng bộ R2 gồm cả DWG gốc, DXF dẫn xuất, preview, IFC/GLB, PDF và báo cáo. Bấm thẻ dự án ở Tổng quan sẽ mở đúng dự án đó; lần mở tiếp theo khôi phục lựa chọn đã lưu.

DWG chỉ có header từ phiên bản cũ cần nhập vào **revision mới** để xử lý nội dung; báo cáo cũ được giữ lại. Chọn tối đa 200 hồ sơ để mở cùng lúc; dự án vẫn lưu các hồ sơ đã nhập trước đó. CAD 2D dùng để định vị và đối chiếu, cần IFC có cấu kiện để kiểm tra va chạm 3D. Thiếu tuyến ống/ống gió hoặc có tham chiếu GUID chưa xác minh vẫn được báo thiếu phạm vi, không tự tạo mô hình thay thế. Xref, đối tượng CAD chưa hỗ trợ và phần PDF chưa đọc được tiếp tục được ghi rõ.

Kiểm thử tự động vẫn dùng fixture trong database **localhost riêng**; các script UI nhập fixture qua ô chọn tệp của dự án. `npm.cmd run test:project-open` kiểm tra mở đúng thẻ dự án và giữ lựa chọn khi chuyển qua hồ sơ được chia sẻ. Kiểm thử DWG thật có lệnh `npm.cmd run test:dwg-real`, yêu cầu chủ động đặt `BIM_REAL_TEST=1`, tài khoản qua `BIM_REAL_USERNAME/BIM_REAL_PASSWORD` và manifest trong `data/artifacts/dwg-0120/real-inputs.json`; lệnh này ghi hồ sơ Nha02 vào **Atlas/R2 thật**, không dùng cho test hồi quy thông thường. Không ghi mật khẩu/key vào script hoặc báo cáo.

**Sau khi dọn dữ liệu ngày 06/11/2026:** các dự án, tệp đã nhập, lượt kiểm tra, nhận xét/đề xuất test và bản sao R2 đã được xóa theo yêu cầu. Giữ nguyên tài khoản, cấu hình kết nối, hồ sơ nguồn trong `data/inputs/Nha02`, trọng số Qwen và adapter. App bắt đầu với danh sách dự án trống; đăng nhập bằng tài khoản cũ, tạo dự án mới rồi nhập lại hồ sơ cần dùng. Các thư mục cache/artifact/runtime chỉ được tạo lại khi có tác vụ tương ứng. Có bản sao tài khoản mã hóa trong `data/inspections/accounts-backup-20261106.dpapi`; không đưa file này lên Git hoặc gửi cho người khác.

Trước khi dọn, backend đạt 216 tests, một test desktop-server tùy chọn không bật; binary Windows 0.12.0 đã qua WebView2 với DWG thật và mở lại dự án sau khởi động lại. Hai DWG Nha02 đã khớp 10/10 trục với IFC; 23/23 tệp từng được xác minh trên R2. Artifact và manifest của các lượt test này đã dọn; cần chuẩn bị lại trước khi chạy các lệnh test thật. Bộ cài NSIS ở mục 5 vẫn giữ nguyên; chưa kiểm thử wizard cài trên máy khác. Hướng dẫn cài ODA áp dụng riêng trên mỗi máy; app chỉ tích hợp việc gọi bộ chuyển đã cài.

**Mở app để sử dụng với hồ sơ thật:** dừng phiên cũ bằng Ctrl+C, dùng terminal PowerShell mới, giữ cấu hình MongoDB làm việc đã lưu:

```powershell
Set-Location 'D:\dowload\BIM_Insight'
npm.cmd start
```

Lệnh `npm start` build giao diện rồi chạy cùng backend local tại `http://127.0.0.1:1420`, giảm bộ nhớ dành cho môi trường phát triển khi đọc IFC. Mỗi lần chạy sẽ build lại để dùng mã mới. Dùng `npm run dev` khi sửa source và cần cập nhật giao diện trực tiếp. Chỉ chạy một phiên trên cổng 1420; đóng ứng dụng nặng để dành khoảng 4–5 GiB RAM trống khi thử bộ 35.

Giữ terminal mở khi sử dụng app. Dòng `Terminate batch job (Y/N)?` cho biết terminal đang nhận yêu cầu dừng; xác nhận dừng có thể đóng bộ xử lý và gây `ECONNRESET` ở proxy. Để dừng một lượt kiểm tra, dùng **Hủy kiểm tra va chạm** trong app. Sau khi sửa source, khởi động lại bằng lệnh trên để nạp cả backend và giao diện mới.

Đăng nhập bằng tài khoản hiện có và tạo/chọn dự án để nhập hồ sơ. Bản Windows 0.12.0 ở mục 5 chưa chứa các thay đổi đọc IFC mới này; cần build lại bộ cài để áp dụng trong app cài đặt. Tài khoản và cấu hình kết nối tiếp tục được giữ.

Sau bản sửa va chạm 08/11, khởi động lại **cả phiên terminal chạy app** bằng lệnh `npm.cmd start` ở trên để nạp backend mới; chỉ tải lại trình duyệt chưa nạp lại backend. Cache của 4 IFC Timber đã sẵn sàng trên máy này, có thể chọn lại cùng hồ sơ và chạy kiểm tra ngay. IFC mới hoặc cấu hình hình học thay đổi sẽ cần dựng cache tương ứng ở lượt đầu.

**Tạo lại bản xem Office sau bản sửa 08/11:** dừng phiên app cũ bằng Ctrl+C (trả lời Y nếu terminal hỏi), chạy `npm.cmd start`. Trong **Dự án và lịch sử**, điền revision mới như `R02`, bấm **Mở revision**, nhập lại bộ IFC Office rồi **Bắt đầu kiểm tra**. Cùng nguồn/cùng revision trả báo cáo đã lưu, nên chỉ tải lại trang hoặc nhập lại vào `R01` sẽ giữ bản xem cũ. Báo cáo/revision và checksum R2 cũ được giữ nguyên; bản xem mới hiện dung lượng đã tối ưu trong chi tiết IFC. Dành khoảng 5 GiB RAM trống cho lượt nhập HVAC Office đã đo; app tiếp tục dừng an toàn nếu ngân sách thực tế không đủ.

**Sau lần dọn 08/11:** đăng nhập bằng tài khoản cũ, tạo dự án mới và nhập bộ nguồn ở `R01`; các dự án test trước đó đã được xóa theo yêu cầu. Tệp gốc, Qwen/adapter và thông tin kết nối vẫn còn. Lượt nhập và va chạm đầu tiên sẽ dựng lại cache.

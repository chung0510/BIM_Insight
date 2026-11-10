# Chạy BIM Insight trên Render Free

Bản này dành cho thử nghiệm, chạy độc lập với máy cá nhân. Một Docker Web Service phục vụ cả React và API Python trên cùng URL HTTPS. Dùng MongoDB Atlas riêng cho tài khoản và metadata; không đưa dữ liệu làm việc hay secrets trên máy vào image.

## Tạo dịch vụ từ màn hình Blueprints

1. Đưa các thay đổi này lên một nhánh của repository `chung0510/BIM_Insight`.
2. Trong Render chọn **Blueprints → New Blueprint Instance** như màn hình hiện tại.
3. Kết nối repository **BIM_Insight**, chọn nhánh có thay đổi và đường dẫn **render.yaml**. Blueprint `Bim_Learn` đang có là ứng dụng khác, không sửa nó.
4. Kiểm tra dịch vụ `bim-insight-demo` có **plan: free**, runtime **Docker**, region **Singapore**. Không thêm disk hay database Postgres.
5. Nhập ba secrets khi Render hỏi:

| Biến | Giá trị |
| --- | --- |
| `BIM_MONGODB_URI` | MongoDB Atlas URI với tài khoản có quyền đọc/ghi database demo. Mã hóa URL các ký tự đặc biệt trong mật khẩu. |
| `BIM_ADMIN_USERNAME` | Tên quản trị: 3–48 ký tự chữ thường/số/dấu chấm/gạch ngang/gạch dưới, bắt đầu bằng chữ hoặc số. |
| `BIM_ADMIN_PASSWORD` | Mật khẩu riêng cho bản thử nghiệm, từ 12 đến 128 ký tự. |

Không gửi URI/mật khẩu vào chat và không commit chúng. `BIM_SETTINGS_KEY` được Render sinh ngẫu nhiên; giữ nguyên giá trị này qua các lần deploy, không chia sẻ nó.

6. Trong trang dịch vụ Render, mở **Connect → Outbound**. Thêm các dải IP đó vào **Atlas → Network Access**. Tài khoản database cần quyền với `bim_insight_render_demo`; dùng tài khoản riêng có quyền tối thiểu thay vì tài khoản quản trị Atlas.
7. Deploy và chờ trạng thái **Live**. Nếu lần đầu chưa kết nối Atlas được, hoàn tất allowlist rồi **Manual Deploy** lại.
8. Mở URL `https://…onrender.com`, đăng nhập bằng thông tin quản trị ở trên. Tài khoản này chỉ được tạo khi database chưa có quản trị; thay secret không đặt lại mật khẩu của tài khoản đã tồn tại. Các tài khoản desktop không tự chuyển sang database demo.

Render tự cung cấp `PORT` và `RENDER_EXTERNAL_URL`; không đặt chúng thành localhost. Dùng URL `onrender.com` mặc định cho bản demo này, cùng một origin cho UI/API.

## Phạm vi thử nghiệm

- Đăng nhập, đăng ký, phân quyền, dự án, xem 3D, IFC/PDF/DXF và kiểm tra va chạm dùng backend hiện có.
- Upload tối đa **20 MiB/tệp**. Worker có ngân sách RSS **256 MiB** để chừa bộ nhớ cho API trong gói 512 MB; chỉ thử tệp nhỏ. Có thể bị dừng an toàn vì vượt ngân sách; chưa có benchmark IFC trên Render Free.
- Render Free ngủ khi không có lưu lượng khoảng 15 phút và mất dữ liệu filesystem khi restart/redeploy. Tệp IFC, preview, cache, báo cáo và cấu hình lưu trong `/tmp/bim-insight` có thể mất. MongoDB vẫn còn tài khoản/metadata, nên hồ sơ cũ có thể còn trong danh sách nhưng không mở được tệp. Không dùng bản này lưu hồ sơ chính thức.
- Workspace có 750 giờ Free mỗi tháng, dùng chung giữa các web service; nếu `Bim_Learn` cũng dùng Free thì cùng tính vào hạn mức. Hết giờ, Render tạm dừng các dịch vụ Free đến tháng sau. Bandwidth/build có hạn mức riêng; kiểm tra **Billing → Monthly Included Usage** và giới hạn chi tiêu nếu tài khoản đã gắn phương thức thanh toán, vì có thể phát sinh phí vượt hạn mức. Blueprint này không tạo gói trả phí.
- **DWG:** image không có ODA Windows; app sẽ báo chưa có bộ chuyển. Có thể chuyển DWG sang DXF trước khi upload.
- **AI:** image không chứa Qwen/model/adapter hoặc môi trường GPU trên máy cá nhân. Chức năng AI báo chưa cấu hình; không tự chuyển sang dịch vụ AI trả phí.
- **Email:** Render Free chặn SMTP 465/587, nên Gmail xác nhận email/khôi phục mật khẩu chưa hoạt động. Đăng nhập bằng username vẫn dùng được; lưu mật khẩu quản trị của bản demo.
- Cấu hình Windows DPAPI cũ không được sao chép. Trên web, các cấu hình mới/lô cấp tài khoản được mã hóa bằng secret riêng trên Render. Đổi/mất `BIM_SETTINGS_KEY` làm mất khả năng giải mã dữ liệu đã mã hóa bằng key cũ.

## Kiểm tra sau deploy

1. `/api/health` trả `status: ok`, `deployment: web_demo` và giới hạn upload 20 MiB. Health không xác nhận MongoDB/AI đang sẵn sàng.
2. Đăng nhập quản trị; trang làm việc hiện cảnh báo bản thử nghiệm miễn phí.
3. Tạo dự án mới, upload một PDF/DXF/IFC mẫu nhỏ; mở preview và tải báo cáo.
4. Kiểm tra đăng xuất và tài khoản thứ hai không xem được dự án chưa chia sẻ.
5. Chỉ coi kiểm tra va chạm/AI là đã xác minh khi đã chạy thật và có kết quả; build thành công chưa chứng minh đủ RAM cho mô hình thực tế.

## Nguồn chính thức

- [Render Free và các giới hạn](https://render.com/docs/free)
- [Blueprint YAML](https://render.com/docs/blueprint-spec)
- [IP đi ra để cấu hình Atlas](https://render.com/docs/outbound-ip-addresses)
- [Ổ đĩa bền vững cho giai đoạn sử dụng chính thức](https://render.com/docs/disks)

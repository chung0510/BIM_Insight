# Tách giao diện BIM Insight thành Render Static Site

Giao diện được phục vụ qua CDN ngay cả khi API Free đang ngủ. Trình duyệt gọi thẳng API HTTPS; màn hình kết nối tự thử lại các lỗi khởi động/mạng trong khoảng hai phút. Không có token nội bộ, URI MongoDB hay mật khẩu trong bundle frontend.

## Backend hiện có

Giữ Web Service `https://bim-insight-demon.onrender.com`, database, toàn bộ secrets và nhánh `deploy/render-demo`. Không tạo lại backend hoặc quản trị viên.

Sau khi push source mới, chờ backend deploy thành công. URL cũ vẫn mở được giao diện như trước. Kiểm tra `/api/health` trước khi nối Static Site.

## Tạo Static Site miễn phí

Trong Render chọn **New → Static Site**, kết nối repository `chung0510/BIM_Insight`:

| Mục | Giá trị |
| --- | --- |
| Name | `bim-insight-web` |
| Branch | `deploy/render-demo` |
| Root Directory | để trống |
| Build Command | `npm ci && npm run build` |
| Publish Directory | `frontend/dist` |
| Auto-Deploy | `On Commit` |

Thêm các environment variables của **Static Site**:

| Key | Value |
| --- | --- |
| `NODE_VERSION` | `24` |
| `SKIP_INSTALL_DEPS` | `true` |
| `VITE_API_BASE_URL` | `https://bim-insight-demon.onrender.com` |

Không thêm MongoDB URI, mật khẩu hoặc `BIM_SETTINGS_KEY` vào Static Site. Các biến `VITE_` là thông tin công khai được đưa vào JavaScript.

Bấm **Deploy Static Site**. Có thể dùng Blueprint `render-static.yaml` thay cho form thủ công; Blueprint này chỉ tạo frontend. Không dùng `render.yaml` để tạo lại Web Service đang hoạt động.

## Cho phép đúng origin của frontend

1. Copy URL HTTPS thực tế của Static Site, ví dụ `https://bim-insight-web.onrender.com`. Render có thể thêm hậu tố nếu tên đã được dùng.
2. Mở **Web Service backend → Environment → Add Environment Variable**.
3. Đặt `BIM_FRONTEND_ORIGIN` bằng URL vừa copy, **không có dấu `/` cuối, đường dẫn, wildcard hoặc thông tin đăng nhập**.
4. Chọn **Save and deploy**. Giữ nguyên `BIM_WEB_ORIGIN`/`RENDER_EXTERNAL_URL` của backend; `BIM_FRONTEND_ORIGIN` là origin bổ sung cho CORS, không đổi Host của health check.
5. Mở link Static Site, chờ màn hình tự kết nối rồi đăng nhập bằng tài khoản web hiện có.

URL API cũ được giữ để tương thích. Muốn tránh màn hình Render Loading ở lần truy cập mới, chia sẻ/bookmark **URL Static Site**.

## Kiểm tra

- Mở Static Site khi API đang ngủ: giao diện BIM Insight xuất hiện với lời giải thích đang kết nối; tự chuyển sang đăng nhập khi API sẵn sàng.
- Thử đăng nhập, tạo dự án mẫu, upload PDF nhỏ và tải báo cáo.
- Các origin khác vẫn bị từ chối; tài khoản vẫn cần phiên đăng nhập và quyền dự án.
- Nếu nhận lỗi CORS/kết nối mãi: đối chiếu chính xác `BIM_FRONTEND_ORIGIN` với URL đang mở, không sửa thành `*`.
- Nếu đổi `VITE_API_BASE_URL`, phải rebuild Static Site; nếu đổi `BIM_FRONTEND_ORIGIN`, redeploy backend.

Static Site không giữ backend thức liên tục, không tăng RAM và không làm tệp lưu tạm bền vững. Giới hạn demo 20 MiB/DWG/Qwen/SMTP vẫn như trước.

## Git

Phần triển khai này được làm trong worktree riêng để giữ các thay đổi lớp học/bài thực hành chưa commit ở workspace chính. Push một commit đã kiểm tra lên nhánh deploy:

```powershell
git -C D:\dowload\BIM_Insight\.local\render-static-split push origin HEAD:deploy/render-demo
```

Với các lần sửa tiếp theo trên nhánh `deploy/render-demo`, kiểm tra file thay đổi, chỉ stage đúng file cần triển khai, commit rồi chạy `git push origin deploy/render-demo`. Hai dịch vụ sẽ cập nhật khi đều bật Auto-Deploy trên nhánh này.

Nguồn: [Static Sites](https://render.com/docs/static-sites), [Render environment variables](https://render.com/docs/configure-environment-variables), [Vite public environment variables](https://vite.dev/guide/env-and-mode).

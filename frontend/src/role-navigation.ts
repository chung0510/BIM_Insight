import {ClipboardCheck, FileCheck2, FolderKanban, GraduationCap, History, LayoutDashboard, ListChecks, ScanLine, Settings2, ShieldCheck, UserPlus, UsersRound} from 'lucide-react';
import type {AccountRole} from './account-api';
import type {ModelVariant} from './models';

export type RoleView = 'overview'|'accounts'|'provision'|'services'|'audit'|'assignments'|'submissions'|'grades'|'students'|'classes'|'notifications';
export const roleNavigation = {
 admin:[{id:'overview',label:'Tổng quan hệ thống',icon:LayoutDashboard},{id:'accounts',label:'Tài khoản và phân quyền',icon:ShieldCheck},{id:'provision',label:'Cấp tài khoản',icon:UserPlus},{id:'services',label:'Cấu hình dịch vụ',icon:Settings2},{id:'audit',label:'Nhật ký quản trị',icon:History}],
 teacher:[{id:'overview',label:'Tổng quan giảng dạy',icon:LayoutDashboard},{id:'classes',label:'Lớp giảng dạy',icon:UsersRound},{id:'submissions',label:'Bài nộp cần chấm',icon:ClipboardCheck},{id:'grades',label:'Bảng điểm',icon:ListChecks}],
 student:[{id:'overview',label:'Tổng quan thực hành',icon:LayoutDashboard},{id:'classes',label:'Lớp của tôi',icon:GraduationCap},{id:'inspection',label:'Tự kiểm tra BIM',icon:ScanLine},{id:'submissions',label:'Bài nộp của tôi',icon:FolderKanban},{id:'grades',label:'Điểm và phản hồi',icon:FileCheck2}],
} as const;
export const roleIntroductions:Record<AccountRole,string> = {
 admin:'Quản lý tài khoản, cấp quyền và theo dõi trạng thái hệ thống.',
 teacher:'Giao bài có tiêu chí, xem minh chứng và trả phản hồi cho sinh viên.',
 student:'Đọc yêu cầu, tự kiểm tra mô hình và theo dõi từng lần nộp bài.',
 user:'',
};
export const roleScreenModels:Record<string,ModelVariant> = {provision:'carre',services:'barragan',audit:'red-house',assignments:'savoye',submissions:'schroder',grades:'malaparte',students:'robie',classes:'robie',notifications:'eames'};
export const rolePageDescriptions:Record<string,string> = {
 provision:'Cấp tài khoản theo mã hoặc Excel, kèm mật khẩu dùng cho lần đăng nhập đầu.',
 services:'Kiểm tra dịch vụ và thiết lập email trên môi trường đang sử dụng.',
 audit:'Theo dõi thao tác quản trị và nghiệp vụ bằng dữ liệu đã ghi nhận.',
 assignments:'Yêu cầu bài thực hành, tiêu chí đánh giá và danh sách được giao.',
 submissions:'Mở từng lần nộp để đối chiếu đúng hồ sơ và minh chứng đã lưu.',
 grades:'Điểm và phản hồi chính thức do giảng viên phụ trách công bố.',
 students:'Danh sách sinh viên theo các nhóm thực hành bạn phụ trách.',
 classes:'Lớp thực hành theo học kỳ, thành viên và bài được giao trong từng lớp.',
 notifications:'Hoạt động và hạn nộp liên quan tới tài khoản đang đăng nhập.',
};

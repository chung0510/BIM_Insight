import { processorFetch, setAccountToken, type Connection } from "./inspection-api";

export type AccountRole = "admin" | "teacher" | "student" | "user";
export type Account = { id: string; realm_id: string; username: string; display_name: string; role: AccountRole; disabled: boolean; revision: number; protected: boolean; created_at: string; must_change_password:boolean; identity_code:string; login_email:string; pending_email:string };
export type AccountSession = { session_token: string; user: Account; expires_in: number };
export type PersonalProfile = {user:Account;email:string;phone:string;organization:string;job_title:string;bio:string};
export const roleLabels: Record<AccountRole, string> = { admin: "Quản trị viên", teacher: "Giảng viên", student: "Sinh viên", user: "Người dùng" };
export const roleDescriptions: Record<AccountRole, string> = {
  admin: "Quản lý tài khoản, phân quyền và theo dõi hệ thống. Các dự án cá nhân vẫn có quyền truy cập riêng.",
  teacher: "Quản lý lớp thực hành, giao bài có tiêu chí, đối chiếu minh chứng và công bố điểm, phản hồi.",
  student: "Theo dõi lớp tham gia, đọc yêu cầu bài, tự kiểm tra mô hình, nộp minh chứng và xem phản hồi đã công bố.",
  user: "Phân tích hồ sơ BIM, kiểm tra xung đột và quản lý các dự án cá nhân.",
};
let currentAccount: Account | null = null;
export function getAccount() { return currentAccount; }
export function rememberSession(session: AccountSession | null) {
  currentAccount = session?.user ?? null;
  setAccountToken(session?.session_token ?? "");
}
export function refreshAccount(account: Account) { currentAccount = account; }
export function accountStorageKey(name: string) { return `bim-insight.${name}.${currentAccount?.realm_id ?? "none"}.${currentAccount?.id ?? "signed-out"}`; }
export async function accountRequest<T>(connection: Connection, url: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await processorFetch(connection, url, { ...(body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }), signal });
  return response.json();
}

export async function downloadAccountFile(connection:Connection,url:string,filename:string,signal?:AbortSignal) {
  const response=await processorFetch(connection,url,{signal});const blob=await response.blob();
  if(signal?.aborted)return;
  const objectUrl=URL.createObjectURL(blob),link=document.createElement("a");link.href=objectUrl;link.download=filename;link.click();setTimeout(()=>URL.revokeObjectURL(objectUrl),1000);
}

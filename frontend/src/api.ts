import axios from "axios";
export const api = axios.create({ baseURL: "/api", timeout: 30000 });
api.interceptors.request.use((config) => {
  if (config.url?.startsWith("/api/")) config.url = config.url.slice(4);
  const token = sessionStorage.getItem("logistics-token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (
      error.response?.status === 401 &&
      !error.config?.url?.startsWith("/auth/")
    )
      window.dispatchEvent(new Event("auth-expired"));
    return Promise.reject(error);
  },
);
export function errorText(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail))
      return detail
        .map((item) => `${item.loc?.slice(1).join(".") ?? ""}: ${item.msg}`)
        .join("；");
    if (error.code === "ERR_NETWORK") return "无法连接服务，请确认后端已启动。";
    if (error.code === "ECONNABORTED") return "请求超时，请稍后重试。";
    return `请求失败${error.response ? `（${error.response.status}）` : ""}：${error.message}`;
  }
  return error instanceof Error ? error.message : String(error);
}
export async function download(url: string, filename: string) {
  const { data } = await api.get<Blob>(url, {
    responseType: "blob",
    timeout: 0,
  });
  const objectUrl = URL.createObjectURL(data);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

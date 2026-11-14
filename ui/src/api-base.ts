/** Single source of truth for the local backend API URL. */
const configured = import.meta.env.VITE_API_BASE_URL?.trim();
export const API_BASE_URL = (configured || "http://127.0.0.1:8000/api/v1").replace(/\/$/, "");
export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

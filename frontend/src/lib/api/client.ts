import axios from "axios";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const api = axios.create({
  baseURL: `${BASE_URL}/api/v1`,
  headers: { "Content-Type": "application/json" },
  timeout: 30000,
});

// Request interceptor: inject JWT
api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("access_token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }
  return config;
});

// Response interceptor: handle auth errors
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if ((error.response?.status === 401 || error.response?.status === 403) && typeof window !== "undefined") {
      const token = localStorage.getItem("access_token");
      if (!token || error.response?.status === 401) {
        localStorage.removeItem("access_token");
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

export function setAuthToken(token: string) {
  if (typeof window !== "undefined") {
    localStorage.setItem("access_token", token);
  }
}

export function clearAuthToken() {
  if (typeof window !== "undefined") {
    localStorage.removeItem("access_token");
  }
}

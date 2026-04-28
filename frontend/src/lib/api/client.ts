import axios, { type AxiosInstance } from "axios";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8010";

function createInstance(timeout: number): AxiosInstance {
  const instance = axios.create({
    baseURL: `${BASE_URL}/api/v1`,
    headers: { "Content-Type": "application/json" },
    timeout,
  });

  // Inject JWT on every request + fix FormData Content-Type
  instance.interceptors.request.use((config) => {
    if (typeof window !== "undefined") {
      const token = localStorage.getItem("access_token");
      if (token) config.headers.Authorization = `Bearer ${token}`;
    }
    // When sending FormData, delete the default Content-Type so the browser can
    // set it automatically with the correct multipart/form-data boundary.
    // Without this, the axios instance default "application/json" overrides it,
    // causing FastAPI to return 422 (can't parse file/form fields).
    if (config.data instanceof FormData) {
      delete config.headers["Content-Type"];
    }
    return config;
  });

  // Handle 401/403 globally
  instance.interceptors.response.use(
    (response) => response,
    (error) => {
      if (
        (error.response?.status === 401 || error.response?.status === 403) &&
        typeof window !== "undefined"
      ) {
        const token = localStorage.getItem("access_token");
        if (!token || error.response?.status === 401) {
          localStorage.removeItem("access_token");
          window.location.href = "/login";
        }
      }
      return Promise.reject(error);
    }
  );

  return instance;
}

// Default instance — 30s timeout
export const api = createInstance(30_000);

// Slow instance — 180s timeout for AI analysis multi-agent pipeline
export const apiSlow = createInstance(180_000);

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

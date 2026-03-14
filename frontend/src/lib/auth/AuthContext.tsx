"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  type ReactNode,
} from "react";
import { useRouter, usePathname } from "next/navigation";
import { api, setAuthToken, clearAuthToken } from "@/lib/api/client";

interface User {
  id: string;
  email: string;
  full_name: string | null;
  preferred_currency: string;
}

interface AuthContextType {
  user: User | null;
  token: string | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, fullName?: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  // On mount, check for existing token
  useEffect(() => {
    const stored = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
    if (stored) {
      setToken(stored);
      // Validate by fetching profile
      api
        .get("/auth/me")
        .then((r) => {
          setUser(r.data);
          setIsLoading(false);
        })
        .catch(() => {
          // Token expired or invalid
          localStorage.removeItem("access_token");
          setToken(null);
          setIsLoading(false);
        });
    } else {
      setIsLoading(false);
    }
  }, []);

  // Redirect unauthenticated users away from dashboard
  useEffect(() => {
    if (!isLoading && !token && pathname?.startsWith("/dashboard")) {
      router.replace("/login");
    }
  }, [isLoading, token, pathname, router]);

  const login = useCallback(async (email: string, password: string) => {
    const resp = await api.post("/auth/login", { email, password });
    const { access_token, user_id, email: userEmail } = resp.data;
    setAuthToken(access_token);
    setToken(access_token);
    // Fetch full profile
    const profile = await api.get("/auth/me");
    setUser(profile.data);
    router.push("/dashboard");
  }, [router]);

  const register = useCallback(async (email: string, password: string, fullName?: string) => {
    const resp = await api.post("/auth/register", {
      email,
      password,
      full_name: fullName || undefined,
      preferred_currency: "AUD",
    });
    const { access_token } = resp.data;
    setAuthToken(access_token);
    setToken(access_token);
    const profile = await api.get("/auth/me");
    setUser(profile.data);
    router.push("/dashboard");
  }, [router]);

  const logout = useCallback(() => {
    clearAuthToken();
    setToken(null);
    setUser(null);
    router.push("/login");
  }, [router]);

  return (
    <AuthContext.Provider value={{ user, token, isLoading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

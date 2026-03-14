"use client";

import { Sidebar } from "@/components/layout/Sidebar";
import { TopBar } from "@/components/layout/TopBar";
import { useAuth } from "@/lib/auth/AuthContext";
import { Loader2 } from "lucide-react";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { token, isLoading } = useAuth();

  // Show loading spinner while checking auth
  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-950">
        <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
      </div>
    );
  }

  // AuthContext handles redirect to /login if no token
  if (!token) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-950">
        <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden bg-gray-950">
      <Sidebar />
      <div className="flex flex-col flex-1 overflow-hidden">
        <TopBar />
        <main className="flex-1 overflow-y-auto p-6">
          {children}
        </main>
      </div>
    </div>
  );
}

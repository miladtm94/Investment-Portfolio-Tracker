"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth/AuthContext";
import { TrendingUp, Mail, Lock, User, Loader2 } from "lucide-react";

export default function LoginPage() {
  const { login, register } = useAuth();
  const [isRegister, setIsRegister] = useState(false);
  const [email, setEmail] = useState("demo@investiq.io");
  const [password, setPassword] = useState("demo1234");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      if (isRegister) {
        await register(email, password, fullName);
      } else {
        await login(email, password);
      }
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-950 px-4">
      <div className="w-full max-w-md space-y-8">
        {/* Logo */}
        <div className="text-center">
          <div className="inline-flex items-center gap-3 mb-6">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center">
              <TrendingUp className="w-6 h-6 text-white" />
            </div>
            <div className="text-left">
              <h1 className="text-2xl font-bold text-gray-100">InvestIQ</h1>
              <p className="text-xs text-gray-500">Intelligence Platform</p>
            </div>
          </div>
          <h2 className="text-xl font-semibold text-gray-200">
            {isRegister ? "Create your account" : "Welcome back"}
          </h2>
          <p className="text-sm text-gray-500 mt-1">
            {isRegister
              ? "Start tracking your portfolio in minutes"
              : "Sign in to your investment dashboard"}
          </p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="card-glass p-8 space-y-5">
          {isRegister && (
            <div>
              <label className="text-sm text-gray-400 mb-1.5 block">Full Name</label>
              <div className="relative">
                <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                <input
                  type="text"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="John Doe"
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg pl-10 pr-4 py-2.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500 transition-colors"
                />
              </div>
            </div>
          )}

          <div>
            <label className="text-sm text-gray-400 mb-1.5 block">Email</label>
            <div className="relative">
              <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                required
                className="w-full bg-gray-800 border border-gray-700 rounded-lg pl-10 pr-4 py-2.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500 transition-colors"
              />
            </div>
          </div>

          <div>
            <label className="text-sm text-gray-400 mb-1.5 block">Password</label>
            <div className="relative">
              <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Min 6 characters"
                required
                minLength={6}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg pl-10 pr-4 py-2.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500 transition-colors"
              />
            </div>
          </div>

          {error && (
            <div className="text-sm text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-4 py-2.5">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full btn-primary py-2.5 flex items-center justify-center gap-2 disabled:opacity-50"
          >
            {loading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : isRegister ? (
              "Create Account"
            ) : (
              "Sign In"
            )}
          </button>

          <div className="text-center text-sm">
            <span className="text-gray-500">
              {isRegister ? "Already have an account?" : "Don't have an account?"}
            </span>{" "}
            <button
              type="button"
              onClick={() => { setIsRegister(!isRegister); setError(""); }}
              className="text-blue-400 hover:text-blue-300 font-medium"
            >
              {isRegister ? "Sign in" : "Create one"}
            </button>
          </div>
        </form>

        <p className="text-center text-xs text-gray-600">
          AUD-native portfolio tracking with ATO tax reporting
        </p>
      </div>
    </div>
  );
}

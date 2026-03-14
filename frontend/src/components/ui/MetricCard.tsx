"use client";

import clsx from "clsx";
import { ReactNode } from "react";

interface MetricCardProps {
  title: string;
  value: string | null;
  subtitle?: string;
  icon?: ReactNode;
  positive?: boolean;
  loading?: boolean;
  compact?: boolean;
  accent?: "blue" | "green" | "red" | "yellow" | "none";
}

export function MetricCard({
  title,
  value,
  subtitle,
  icon,
  positive,
  loading = false,
  compact = false,
  accent = "none",
}: MetricCardProps) {
  const accentColors: Record<string, string> = {
    blue: "border-blue-500/30 bg-blue-500/5",
    green: "border-green-500/30 bg-green-500/5",
    red: "border-red-500/30 bg-red-500/5",
    yellow: "border-yellow-500/30 bg-yellow-500/5",
    none: "",
  };

  return (
    <div className={clsx("card-glass p-4 hover:border-gray-700 transition-colors", accentColors[accent])}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-gray-500 font-medium uppercase tracking-wide">{title}</span>
        {icon && (
          <div className={clsx(
            "w-7 h-7 rounded-lg flex items-center justify-center",
            positive === true ? "bg-green-400/10 text-green-400" :
            positive === false ? "bg-red-400/10 text-red-400" :
            "bg-gray-800 text-gray-400"
          )}>
            {icon}
          </div>
        )}
      </div>

      {loading ? (
        <div className="space-y-2">
          <div className="h-6 w-32 bg-gray-800 rounded animate-pulse" />
          <div className="h-3 w-20 bg-gray-800 rounded animate-pulse" />
        </div>
      ) : (
        <>
          <div className={clsx(
            "font-bold font-mono",
            compact ? "text-lg" : "text-2xl",
            positive === true ? "text-green-400" :
            positive === false ? "text-red-400" :
            "text-gray-100"
          )}>
            {value ?? "—"}
          </div>
          {subtitle && (
            <div className="text-xs text-gray-500 mt-1 truncate">{subtitle}</div>
          )}
        </>
      )}
    </div>
  );
}

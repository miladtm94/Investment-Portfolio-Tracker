"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";
import {
  LayoutDashboard, Briefcase, ArrowLeftRight, BarChart2,
  Bot, FileText, RefreshCw, Settings, TrendingUp, Zap, Upload, LogOut,
  Globe, Star, History,
} from "lucide-react";
import { useAuth } from "@/lib/auth/AuthContext";

const INVEST_NAV = [
  { href: "/dashboard",              label: "Dashboard",   icon: LayoutDashboard, badge: null },
  { href: "/dashboard/transactions", label: "Investments", icon: ArrowLeftRight,  badge: null },
  { href: "/dashboard/analytics",    label: "Analytics",   icon: BarChart2,       badge: null },
  { href: "/dashboard/advisor",      label: "AI Advisor",  icon: Bot,             badge: "AI" },
  { href: "/dashboard/tax",          label: "Tax Center",  icon: FileText,        badge: null },
];

const TRADING_NAV = [
  { href: "/dashboard/markets",          label: "Markets",        icon: Globe,    badge: null },
  { href: "/dashboard/watchlist",        label: "Watchlist",      icon: Star,     badge: null },
  { href: "/dashboard/analysis/history", label: "AI History",     icon: History,  badge: null },
];

export function Sidebar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();

  return (
    <aside className="w-60 flex-shrink-0 flex flex-col bg-gray-900 border-r border-gray-800">
      {/* Logo */}
      <div className="h-16 flex items-center px-4 border-b border-gray-800">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center">
            <TrendingUp className="w-4 h-4 text-white" />
          </div>
          <div>
            <span className="font-bold text-gray-100 text-sm">InvestIQ</span>
            <div className="text-xs text-gray-500">Intelligence Platform</div>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-3 space-y-0.5 overflow-y-auto">
        <div className="text-xs font-medium text-gray-600 uppercase tracking-wider px-3 py-2">
          Portfolio
        </div>
        {INVEST_NAV.map(({ href, label, icon: Icon, badge }) => {
          const isActive = pathname === href || (href !== "/dashboard" && pathname.startsWith(href));
          return (
            <Link key={href} href={href} className={clsx("sidebar-item", isActive && "sidebar-item-active")}>
              <Icon className="w-4 h-4 flex-shrink-0" />
              <span className="text-sm">{label}</span>
              {badge && (
                <span className="ml-auto text-xs bg-blue-600 text-white px-1.5 py-0.5 rounded-full">{badge}</span>
              )}
            </Link>
          );
        })}

        <div className="text-xs font-medium text-gray-600 uppercase tracking-wider px-3 py-2 mt-4">
          Trading
        </div>
        {TRADING_NAV.map(({ href, label, icon: Icon }) => {
          const isActive = pathname === href || pathname.startsWith(href);
          return (
            <Link key={href} href={href} className={clsx("sidebar-item", isActive && "sidebar-item-active")}>
              <Icon className="w-4 h-4 flex-shrink-0" />
              <span className="text-sm">{label}</span>
            </Link>
          );
        })}
      </nav>

      {/* Bottom */}
      <div className="p-3 border-t border-gray-800 space-y-1">
        {user && (
          <div className="px-3 py-2 mb-1">
            <div className="text-sm text-gray-300 truncate">{user.full_name || user.email}</div>
            <div className="text-xs text-gray-600 truncate">{user.email}</div>
          </div>
        )}
        <button onClick={logout} className="sidebar-item w-full text-red-400 hover:text-red-300 hover:bg-red-400/10">
          <LogOut className="w-4 h-4" />
          <span className="text-sm">Sign Out</span>
        </button>
      </div>
    </aside>
  );
}

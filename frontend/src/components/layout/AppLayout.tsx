/**
 * SupportFlow AI — Application Layout Shell
 * Responsive sidebar navigation with role-aware menu items.
 */

import React, { useState } from "react";
import { NavLink, useNavigate, Outlet } from "react-router-dom";
import { cn } from "@/utils/cn";
import { useAuth } from "@/context/AuthContext";
import { RoleBadge, Spinner } from "@/components/ui";
import {
  LayoutDashboard,
  Ticket,
  ClipboardList,
  BookOpen,
  BarChart3,
  LogOut,
  Menu,
  X,
  Zap,
  PlusCircle,
  User,
} from "lucide-react";

interface NavItem {
  to: string;
  label: string;
  icon: React.ReactNode;
  roles: string[];
  end?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  // Customer items
  {
    to: "/app",
    label: "My Dashboard",
    icon: <LayoutDashboard className="w-4 h-4" />,
    roles: ["CUSTOMER"],
    end: true,
  },
  {
    to: "/app/tickets",
    label: "My Tickets",
    icon: <Ticket className="w-4 h-4" />,
    roles: ["CUSTOMER"],
  },
  {
    to: "/app/tickets/new",
    label: "Create Ticket",
    icon: <PlusCircle className="w-4 h-4" />,
    roles: ["CUSTOMER"],
  },
  // Agent items
  {
    to: "/agent",
    label: "Dashboard",
    icon: <LayoutDashboard className="w-4 h-4" />,
    roles: ["SUPPORT_AGENT", "ADMIN"],
    end: true,
  },
  {
    to: "/agent/tickets",
    label: "All Tickets",
    icon: <Ticket className="w-4 h-4" />,
    roles: ["SUPPORT_AGENT", "ADMIN"],
  },
  {
    to: "/agent/reviews",
    label: "Review Queue",
    icon: <ClipboardList className="w-4 h-4" />,
    roles: ["SUPPORT_AGENT", "ADMIN"],
  },
  {
    to: "/agent/knowledge",
    label: "Knowledge Base",
    icon: <BookOpen className="w-4 h-4" />,
    roles: ["SUPPORT_AGENT", "ADMIN"],
  },
  // Admin-only items
  {
    to: "/admin/analytics",
    label: "Analytics",
    icon: <BarChart3 className="w-4 h-4" />,
    roles: ["ADMIN"],
  },
];

export const AppLayout: React.FC = () => {
  const { user, logout, isLoading } = useAuth();
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-50">
        <Spinner size="lg" className="text-brand-600" />
      </div>
    );
  }

  const visibleItems = user
    ? NAV_ITEMS.filter((item) => item.roles.includes(user.role))
    : [];

  const NavContent = () => (
    <>
      {/* Logo */}
      <div className="px-5 py-5 border-b border-slate-100 flex items-center gap-2.5">
        <div className="w-7 h-7 rounded-lg bg-brand-600 flex items-center justify-center">
          <Zap className="w-4 h-4 text-white" />
        </div>
        <div>
          <p className="text-sm font-bold text-slate-900 leading-none">SupportFlow</p>
          <p className="text-[10px] text-slate-400 mt-0.5">AI Operations</p>
        </div>
      </div>

      {/* Nav links */}
      <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
        {visibleItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={() => setSidebarOpen(false)}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-brand-50 text-brand-700"
                  : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
              )
            }
          >
            <span className="shrink-0">{item.icon}</span>
            {item.label}
          </NavLink>
        ))}
      </nav>

      {/* User section */}
      {user && (
        <div className="px-3 py-4 border-t border-slate-100">
          <div className="flex items-center gap-3 px-3 py-2 mb-2">
            <div className="w-7 h-7 rounded-full bg-slate-200 flex items-center justify-center shrink-0">
              <User className="w-4 h-4 text-slate-500" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-semibold text-slate-900 truncate">
                {user.full_name || user.email}
              </p>
              <RoleBadge role={user.role} />
            </div>
          </div>
          <button
            onClick={handleLogout}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 hover:bg-rose-50 hover:text-rose-700 transition-colors"
          >
            <LogOut className="w-4 h-4 shrink-0" />
            Sign out
          </button>
        </div>
      )}
    </>
  );

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50">
      {/* Desktop sidebar */}
      <aside className="hidden md:flex md:flex-col md:w-56 bg-white border-r border-slate-200 shrink-0">
        <NavContent />
      </aside>

      {/* Mobile sidebar overlay */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div
            className="fixed inset-0 bg-black/40"
            onClick={() => setSidebarOpen(false)}
          />
          <aside className="fixed left-0 top-0 bottom-0 w-64 bg-white flex flex-col z-50 shadow-xl">
            <button
              className="absolute top-4 right-4 p-1 rounded text-slate-400 hover:text-slate-600"
              onClick={() => setSidebarOpen(false)}
              aria-label="Close sidebar"
            >
              <X className="w-5 h-5" />
            </button>
            <NavContent />
          </aside>
        </div>
      )}

      {/* Main content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Mobile header */}
        <header className="md:hidden flex items-center gap-3 px-4 py-3 bg-white border-b border-slate-200">
          <button
            onClick={() => setSidebarOpen(true)}
            className="p-1.5 rounded-lg text-slate-500 hover:bg-slate-100"
            aria-label="Open navigation"
          >
            <Menu className="w-5 h-5" />
          </button>
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded bg-brand-600 flex items-center justify-center">
              <Zap className="w-3.5 h-3.5 text-white" />
            </div>
            <span className="text-sm font-bold text-slate-900">SupportFlow AI</span>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
};

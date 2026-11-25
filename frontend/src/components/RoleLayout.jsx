import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  ChefHat,
  ChevronDown,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  QrCode,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Store,
  Sun,
  UserCheck,
  UtensilsCrossed,
  X,
} from "lucide-react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { fetchHealth, resetDemoData } from "../api/client";
import { getRoleLabel, useAuth } from "../context/AuthContext";
import { useTheme } from "../context/ThemeContext";

const NAV_BY_ROLE = {
  student: [
    { to: "/student", label: "Menu & Order Portal", icon: UtensilsCrossed, end: true },
  ],
  outlet_manager: [
    { to: "/manager", label: "Kitchen Operations", icon: Store, end: true },
    { to: "/manager/scanner", label: "Counter QR Scanner", icon: QrCode, end: true },
  ],
  admin: [
    { to: "/admin", label: "Platform Overview", icon: ShieldCheck, end: true },
    { to: "/admin/outlets", label: "Outlets & Staff", icon: Store, end: true },
    { to: "/admin/scanner", label: "Counter QR Scanner", icon: QrCode, end: true },
  ],
};

export default function RoleLayout() {
  const { user, authConfig, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const location = useLocation();
  const navigate = useNavigate();

  const [health, setHealth] = useState(null);
  const [resetting, setResetting] = useState(false);
  const [layoutError, setLayoutError] = useState("");
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [userDropdownOpen, setUserDropdownOpen] = useState(false);

  const loadHealth = useCallback(async () => {
    try {
      const h = await fetchHealth();
      setHealth(h);
    } catch {
      setHealth(null);
    }
  }, []);

  const triggerRefresh = useCallback(() => {
    setRefreshNonce((n) => n + 1);
    loadHealth();
  }, [loadHealth]);

  useEffect(() => {
    loadHealth();
  }, [loadHealth, refreshNonce]);

  // Close mobile drawer on route change
  useEffect(() => {
    setMobileMenuOpen(false);
    setUserDropdownOpen(false);
  }, [location.pathname]);

  const handleResetDemo = async () => {
    setLayoutError("");
    setResetting(true);
    try {
      await resetDemoData();
      triggerRefresh();
    } catch (err) {
      setLayoutError(err.message || "Failed to reset demo data.");
    } finally {
      setResetting(false);
    }
  };

  const handleLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  const navItems = NAV_BY_ROLE[user?.role] || [];

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-[#0b0f19] text-slate-900 dark:text-slate-100 flex flex-col md:flex-row transition-colors duration-200">
      {/* Mobile Top Header */}
      <div className="md:hidden flex items-center justify-between px-4 py-3 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 sticky top-0 z-30">
        <div className="flex items-center gap-2.5">
          <div className="h-9 w-9 rounded-xl bg-indigo-600 flex items-center justify-center text-white shadow-sm">
            <ChefHat className="w-5 h-5" />
          </div>
          <div>
            <div className="text-sm font-bold tracking-tight leading-none text-slate-900 dark:text-white">
              GALLEY<span className="text-indigo-600 dark:text-indigo-400">CONTROL</span>
            </div>
            <div className="text-[10px] text-slate-500 dark:text-slate-400 truncate max-w-[160px]">
              {user?.organisation_name || "Campus Canteen"}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={toggleTheme}
            className="p-2 rounded-lg text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition"
            title="Toggle theme"
          >
            {theme === "dark" ? <Sun className="w-4 h-4 text-amber-400" /> : <Moon className="w-4 h-4 text-slate-600" />}
          </button>
          <button
            type="button"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            className="p-2 rounded-lg text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition"
            aria-label="Toggle menu"
          >
            {mobileMenuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </div>
      </div>

      {/* Mobile Navigation Drawer */}
      {mobileMenuOpen && (
        <div className="md:hidden fixed inset-0 z-40 bg-black/50 backdrop-blur-sm flex flex-col">
          <div className="w-4/5 max-w-xs bg-white dark:bg-slate-900 h-full p-5 flex flex-col shadow-2xl border-r border-slate-200 dark:border-slate-800 animate-in slide-in-from-left duration-200">
            <div className="flex items-center justify-between pb-4 border-b border-slate-200 dark:border-slate-800">
              <div className="flex items-center gap-2">
                <div className="h-8 w-8 rounded-lg bg-indigo-600 flex items-center justify-center text-white font-bold">
                  GC
                </div>
                <div className="font-bold text-sm tracking-tight">Galley Control</div>
              </div>
              <button
                type="button"
                onClick={() => setMobileMenuOpen(false)}
                className="p-1 rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="py-4">
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2 px-3">
                Navigation
              </div>
              <nav className="space-y-1">
                {navItems.map(({ to, label, icon: Icon, end }) => (
                  <NavLink
                    key={to}
                    to={to}
                    end={end}
                    className={({ isActive }) =>
                      `flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition ${
                        isActive
                          ? "bg-indigo-600 text-white shadow-sm"
                          : "text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800"
                      }`
                    }
                  >
                    <Icon className="w-4 h-4" />
                    <span>{label}</span>
                  </NavLink>
                ))}
              </nav>
            </div>

            <div className="mt-auto pt-4 border-t border-slate-200 dark:border-slate-800 space-y-3">
              <div className="px-3 py-2 rounded-xl bg-slate-100 dark:bg-slate-800/60">
                <div className="text-xs font-medium text-slate-900 dark:text-white truncate">
                  {user?.full_name}
                </div>
                <div className="text-[11px] text-slate-500 dark:text-slate-400">
                  {user?.role === "outlet_manager"
                    ? user?.is_org_manager
                      ? "Org Manager"
                      : "Outlet Manager"
                    : user?.role === "admin"
                      ? "Platform Admin"
                      : "Student"}
                </div>
              </div>
              <button
                type="button"
                onClick={handleLogout}
                className="w-full flex items-center justify-center gap-2 px-3 py-2.5 rounded-xl text-sm font-medium text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-950/40 hover:bg-rose-100 transition"
              >
                <LogOut className="w-4 h-4" />
                <span>Log Out</span>
              </button>
            </div>
          </div>
          <div className="flex-1" onClick={() => setMobileMenuOpen(false)} />
        </div>
      )}

      {/* Desktop SaaS Sidebar */}
      <aside className="hidden md:flex flex-col w-64 bg-white dark:bg-slate-900 border-r border-slate-200 dark:border-slate-800 shrink-0 select-none">
        {/* Brand Header */}
        <div className="p-5 border-b border-slate-200 dark:border-slate-800">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-xl bg-gradient-to-tr from-indigo-700 to-indigo-500 flex items-center justify-center text-white shadow-md shadow-indigo-500/20">
              <ChefHat className="w-5 h-5" />
            </div>
            <div>
              <div className="text-base font-extrabold tracking-tight text-slate-900 dark:text-white leading-none">
                GALLEY<span className="text-indigo-600 dark:text-indigo-400"> CONTROL</span>
              </div>
              <div className="text-[11px] font-medium text-slate-500 dark:text-slate-400 mt-1 flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block animate-pulse" />
                <span className="truncate max-w-[130px]">{user?.organisation_name || "Campus Network"}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Tenant/Org Context Banner */}
        <div className="px-5 py-3 bg-slate-50 dark:bg-slate-950/40 border-b border-slate-200 dark:border-slate-800/80">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500">
            Active Workspace
          </div>
          <div className="text-xs font-medium text-slate-700 dark:text-slate-300 truncate mt-0.5">
            {user?.role === "admin"
              ? "Multi-Tenant Platform"
              : user?.outlet_name
                ? `${user.outlet_name}`
                : user?.organisation_name || "Campus Canteen"}
          </div>
        </div>

        {/* Navigation Menu */}
        <div className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          <div className="px-3 py-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500">
            Workspace
          </div>
          {navItems.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm font-medium transition duration-150 ${
                  isActive
                    ? "bg-indigo-600 text-white shadow-sm shadow-indigo-600/30"
                    : "text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800/60"
                }`
              }
            >
              <Icon className="w-4 h-4 shrink-0" />
              <span className="truncate">{label}</span>
            </NavLink>
          ))}
        </div>

        {/* Bottom System & User Section */}
        <div className="p-4 border-t border-slate-200 dark:border-slate-800 space-y-3">
          {/* Health & LLM Status Indicator */}
          <div className="flex items-center justify-between text-xs px-2 py-1.5 rounded-lg bg-slate-100 dark:bg-slate-800/50">
            <div className="flex items-center gap-1.5 text-slate-600 dark:text-slate-300">
              <Activity className="w-3.5 h-3.5 text-emerald-500" />
              <span>{health?.status === "ok" ? "System Ready" : "Connecting..."}</span>
            </div>
            {health?.llm_mode === "hosted_llm" ? (
              <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-950/60 px-1.5 py-0.5 rounded border border-indigo-200 dark:border-indigo-800">
                <Sparkles className="w-2.5 h-2.5" />
                Gemini
              </span>
            ) : (
              <span className="text-[10px] text-slate-400 font-mono">SQLite</span>
            )}
          </div>

          {/* Theme Switcher Button */}
          <button
            type="button"
            onClick={toggleTheme}
            className="w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs font-medium text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition"
          >
            <span className="flex items-center gap-2">
              {theme === "dark" ? <Moon className="w-4 h-4 text-indigo-400" /> : <Sun className="w-4 h-4 text-amber-500" />}
              <span>{theme === "dark" ? "Dark Theme" : "Light Theme"}</span>
            </span>
            <span className="text-[10px] uppercase font-semibold tracking-wider text-slate-400">Toggle</span>
          </button>

          {/* User Profile Card & Logout */}
          <div className="flex items-center justify-between pt-2 border-t border-slate-200 dark:border-slate-800">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="h-8 w-8 rounded-full bg-indigo-100 dark:bg-indigo-950 border border-indigo-200 dark:border-indigo-800 flex items-center justify-center text-xs font-bold text-indigo-700 dark:text-indigo-300 shrink-0">
                {user?.full_name?.charAt(0) || "U"}
              </div>
              <div className="min-w-0">
                <div className="text-xs font-semibold text-slate-900 dark:text-white truncate">
                  {user?.full_name}
                </div>
                <div className="text-[10px] text-slate-500 dark:text-slate-400 truncate">
                  {user?.role === "outlet_manager"
                    ? user?.is_org_manager
                      ? "Org Manager"
                      : "Outlet Manager"
                    : user?.role === "admin"
                      ? "Platform Admin"
                      : "Student"}
                </div>
              </div>
            </div>
            <button
              type="button"
              onClick={handleLogout}
              className="p-1.5 rounded-lg text-slate-400 hover:text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-950/40 transition"
              title="Logout"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 overflow-y-auto">
        {/* Top bar for desktop */}
        <header className="hidden md:flex items-center justify-between px-8 py-3.5 bg-white dark:bg-slate-900/60 border-b border-slate-200 dark:border-slate-800/80 backdrop-blur sticky top-0 z-10">
          <div className="flex items-center gap-3 text-sm">
            <span className="font-semibold text-slate-800 dark:text-slate-200">
              {navItems.find((item) => item.to === location.pathname)?.label || "Galley Control Console"}
            </span>
            <span className="text-slate-300 dark:text-slate-700">•</span>
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {user?.organisation_name || "Enterprise"}
            </span>
          </div>

          <div className="flex items-center gap-3">
            {user?.role === "admin" && authConfig?.demo_mode && (
              <button
                type="button"
                onClick={handleResetDemo}
                disabled={resetting}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 shadow-sm transition"
                title="Reset SQLite back to clean seeded demo data (Development Only)"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                <span>{resetting ? "Resetting..." : "Reset Demo"}</span>
              </button>
            )}

            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300">
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
              <span>{user?.organisation_name || "Live System"}</span>
            </div>
          </div>
        </header>

        {/* Main Body */}
        <main className="flex-1 p-4 sm:p-6 lg:p-8 max-w-7xl w-full mx-auto">
          {layoutError && (
            <div className="mb-6 rounded-2xl border border-rose-300 dark:border-rose-800 bg-rose-50 dark:bg-rose-950/40 px-5 py-4 text-sm text-rose-800 dark:text-rose-200 shadow-sm">
              <strong>Error:</strong> {layoutError}
            </div>
          )}
          <Outlet context={{ refreshNonce, triggerRefresh }} />
        </main>
      </div>
    </div>
  );
}

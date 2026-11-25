import { useEffect, useState } from "react";
import {
  Building2,
  CheckCircle2,
  ChefHat,
  Eye,
  EyeOff,
  GraduationCap,
  Lock,
  LogIn,
  LogOut,
  ShieldCheck,
  Store,
  User,
  UserPlus,
  UtensilsCrossed,
} from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { getDefaultRouteForRole, getRoleLabel, useAuth } from "../context/AuthContext";

const ROLES = [
  {
    id: "student",
    title: "Student Login",
    badge: "STUDENT PORTAL",
    tagline: "Dining & Digital QR Passes",
    scope: "Browse daily canteen menus, place advance orders, and retrieve digital pickup QR passes.",
    icon: GraduationCap,
    accent: "indigo",
    activeClass:
      "border-indigo-600 dark:border-indigo-500 bg-indigo-50/70 dark:bg-indigo-950/40 shadow-md ring-2 ring-indigo-500/30",
    inactiveClass:
      "border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-slate-300 dark:hover:border-slate-700",
    badgeClass:
      "bg-indigo-100 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300 border-indigo-200 dark:border-indigo-800",
    buttonClass: "bg-indigo-600 hover:bg-indigo-700 text-white shadow-indigo-600/30",
    iconBg: "bg-indigo-600 text-white",
    placeholder: "student@campus.edu or username",
    buttonLabel: "Sign In as Student",
    portalDesc: "Access the campus student portal to browse food menus, track live kitchen wait times, and place orders.",
  },
  {
    id: "outlet_manager",
    title: "Outlet Manager Login",
    badge: "KITCHEN OPERATIONS",
    tagline: "Queue & Menu Photo Studio",
    scope: "Manage live kitchen queues, food photography & dish studio, and counter QR scanner.",
    icon: Store,
    accent: "amber",
    activeClass:
      "border-amber-500 dark:border-amber-400 bg-amber-50/70 dark:bg-amber-950/40 shadow-md ring-2 ring-amber-500/30",
    inactiveClass:
      "border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-slate-300 dark:hover:border-slate-700",
    badgeClass:
      "bg-amber-100 dark:bg-amber-950 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800",
    buttonClass: "bg-amber-600 hover:bg-amber-700 text-white shadow-amber-600/30",
    iconBg: "bg-amber-500 text-white",
    placeholder: "manager@canteen.edu or username",
    buttonLabel: "Sign In as Outlet Manager",
    portalDesc: "Access kitchen operations for your assigned outlet, update dish stock, upload food photos, and scan order QR passes.",
  },
  {
    id: "admin",
    title: "Organisation Admin Login",
    badge: "CAMPUS & PLATFORM ADMIN",
    tagline: "Governance & Outlets",
    scope: "Oversee campus outlets, provision manager accounts, and monitor organisation-wide analytics.",
    icon: ShieldCheck,
    accent: "emerald",
    activeClass:
      "border-emerald-600 dark:border-emerald-500 bg-emerald-50/70 dark:bg-emerald-950/40 shadow-md ring-2 ring-emerald-500/30",
    inactiveClass:
      "border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-slate-300 dark:hover:border-slate-700",
    badgeClass:
      "bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800",
    buttonClass: "bg-emerald-600 hover:bg-emerald-700 text-white shadow-emerald-600/30",
    iconBg: "bg-emerald-600 text-white",
    placeholder: "admin@galley.edu or username",
    buttonLabel: "Sign In as Organisation Admin",
    portalDesc: "Access platform and organisation governance, configure canteen outlets, provision supervisor staff, and inspect 8-agent AI telemetry.",
  },
];

export default function LoginPage() {
  const { user, login, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const searchParams = new URLSearchParams(location.search);
  const paramRole = searchParams.get("role");
  const initialRole = ["student", "outlet_manager", "admin"].includes(paramRole)
    ? paramRole
    : "student";

  const [selectedRole, setSelectedRole] = useState(initialRole);
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (paramRole && ["student", "outlet_manager", "admin"].includes(paramRole)) {
      setSelectedRole(paramRole);
    }
  }, [paramRole]);

  const activeRoleConfig =
    ROLES.find((r) => r.id === selectedRole) || ROLES[0];

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setNotice("");

    if (!identifier.trim() || !password) {
      setError("Please enter both your email/username and password.");
      return;
    }

    setSubmitting(true);
    try {
      // Authenticate with existing backend authentication system
      const authenticatedUser = await login(identifier.trim(), password);
      // Derive target strictly from the verified database role returned by backend
      const actualRole = authenticatedUser.role;
      const targetRoute = getDefaultRouteForRole(actualRole);

      // If user signed in on a different tab than their database role, provide clear feedback
      if (selectedRole !== actualRole) {
        setNotice(
          `Authenticated as ${getRoleLabel(actualRole)}. Redirecting to your authorised ${getRoleLabel(actualRole)} Dashboard...`
        );
        setTimeout(() => {
          navigate(targetRoute, { replace: true });
        }, 800);
      } else {
        navigate(targetRoute, { replace: true });
      }
    } catch (err) {
      setError(err.message || "Authentication failed. Please verify your credentials.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-[#0b0f19] text-slate-900 dark:text-slate-100 flex flex-col justify-center items-center p-4 sm:p-6 transition-colors duration-200">
      <div className="w-full max-w-4xl space-y-6">
        {/* Header Branding */}
        <div className="text-center space-y-2">
          <div className="inline-flex items-center gap-3">
            <div className="h-12 w-12 rounded-2xl bg-gradient-to-tr from-indigo-700 to-indigo-500 flex items-center justify-center text-white shadow-lg shadow-indigo-500/25">
              <ChefHat className="w-6 h-6" />
            </div>
            <div className="text-left">
              <h1 className="text-2xl font-black tracking-tight text-slate-900 dark:text-white leading-none">
                GALLEY<span className="text-indigo-600 dark:text-indigo-400"> CONTROL</span>
              </h1>
              <p className="text-xs font-semibold text-slate-500 dark:text-slate-400 mt-1">
                Multi-Tenant Campus Canteen SaaS
              </p>
            </div>
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 max-w-md mx-auto">
            Select your role below to access your authorised dining, kitchen operations, or campus administration workspace.
          </p>
        </div>

        {/* Active Session Notification (prevents user from being trapped in redirect loop) */}
        {user && (
          <div className="rounded-2xl border border-indigo-200 dark:border-indigo-800 bg-white dark:bg-slate-900 p-4 shadow-sm flex flex-col sm:flex-row items-center justify-between gap-3 text-xs">
            <div className="flex items-center gap-3">
              <div className="h-9 w-9 rounded-xl bg-indigo-600 text-white flex items-center justify-center font-bold text-sm">
                {user.full_name?.charAt(0) || "U"}
              </div>
              <div>
                <div className="font-bold text-slate-900 dark:text-white flex items-center gap-2">
                  <span>Currently Signed In: {user.full_name}</span>
                  <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-indigo-100 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-800">
                    {getRoleLabel(user.role).toUpperCase()}
                  </span>
                </div>
                <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">
                  {user.email} • {user.organisation_name || "Campus Network"}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2 w-full sm:w-auto">
              <button
                type="button"
                onClick={() => navigate(getDefaultRouteForRole(user.role), { replace: true })}
                className="flex-1 sm:flex-initial px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-xs shadow-sm transition"
              >
                Go to Dashboard
              </button>
              <button
                type="button"
                onClick={async () => {
                  await logout();
                  setError("");
                  setNotice("");
                }}
                className="flex-1 sm:flex-initial px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-800 text-slate-700 dark:text-slate-300 font-semibold text-xs hover:bg-slate-100 dark:hover:bg-slate-800 transition flex items-center justify-center gap-1.5"
              >
                <LogOut className="w-3.5 h-3.5" />
                <span>Sign Out</span>
              </button>
            </div>
          </div>
        )}

        {/* 1. THREE CLEARLY VISIBLE ROLE LOGIN OPTIONS */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {ROLES.map((role) => {
            const Icon = role.icon;
            const isSelected = selectedRole === role.id;
            return (
              <button
                key={role.id}
                type="button"
                onClick={() => {
                  setSelectedRole(role.id);
                  setError("");
                  setNotice("");
                }}
                className={`relative text-left p-4 rounded-2xl border transition-all duration-200 flex flex-col justify-between space-y-3 cursor-pointer ${
                  isSelected ? role.activeClass : role.inactiveClass
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className={`h-10 w-10 rounded-xl flex items-center justify-center ${role.iconBg} shadow-sm`}>
                    <Icon className="w-5 h-5" />
                  </div>
                  <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${role.badgeClass}`}>
                    {role.badge}
                  </span>
                </div>

                <div>
                  <div className="font-bold text-sm text-slate-900 dark:text-white flex items-center gap-1.5">
                    <span>{role.title}</span>
                    {isSelected && <CheckCircle2 className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />}
                  </div>
                  <p className="text-xs text-slate-500 dark:text-slate-400 font-medium mt-0.5">
                    {role.tagline}
                  </p>
                  <p className="text-[11px] text-slate-400 dark:text-slate-500 mt-2 line-clamp-2 leading-relaxed">
                    {role.scope}
                  </p>
                </div>
              </button>
            );
          })}
        </div>

        {/* 2. ROLE-SPECIFIC LOGIN CONTAINER */}
        <div className="bg-white dark:bg-slate-900 rounded-3xl border border-slate-200 dark:border-slate-800 p-6 sm:p-8 shadow-sm space-y-6">
          <div className="space-y-1.5 border-b border-slate-100 dark:border-slate-800 pb-4">
            <div className="flex items-center gap-2">
              <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold border ${activeRoleConfig.badgeClass}`}>
                {activeRoleConfig.badge}
              </span>
              <span className="text-xs font-semibold text-slate-400">• Authenticated Role Verification</span>
            </div>
            <h2 className="text-xl font-bold text-slate-900 dark:text-white">
              {activeRoleConfig.title}
            </h2>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {activeRoleConfig.portalDesc}
            </p>
          </div>

          {error && (
            <div
              role="alert"
              className="rounded-2xl border border-rose-300 dark:border-rose-800 bg-rose-50 dark:bg-rose-950/40 px-4 py-3 text-xs text-rose-800 dark:text-rose-200 shadow-sm"
            >
              {error}
            </div>
          )}

          {notice && (
            <div
              role="status"
              className="rounded-2xl border border-emerald-300 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/40 px-4 py-3 text-xs text-emerald-800 dark:text-emerald-200 shadow-sm flex items-center gap-2"
            >
              <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0" />
              <span>{notice}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label
                htmlFor="login-identifier"
                className="block text-xs font-semibold text-slate-700 dark:text-slate-300"
              >
                Email or Username
              </label>
              <div className="relative">
                <User className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
                <input
                  id="login-identifier"
                  type="text"
                  autoComplete="username"
                  placeholder={activeRoleConfig.placeholder}
                  value={identifier}
                  onChange={(e) => setIdentifier(e.target.value)}
                  className="w-full rounded-2xl bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-700 pl-10 pr-4 py-3 text-xs text-slate-900 dark:text-white placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label
                  htmlFor="login-password"
                  className="block text-xs font-semibold text-slate-700 dark:text-slate-300"
                >
                  Password
                </label>
                <Link
                  to="/forgot-password"
                  className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline font-medium"
                >
                  Forgot password?
                </Link>
              </div>
              <div className="relative">
                <Lock className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
                <input
                  id="login-password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  placeholder="Enter your password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full rounded-2xl bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-700 pl-10 pr-10 py-3 text-xs text-slate-900 dark:text-white placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((prev) => !prev)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 p-1"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={submitting}
              className={`w-full py-3.5 rounded-2xl font-bold text-xs shadow-md disabled:opacity-50 flex items-center justify-center gap-2 transition cursor-pointer ${activeRoleConfig.buttonClass}`}
            >
              <LogIn className="w-4 h-4" />
              <span>
                {submitting
                  ? "Verifying Permissions..."
                  : activeRoleConfig.buttonLabel}
              </span>
            </button>
          </form>

          {/* Role-Specific Contextual Links & Guidance */}
          <div className="pt-4 border-t border-slate-100 dark:border-slate-800 space-y-3 text-xs">
            {selectedRole === "student" && (
              <div className="flex items-center justify-between gap-2">
                <span className="text-slate-500">New campus student?</span>
                <Link
                  to="/register"
                  className="inline-flex items-center gap-1.5 text-indigo-600 dark:text-indigo-400 hover:underline font-bold"
                >
                  <UserPlus className="w-3.5 h-3.5" />
                  <span>Create Student Account</span>
                </Link>
              </div>
            )}

            {selectedRole === "outlet_manager" && (
              <div className="p-3 rounded-xl bg-amber-50/70 dark:bg-amber-950/30 border border-amber-200/60 dark:border-amber-900/40 text-[11px] text-amber-900 dark:text-amber-200 space-y-1">
                <div className="font-bold flex items-center gap-1.5">
                  <Store className="w-3.5 h-3.5" />
                  <span>Outlet Manager Provisioning</span>
                </div>
                <p className="text-amber-800 dark:text-amber-300">
                  Manager accounts are strictly provisioned by your campus Organisation Administrator. Contact your canteen administrator if you need your account provisioned or assigned to an outlet.
                </p>
              </div>
            )}

            {selectedRole === "admin" && (
              <div className="flex items-center justify-between gap-2">
                <span className="text-slate-500">New college or canteen network?</span>
                <Link
                  to="/register-org"
                  className="inline-flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400 hover:underline font-bold"
                >
                  <Building2 className="w-3.5 h-3.5" />
                  <span>Register College Organisation</span>
                </Link>
              </div>
            )}

            <div className="flex items-center justify-between text-[11px] text-slate-400 pt-1">
              <span>Security Protected</span>
              <span>Server-side tenant isolation & RBAC verified</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
